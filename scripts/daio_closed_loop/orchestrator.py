"""
Generic DAIO Autonomous Closed Loop Orchestrator.
Integrates WorkStore, RoleRouter, Adapters, and Safety Breakers.
Follows Fail-Closed Invariants DAIO-001..004.
"""

from __future__ import annotations
import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional
import uuid

from .models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
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
    ) -> DAIOWorkItem:
        work = DAIOWorkItem(
            work_id=f"daio-{uuid.uuid4().hex[:8]}",
            project_root=project_root,
            change_id=change_id,
            current_stage="S3",
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            requested_action=initial_action,
            allowed_scope=allowed_scope or [],
            architect_endpoint=architect_endpoint or {},
            status=DAIOStatus.AWAITING_REVIEW,
        )
        self.store.save_work_item(work)
        return work

    async def run_autonomous_loop(self, work_id: str) -> DAIOWorkItem:
        """
        Execute the autonomous closed loop until COMPLETED, HUMAN_GATE_REQUIRED, or BLOCKED.
        Enforces 0 human relays.
        """
        worker_id = f"worker-{uuid.uuid4().hex[:6]}"
        lease_id = self.store.acquire_lease(work_id, worker_id, ttl_seconds=300)
        if not lease_id:
            raise PermissionError(f"Cannot acquire lease for work item '{work_id}' (already locked).")

        consecutive_errors = 0
        previous_reviewed_sha: Optional[str] = None
        rounds_executed = 0

        try:
            while rounds_executed < self.max_rounds:
                work = self.store.load_work_item(work_id)
                if not work:
                    raise KeyError(f"Work item '{work_id}' not found.")

                if work.status in {DAIOStatus.COMPLETED, DAIOStatus.HUMAN_GATE_REQUIRED, DAIOStatus.BLOCKED}:
                    logger.info(f"Loop terminating with terminal status: {work.status.value}")
                    break

                rounds_executed += 1
                logger.info(f"--- [DAIO Closed Loop Round {rounds_executed}/{self.max_rounds}] Gate: {work.current_gate.value}, Role: {work.assigned_role.value} ---")

                # =========================================================================
                # Branch 1: LEAD_ARCHITECT_REVIEW turn
                # =========================================================================
                if work.assigned_role == DAIORole.LEAD_ARCHITECT_REVIEW:
                    # Invariant DAIO-001: Repeated SHA without code modification check
                    if work.head_sha and work.head_sha == previous_reviewed_sha:
                        work.status = DAIOStatus.HUMAN_GATE_REQUIRED
                        work.human_gate_reason = f"DAIO-001 Zero progress: Repeated review on identical HEAD SHA ({work.head_sha})"
                        self.store.save_work_item(work)
                        break

                    # Format review package
                    report_markdown = f"""# DAIO Review Request — Change {work.change_id} (Round {rounds_executed})
**Work ID:** `{work.work_id}`  
**Current Gate:** `{work.current_gate.value}`  
**Commit SHA:** `{work.head_sha or 'INITIAL'}`  
**Action / Deliverables:** {work.requested_action}  
"""
                    try:
                        decision = await self.bridge.transmit_review_request(work, report_markdown)
                        consecutive_errors = 0
                        previous_reviewed_sha = work.head_sha

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
                        exec_res = self.executor.execute_task(
                            work=work,
                            command=None,
                            test_command=self.default_test_command,
                            commit_message=f"feat(daio): automated execution round {rounds_executed} for {work.change_id}",
                        )

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
