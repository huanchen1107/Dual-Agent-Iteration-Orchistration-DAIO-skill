from __future__ import annotations
import asyncio
import datetime
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    TERMINAL_PHASES,
    is_terminal_phase,
)
from .router import DAIORoleRouter
from .store import DAIOWorkStore, SqliteDAIOWorkStore
from .adapters.executor import EngineeringExecutorAdapter, SubprocessWorkspaceExecutor, ExecutionResult
from .adapters.bridge import ArchitectBridgeAdapter, MockArchitectBridgeAdapter

logger = logging.getLogger("DAIO_Closed_Loop")


class DAIOClosedLoopOrchestrator:
    """
    Autonomous Closed Loop Orchestrator managing multi-turn engineering & review cycles.
    Enforces 'Human relay count = 0' and fail-closed safety breakers.
    Supports autonomous continuous orchestration (Phase S5.5).
    """

    def __init__(
        self,
        store: Optional[DAIOWorkStore] = None,
        executor: Optional[EngineeringExecutorAdapter] = None,
        bridge: Optional[ArchitectBridgeAdapter] = None,
        max_rounds: int = 10,
        consecutive_errors_cap: int = 3,
        default_test_command: Optional[str] = None,
    ) -> None:
        self.store = store or SqliteDAIOWorkStore()
        self.executor = executor or SubprocessWorkspaceExecutor()
        self.bridge = bridge or MockArchitectBridgeAdapter()
        self.max_rounds = max_rounds
        self.consecutive_errors_cap = consecutive_errors_cap
        self.default_test_command = default_test_command
        self.round_history: List[Dict[str, Any]] = []

    def create_work_item(
        self,
        change_id: str,
        project_root: str,
        initial_action: str,
        allowed_scope: Optional[List[str]] = None,
        architect_endpoint: Optional[Dict[str, Any]] = None,
        parent_work_id: Optional[str] = None,
    ) -> DAIOWorkItem:
        work = DAIOWorkItem(
            work_id=f"daio-{uuid.uuid4().hex[:8]}",
            project_root=project_root,
            change_id=change_id,
            current_stage=change_id,
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            requested_action=initial_action,
            allowed_scope=allowed_scope or [],
            architect_endpoint=architect_endpoint or {},
            parent_work_id=parent_work_id,
            status=DAIOStatus.AWAITING_REVIEW,
        )
        self.store.save_work_item(work)
        return work

    def resolve_next_work_item(self, completed_work: DAIOWorkItem, next_phase: Optional[str]) -> Optional[DAIOWorkItem]:
        """
        Idempotently resolve or create the next WorkItem for an authorized next_phase.
        Never invents work for terminal, stop, or empty phases.
        Preserves provenance linking successor/root work items to the authorization that created them.
        """
        if not next_phase or not isinstance(next_phase, str):
            return None

        clean_phase = next_phase.strip().upper()
        if not clean_phase or is_terminal_phase(clean_phase):
            return None

        # Determine work identity and root status
        safe_parent = completed_work.work_id.replace(" ", "_")
        safe_phase = next_phase.strip().replace(" ", "_").replace("/", "_")

        is_production_root = (
            next_phase.strip().startswith("CHANGE_")
            or completed_work.current_stage.startswith("STAGE_")
            or "COMPLETE" in completed_work.current_stage.upper()
        )

        if is_production_root:
            next_work_id = f"daio-root-{safe_phase.lower()}"
        else:
            next_work_id = f"{safe_parent}__to__{safe_phase.lower()}"

        # Check if already exists in store (idempotency)
        existing = self.store.load_work_item(next_work_id)
        if existing:
            logger.info(f"NEXT_WORK_RECOVERED: work_id={existing.work_id}, parent_id={completed_work.work_id}, phase={next_phase}")
            return existing

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Create new work item with authorized context & provenance
        next_work = DAIOWorkItem(
            work_id=next_work_id,
            parent_work_id=completed_work.work_id,
            project_root=completed_work.project_root,
            change_id=next_phase.strip(),
            current_stage=next_phase.strip(),
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            requested_action=f"Initiate authorized work for {next_phase.strip()} following {completed_work.work_id}",
            allowed_scope=list(completed_work.allowed_scope),
            base_sha=completed_work.head_sha or completed_work.base_sha,
            head_sha=completed_work.head_sha or completed_work.base_sha,
            status=DAIOStatus.AWAITING_REVIEW,
            architect_endpoint=dict(completed_work.architect_endpoint),
            metadata={
                "derived_from_work_id": completed_work.work_id,
                "authorized_next_phase": next_phase.strip(),
                "authorization_source": "ARCHITECT_POST_COMPLETION_HANDOFF" if is_production_root else "IN_CHAIN_SUCCESSOR",
                "is_production_root": is_production_root,
                "authorized_at": now_iso,
                "parent_head_sha": completed_work.head_sha,
            }
        )
        self.store.save_work_item(next_work)
        if is_production_root:
            logger.info(f"NEW_ROOT_WORK_ITEM_CREATED: work_id={next_work.work_id}, change_id={next_phase}, parent_id={completed_work.work_id}")
        else:
            logger.info(f"NEXT_WORK_CREATED: work_id={next_work.work_id}, parent_id={completed_work.work_id}, phase={next_phase}")
        return next_work

    async def run_autonomous_loop(self, work_id: str, worker_id: Optional[str] = None) -> DAIOWorkItem:
        """
        Execute the autonomous closed loop until COMPLETED, HUMAN_GATE_REQUIRED, or BLOCKED.
        Enforces 0 human relays.
        """
        if not worker_id:
            existing = self.store.load_work_item(work_id)
            if existing and existing.claimed_by:
                worker_id = existing.claimed_by
            else:
                worker_id = f"worker-{uuid.uuid4().hex[:6]}"

        lease_id = self.store.acquire_lease(work_id, worker_id, ttl_seconds=300)
        if not lease_id:
            raise PermissionError(f"Cannot acquire lease for work item '{work_id}' (already locked).")

        consecutive_errors = 0
        previous_reviewed_sha: Optional[str] = None
        previous_reviewed_gate: Optional[DAIOGate] = None
        rounds_executed = 0

        try:
            while rounds_executed < self.max_rounds:
                work = self.store.load_work_item(work_id)
                if not work:
                    raise KeyError(f"Work item '{work_id}' not found.")

                if work.status in {DAIOStatus.COMPLETED, DAIOStatus.HUMAN_GATE_REQUIRED, DAIOStatus.BLOCKED}:
                    logger.info(f"Loop terminating with terminal status: {work.status.value}")
                    if work.status == DAIOStatus.COMPLETED:
                        logger.info(f"CURRENT_WORK_COMPLETED: work_id={work.work_id}, stage={work.current_stage}")
                    break

                rounds_executed += 1
                logger.info(f"--- [DAIO Closed Loop Round {rounds_executed}/{self.max_rounds}] Gate: {work.current_gate.value}, Role: {work.assigned_role.value} ---")

                # =========================================================================
                # Branch 1: LEAD_ARCHITECT_REVIEW turn
                # =========================================================================
                if work.assigned_role == DAIORole.LEAD_ARCHITECT_REVIEW:
                    # Invariant DAIO-001: Repeated SHA without code modification check on IMPLEMENTATION_GATE
                    if (
                        work.head_sha
                        and work.head_sha == previous_reviewed_sha
                        and work.current_gate == previous_reviewed_gate
                        and work.current_gate == DAIOGate.IMPLEMENTATION_GATE
                    ):
                        work.status = DAIOStatus.HUMAN_GATE_REQUIRED
                        work.human_gate_reason = f"DAIO-001 Zero progress: Repeated review on identical HEAD SHA ({work.head_sha}) at {work.current_gate.value}"
                        self.store.save_work_item(work)
                        break

                    # Format review package
                    if work.current_gate == DAIOGate.CONTRACT_GATE:
                        report_markdown = f"""🏛️ **[DAIO v2.1 Closed Loop Review — Gate: CONTRACT_GATE]**

Lead Architect,

Persistent DAIO worker has active work item:
- **Work ID:** `{work.work_id}`
- **Current Stage / Change ID:** `{work.change_id}`
- **Parent Work ID:** `{work.parent_work_id or 'ROOT'}`
- **Current Gate:** `{work.current_gate.value}`
- **Commit SHA:** `{work.head_sha or 'INITIAL'}`
- **Action:** {work.requested_action}

Please provide your review instruction in a structured decision block:
```json
{{
  "decision": "REVISE",
  "current_phase": "{work.change_id}",
  "next_phase": null,
  "action": "RUN",
  "human_approval_required": false,
  "instruction": "<Specify engineering task or preflight instruction>"
}}
```
"""
                    else:
                        exec_report = work.metadata.get("last_execution_report", work.requested_action)
                        report_markdown = f"""🏛️ **[DAIO v2.1 Closed Loop Review — Gate: IMPLEMENTATION_GATE]**

Lead Architect,

The Engineering Agent has executed the task and passed all test integrity gates:
- **Work ID:** `{work.work_id}`
- **Current Stage / Change ID:** `{work.change_id}`
- **Parent Work ID:** `{work.parent_work_id or 'ROOT'}`
- **Current Gate:** `{work.current_gate.value}`
- **Commit SHA:** `{work.head_sha or 'INITIAL'}`
- **Test Integrity Gate:** PASSED

### Task / Execution Report:
{exec_report}

If approved, please return an `APPROVE` decision. If this work authorizes a subsequent work item, specify `next_phase`:
```json
{{
  "decision": "APPROVE",
  "current_phase": "{work.change_id}",
  "next_phase": null,
  "action": "PROCEED",
  "human_approval_required": false,
  "instruction": "Work approved."
}}
```
"""
                    try:
                        decision = await self.bridge.transmit_review_request(work, report_markdown)
                        consecutive_errors = 0
                        previous_reviewed_sha = work.head_sha
                        previous_reviewed_gate = work.current_gate

                        # Record turn history and log decision persistence
                        turn_id = f"turn-{uuid.uuid4().hex[:8]}"
                        if hasattr(self.store, "record_turn_history"):
                            self.store.record_turn_history(
                                turn_id=turn_id,
                                work_id=work.work_id,
                                role=DAIORole.LEAD_ARCHITECT_REVIEW.value,
                                action_summary=decision.instruction or decision.decision,
                                commit_sha=work.head_sha or "INITIAL",
                                status=decision.decision,
                                payload={
                                    "decision": decision.decision,
                                    "current_phase": decision.current_phase,
                                    "next_phase": decision.next_phase,
                                    "action": decision.action,
                                    "human_approval_required": decision.human_approval_required,
                                    "instruction": decision.instruction,
                                }
                            )
                        logger.info(f"ARCHITECT_DECISION_PERSISTED: work_id={work.work_id}, decision={decision.decision}, phase={decision.current_phase}, next_phase={decision.next_phase}")

                        # Process routing
                        work = DAIORoleRouter.process_architect_review(work, decision, DAIORole.LEAD_ARCHITECT_REVIEW)
                        self.round_history.append({
                            "round": rounds_executed,
                            "role": DAIORole.LEAD_ARCHITECT_REVIEW.value,
                            "gate": work.current_gate.value,
                            "decision": decision.decision,
                            "instruction": decision.instruction,
                            "sha": work.head_sha,
                        })
                        self.store.save_work_item(work)

                        if work.status == DAIOStatus.COMPLETED:
                            logger.info(f"CURRENT_WORK_COMPLETED: work_id={work.work_id}, stage={work.current_stage}")
                            if decision.next_phase and not is_terminal_phase(decision.next_phase):
                                self.resolve_next_work_item(work, decision.next_phase)
                            break

                    except Exception as ex:
                        consecutive_errors += 1
                        logger.error(f"Error during Architect review turn ({consecutive_errors}/{self.consecutive_errors_cap}): {ex}")
                        if consecutive_errors >= self.consecutive_errors_cap:
                            work.status = DAIOStatus.HUMAN_GATE_REQUIRED
                            work.human_gate_reason = f"DAIO-003 Error Cap Reached: {ex}"
                            self.store.save_work_item(work)
                            break

                # =========================================================================
                # Branch 2: ENGINEERING_EXECUTION turn
                # =========================================================================
                elif work.assigned_role == DAIORole.ENGINEERING_EXECUTION:
                    try:
                        # Execute task & run test gate
                        async_fn = getattr(self.executor, "execute_task_async", None)
                        if callable(async_fn) and asyncio.iscoroutinefunction(async_fn):
                            exec_res = await async_fn(
                                work=work,
                                test_command=self.default_test_command,
                                commit_message=f"feat(daio): automated execution round {rounds_executed} for {work.change_id}",
                            )
                        else:
                            raw_res = self.executor.execute_task(
                                work=work,
                                command=None,
                                test_command=self.default_test_command,
                                commit_message=f"feat(daio): automated execution round {rounds_executed} for {work.change_id}",
                            )
                            if asyncio.iscoroutine(raw_res):
                                exec_res = await raw_res
                            else:
                                exec_res = raw_res

                        # Check Scope Violation (DAIO-002)
                        if exec_res.scope_violation:
                            work.status = DAIOStatus.HUMAN_GATE_REQUIRED
                            work.human_gate_reason = f"DAIO-002 Scope Violation: {exec_res.error_message}"
                            self.store.save_work_item(work)
                            break

                        consecutive_errors = 0 if exec_res.success else (consecutive_errors + 1)

                        # Process routing
                        work = DAIORoleRouter.process_engineering_completion(
                            work=work,
                            acting_role=DAIORole.ENGINEERING_EXECUTION,
                            test_passed=exec_res.test_passed,
                            commit_sha=exec_res.commit_sha,
                            execution_error=exec_res.error_message,
                        )
                        if not hasattr(work, "metadata") or work.metadata is None:
                            work.metadata = {}
                        if exec_res.proposal:
                            report = getattr(exec_res.proposal, "reasoning_summary", "") or getattr(exec_res.proposal, "raw_response", "") or exec_res.output
                            work.metadata["last_execution_report"] = report
                        elif exec_res.output:
                            work.metadata["last_execution_report"] = exec_res.output

                        self.round_history.append({
                            "round": rounds_executed,
                            "role": DAIORole.ENGINEERING_EXECUTION.value,
                            "gate": work.current_gate.value,
                            "test_passed": exec_res.test_passed,
                            "sha": exec_res.commit_sha,
                            "diff_files": exec_res.diff_files,
                        })
                        self.store.save_work_item(work)

                    except Exception as ex:
                        consecutive_errors += 1
                        logger.error(f"Error during Engineering turn ({consecutive_errors}/{self.consecutive_errors_cap}): {ex}")
                        if consecutive_errors >= self.consecutive_errors_cap:
                            work.status = DAIOStatus.HUMAN_GATE_REQUIRED
                            work.human_gate_reason = f"DAIO-003 Error Cap Reached: {ex}"
                            self.store.save_work_item(work)
                            break

            # If loop exited because of max rounds
            if rounds_executed >= self.max_rounds and work.status not in {DAIOStatus.COMPLETED, DAIOStatus.HUMAN_GATE_REQUIRED}:
                work.status = DAIOStatus.HUMAN_GATE_REQUIRED
                work.human_gate_reason = f"DAIO-003 Max autonomous rounds ({self.max_rounds}) reached."
                self.store.save_work_item(work)

            return work

        finally:
            self.store.release_lease(work_id, lease_id)

    async def run_continuous_loop(self, initial_work_id: str, max_continuous_works: int = 5) -> List[DAIOWorkItem]:
        """
        Execute continuous orchestration across multiple authorized work items.
        Automatically claims and processes successive work items when APPROVE authorizes next_phase.
        """
        completed_works: List[DAIOWorkItem] = []
        current_work_id: Optional[str] = initial_work_id
        works_processed = 0

        while current_work_id and works_processed < max_continuous_works:
            works_processed += 1
            logger.info(f"🚀 Continuous Orchestration: Processing work item [{works_processed}/{max_continuous_works}]: {current_work_id}")

            final_work = await self.run_autonomous_loop(current_work_id)
            completed_works.append(final_work)

            # Check if current work completed successfully and authorized a next phase
            if final_work.status == DAIOStatus.COMPLETED and final_work.last_decision == "APPROVE":
                next_phase = final_work.authorized_next_phase
                if next_phase and not is_terminal_phase(next_phase):
                    logger.info(f"NEXT_PHASE_AUTHORIZED: phase={next_phase}, authorized_by_work={final_work.work_id}")
                    next_work = self.resolve_next_work_item(final_work, next_phase)
                    if next_work and next_work.status not in {DAIOStatus.COMPLETED, DAIOStatus.HUMAN_GATE_REQUIRED}:
                        # Atomically claim the next work item
                        worker_id = f"worker-{uuid.uuid4().hex[:6]}"
                        claimed = None
                        if hasattr(self.store, "claim_next_available_work_item"):
                            claimed = self.store.claim_next_available_work_item(worker_id=worker_id, ttl_seconds=300)

                        if claimed and claimed.work_id == next_work.work_id:
                            logger.info(f"ROOT_WORK_CLAIMED: work_id={claimed.work_id}, worker={worker_id}, lease={claimed.lease_id}")
                            # Release the queue lock so run_autonomous_loop can manage its own lease
                            self.store.release_lease(claimed.work_id, claimed.lease_id)
                            current_work_id = claimed.work_id
                            continue
                        elif self.store.acquire_lease(next_work.work_id, worker_id, ttl_seconds=300):
                            logger.info(f"NEXT_WORK_CLAIMED: work_id={next_work.work_id}, worker={worker_id}")
                            self.store.release_lease(next_work.work_id, worker_id)
                            current_work_id = next_work.work_id
                            continue
                        else:
                            logger.warning(f"Could not acquire lease for next work item '{next_work.work_id}'. Ending continuous loop.")
                            break
                    else:
                        logger.info(f"Next work item '{next_work.work_id if next_work else None}' is in terminal state or already completed.")
                        break
                else:
                    logger.info(f"Terminal or empty next_phase '{next_phase}'. Continuous orchestration complete.")
                    break
            else:
                logger.info(f"Work item '{current_work_id}' ended with status '{final_work.status.value}'. Stopping continuous loop.")
                break

        return completed_works

    async def process_incoming_architect_decision(
        self,
        work_id: str,
        decision: ArchitectDecision,
        send_ack: bool = True,
    ) -> Tuple[bool, Optional[DAIOWorkItem], Dict[str, Any]]:
        """
        Durable Decision-Watch Processor:
        Ingests, validates, persists, routes, and acknowledges an incoming ArchitectDecision.
        Dispatches DECISION_ACKNOWLEDGED event to the Lead Architect conversation.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        work = self.store.load_work_item(work_id)
        if not work:
            err_report = {
                "event": "ARCHITECT_DECISION_NOT_APPLIED",
                "work_id": work_id,
                "reason": f"Work item '{work_id}' not found in durable store",
                "decision": decision.decision,
                "human_action_required": True,
            }
            logger.error(f"❌ ARCHITECT_DECISION_NOT_APPLIED: {err_report}")
            return False, None, err_report

        decision_hash = hashlib.sha256(f"{work_id}:{decision.decision}:{decision.current_phase}:{decision.instruction}:{now}".encode()).hexdigest()[:12]

        try:
            # 1. Route work item state
            work = DAIORoleRouter.process_architect_review(work, decision, DAIORole.LEAD_ARCHITECT_REVIEW)

            # 2. Persist turn history & work state
            turn_id = f"turn-{uuid.uuid4().hex[:8]}"
            if hasattr(self.store, "record_turn_history"):
                self.store.record_turn_history(
                    turn_id=turn_id,
                    work_id=work.work_id,
                    role=DAIORole.LEAD_ARCHITECT_REVIEW.value,
                    action_summary=decision.instruction or decision.decision,
                    commit_sha=work.head_sha or "INITIAL",
                    status=decision.decision,
                    payload={
                        "decision": decision.decision,
                        "current_phase": decision.current_phase,
                        "next_phase": decision.next_phase,
                        "action": decision.action,
                        "human_approval_required": decision.human_approval_required,
                        "instruction": decision.instruction,
                        "decision_hash": decision_hash,
                    }
                )
            self.store.save_work_item(work)

            # 3. Build & Dispatch DECISION_ACKNOWLEDGED event
            ack_event = {
                "event": "DECISION_ACKNOWLEDGED",
                "work_id": work.work_id,
                "decision": decision.decision,
                "action": decision.action,
                "decision_hash": decision_hash,
                "received_at": now,
                "resulting_durable_status": work.status.value,
                "human_action_required": (work.status == DAIOStatus.HUMAN_GATE_REQUIRED),
            }

            if send_ack and self.bridge and hasattr(self.bridge, "transmit_review_request"):
                ack_markdown = f"""🏓 **[DAIO DECISION_ACKNOWLEDGED]**

- **Work ID:** `{work.work_id}`
- **Decision Ingested:** `{decision.decision}` (Action: `{decision.action}`)
- **Decision Hash:** `{decision_hash}`
- **Resulting Durable Status:** `{work.status.value}`
- **Human Action Required:** `{work.status == DAIOStatus.HUMAN_GATE_REQUIRED}`

```json
{json.dumps(ack_event, indent=2)}
```
"""
                try:
                    await self.bridge.transmit_review_request(work, ack_markdown)
                except Exception as b_ex:
                    logger.warning(f"Could not transmit DECISION_ACKNOWLEDGED via bridge: {b_ex}")

            logger.info(f"✅ DECISION_ACKNOWLEDGED: work_id={work.work_id}, decision={decision.decision}, hash={decision_hash}, resulting_status={work.status.value}")
            return True, work, ack_event

        except Exception as ex:
            err_report = {
                "event": "ARCHITECT_DECISION_NOT_APPLIED",
                "work_id": work.work_id,
                "reason": str(ex),
                "decision": decision.decision,
                "failed_transition": f"Attempting to apply {decision.decision} on {work.status.value}",
                "human_action_required": True,
            }
            logger.error(f"❌ ARCHITECT_DECISION_NOT_APPLIED: {err_report}")
            return False, work, err_report

