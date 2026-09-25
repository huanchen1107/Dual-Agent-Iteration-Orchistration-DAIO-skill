"""
Autonomous Successor Handoff Watchdog & Stall Recovery Engine for Generic DAIO.
Enforces DAIO-DEFECT-HANDOFF-WATCHDOG-001:
- Autonomous watchdog lifecycle independent of incoming ChatGPT messages.
- Bounded state transitions with explicit deadlines (discovery, claim, first heartbeat, progress).
- Root-cause diagnostics across store, worker, lease, bridge, and backend.
- Safe bounded recovery actions (rescan, lease recovery, successor materialization).
- Single structured escalation report on unrecoverable stall.
- User-visible status formatting.
"""

from __future__ import annotations
import asyncio
import datetime
from enum import Enum
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    HandoffState,
    HandoffWatch,
    is_terminal_phase,
)
from .store import DAIOWorkStore, SqliteDAIOWorkStore

logger = logging.getLogger("DAIO_Handoff_Watchdog")


class WatchdogPolicyAction(str, Enum):
    HEALTHY_PROGRESS = "HEALTHY_PROGRESS"
    WAITING = "WAITING"
    RECOVERABLE_STALL = "RECOVERABLE_STALL"
    TERMINAL_SUCCESS = "TERMINAL_SUCCESS"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    ESCALATE = "ESCALATE"


def classify_work_status_for_watchdog(
    work: Optional[DAIOWorkItem],
    watch: HandoffWatch,
    now: datetime.datetime,
) -> Tuple[WatchdogPolicyAction, str]:
    """
    Exhaustively maps every DAIOWorkItem status to an explicit WatchdogPolicyAction.
    Fails closed to ESCALATE for any unhandled or unknown status.
    """
    now_iso = now.isoformat()

    if work is None:
        if watch.discovery_deadline and now_iso > watch.discovery_deadline:
            return WatchdogPolicyAction.RECOVERABLE_STALL, "DISCOVERY_DEADLINE_EXCEEDED"
        return WatchdogPolicyAction.WAITING, "WAITING_FOR_MATERIALIZATION"

    status = work.status

    if status == DAIOStatus.COMPLETED:
        return WatchdogPolicyAction.TERMINAL_SUCCESS, "COMPLETED"

    elif status == DAIOStatus.HUMAN_GATE_REQUIRED:
        return WatchdogPolicyAction.TERMINAL_FAILURE, "HUMAN_GATE_REQUIRED"

    elif status == DAIOStatus.BLOCKED:
        if work.attempt_count < work.max_attempts and watch.recovery_attempt_count < watch.max_recovery_attempts:
            return WatchdogPolicyAction.RECOVERABLE_STALL, "SUCCESSOR_BLOCKED"
        else:
            return WatchdogPolicyAction.ESCALATE, "BLOCKED_RETRY_BUDGET_EXHAUSTED"

    elif status == DAIOStatus.QUEUED:
        if watch.claim_deadline and now_iso > watch.claim_deadline:
            return WatchdogPolicyAction.RECOVERABLE_STALL, "CLAIM_DEADLINE_EXCEEDED"
        return WatchdogPolicyAction.WAITING, "WAITING_FOR_CLAIM"

    elif status == DAIOStatus.AWAITING_REVIEW:
        if watch.progress_deadline and now_iso > watch.progress_deadline:
            return WatchdogPolicyAction.RECOVERABLE_STALL, "REVIEW_DEADLINE_EXCEEDED"
        return WatchdogPolicyAction.WAITING, "AWAITING_ARCHITECT_REVIEW"

    elif status == DAIOStatus.IN_PROGRESS:
        has_provenance = bool(
            work.claimed_by
            and work.lease_id
            and work.lease_expires_at
            and work.lease_expires_at >= now_iso
            and (work.execution_started_at or work.metadata.get("execution_started_at"))
        )
        if not has_provenance:
            if not work.lease_id:
                return WatchdogPolicyAction.RECOVERABLE_STALL, "IN_PROGRESS_NO_LEASE"
            if work.lease_expires_at and work.lease_expires_at < now_iso:
                return WatchdogPolicyAction.RECOVERABLE_STALL, "LEASE_EXPIRED"
            if not work.claimed_by:
                return WatchdogPolicyAction.RECOVERABLE_STALL, "ORPHAN_IN_PROGRESS_NO_CLAIMANT"
            return WatchdogPolicyAction.RECOVERABLE_STALL, "ORPHAN_IN_PROGRESS_MISSING_PROVENANCE"

        if watch.progress_deadline and now_iso > watch.progress_deadline:
            return WatchdogPolicyAction.RECOVERABLE_STALL, "PROGRESS_DEADLINE_EXCEEDED"
        return WatchdogPolicyAction.HEALTHY_PROGRESS, "EXECUTING_WITH_ACTIVE_LEASE"

    else:
        return WatchdogPolicyAction.ESCALATE, f"UNKNOWN_WORK_STATUS_{status}"


class DAIOHandoffWatchdog:
    """
    Supervisor watchdog that actively monitors authorized work handoffs,
    detects stalls against explicit time budgets, performs bounded automatic recovery,
    and escalates unrecoverable stalls to the Lead Architect.
    """

    def __init__(
        self,
        store: DAIOWorkStore,
        project_root: str,
        orchestrator: Optional[Any] = None,
        bridge: Optional[Any] = None,
        discovery_timeout_seconds: float = 30.0,
        claim_timeout_seconds: float = 45.0,
        first_heartbeat_timeout_seconds: float = 60.0,
        progress_timeout_seconds: float = 120.0,
        max_recovery_attempts: int = 3,
    ) -> None:
        self.store = store
        self.project_root = Path(project_root).resolve()
        self.orchestrator = orchestrator
        self.bridge = bridge
        self.discovery_timeout_seconds = discovery_timeout_seconds
        self.claim_timeout_seconds = claim_timeout_seconds
        self.first_heartbeat_timeout_seconds = first_heartbeat_timeout_seconds
        self.progress_timeout_seconds = progress_timeout_seconds
        self.max_recovery_attempts = max_recovery_attempts

    def register_handoff(
        self,
        parent_work: DAIOWorkItem,
        expected_next_phase: str,
        successor_work_id: Optional[str] = None,
        now: Optional[datetime.datetime] = None,
    ) -> HandoffWatch:
        """
        Idempotently create or update a durable handoff watch record for an authorized transition.
        """
        now_dt = now or datetime.datetime.now(datetime.timezone.utc)
        now_iso = now_dt.isoformat()

        # Check if watch already exists for this parent/phase
        existing = self.store.find_handoff_watch_by_parent(parent_work.work_id)
        if existing and existing.expected_next_phase.strip().upper() == expected_next_phase.strip().upper():
            if successor_work_id and not existing.successor_work_id:
                existing.successor_work_id = successor_work_id
                existing.current_state = HandoffState.WAITING_FOR_CLAIM
                existing.last_progress_at = now_iso
                self.store.save_handoff_watch(existing)

            # If existing watch was escalated or completed, check if successor is still active/recoverable
            succ_item = self.store.load_work_item(existing.successor_work_id) if existing.successor_work_id else None
            if succ_item and succ_item.status != DAIOStatus.COMPLETED and existing.current_state in {HandoffState.STALLED_ESCALATED, HandoffState.COMPLETED}:
                existing.current_state = HandoffState.WAITING_FOR_CLAIM if succ_item.status == DAIOStatus.QUEUED else HandoffState.CLAIMED
                existing.recovery_attempt_count = 0
                existing.last_progress_at = now_iso
                existing.claim_deadline = (now_dt + datetime.timedelta(seconds=self.claim_timeout_seconds)).isoformat()
                existing.discovery_deadline = (now_dt + datetime.timedelta(seconds=self.discovery_timeout_seconds)).isoformat()
                existing.first_heartbeat_deadline = (now_dt + datetime.timedelta(seconds=self.first_heartbeat_timeout_seconds)).isoformat()
                existing.progress_deadline = (now_dt + datetime.timedelta(seconds=self.progress_timeout_seconds)).isoformat()
                self.store.save_handoff_watch(existing)
                logger.info(f"🔄 HANDOFF_WATCH_REACTIVATED: watch_id={existing.watch_id}, successor={succ_item.work_id}, status={succ_item.status.value}")

            return existing

        watch_id = f"watch-{uuid.uuid4().hex[:8]}"
        disc_deadline = (now_dt + datetime.timedelta(seconds=self.discovery_timeout_seconds)).isoformat()
        claim_deadline = (now_dt + datetime.timedelta(seconds=self.claim_timeout_seconds)).isoformat()
        first_hb_deadline = (now_dt + datetime.timedelta(seconds=self.first_heartbeat_timeout_seconds)).isoformat()
        prog_deadline = (now_dt + datetime.timedelta(seconds=self.progress_timeout_seconds)).isoformat()

        initial_state = HandoffState.WAITING_FOR_CLAIM if successor_work_id else HandoffState.SUCCESSOR_EXPECTED

        watch = HandoffWatch(
            watch_id=watch_id,
            parent_work_id=parent_work.work_id,
            successor_work_id=successor_work_id,
            expected_next_phase=expected_next_phase.strip(),
            created_at=now_iso,
            discovery_deadline=disc_deadline,
            claim_deadline=claim_deadline,
            first_heartbeat_deadline=first_hb_deadline,
            progress_deadline=prog_deadline,
            current_state=initial_state,
            last_progress_at=now_iso,
            recovery_attempt_count=0,
            max_recovery_attempts=self.max_recovery_attempts,
            metadata={
                "project_root": str(self.project_root),
                "parent_head_sha": parent_work.head_sha,
                "parent_stage": parent_work.current_stage,
            }
        )
        self.store.save_handoff_watch(watch)
        logger.info(f"👀 HANDOFF_WATCH_REGISTERED: watch_id={watch.watch_id}, parent={parent_work.work_id}, next_phase={expected_next_phase}, state={watch.current_state.value}")
        return watch

    def evaluate_watches(self, now: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        """
        Evaluate all active handoff watches against their deadline budgets.
        Transitions stalled watches to STALLED_DIAGNOSING and triggers bounded recovery/escalation.
        """
        now_dt = now or datetime.datetime.now(datetime.timezone.utc)
        active_watches = self.store.list_active_handoff_watches()
        eval_results: List[Dict[str, Any]] = []

        for watch in active_watches:
            result = self._evaluate_single_watch(watch, now_dt)
            eval_results.append(result)

        return eval_results

    def _evaluate_single_watch(self, watch: HandoffWatch, now_dt: datetime.datetime) -> Dict[str, Any]:
        now_iso = now_dt.isoformat()
        successor = self.store.load_work_item(watch.successor_work_id) if watch.successor_work_id else None

        # If successor_work_id was not bound, try to locate it by parent
        if not successor:
            all_items = self.store.list_work_items()
            for it in all_items:
                if it.parent_work_id == watch.parent_work_id or it.change_id == watch.expected_next_phase:
                    successor = it
                    watch.successor_work_id = it.work_id
                    break

        action, reason = classify_work_status_for_watchdog(successor, watch, now_dt)

        if action == WatchdogPolicyAction.TERMINAL_SUCCESS:
            watch.current_state = HandoffState.COMPLETED
            watch.last_progress_at = now_iso
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "COMPLETED", "state": watch.current_state.value, "policy": action.value}

        elif action == WatchdogPolicyAction.HEALTHY_PROGRESS:
            watch.current_state = HandoffState.EXECUTING
            watch.last_progress_at = successor.updated_at if successor else now_iso
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value, "policy": action.value}

        elif action == WatchdogPolicyAction.WAITING:
            if successor:
                watch.current_state = HandoffState.WAITING_FOR_CLAIM if successor.status == DAIOStatus.QUEUED else HandoffState.CLAIMED
            else:
                watch.current_state = HandoffState.SUCCESSOR_EXPECTED
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value, "policy": action.value}

        elif action == WatchdogPolicyAction.RECOVERABLE_STALL:
            return self._handle_stall(watch, reason, now_dt)

        elif action in {WatchdogPolicyAction.TERMINAL_FAILURE, WatchdogPolicyAction.ESCALATE}:
            diagnostics = self.diagnose_stall(watch)
            diagnostics["stall_reason"] = reason
            escalation_res = self.escalate_stall(watch, diagnostics)
            watch.current_state = HandoffState.STALLED_ESCALATED
            watch.escalation_state = json.dumps(escalation_res)
            self.store.save_handoff_watch(watch)
            return {
                "watch_id": watch.watch_id,
                "status": "ESCALATED",
                "escalation": escalation_res,
                "diagnostics": diagnostics,
                "policy": action.value,
            }

        # Fail closed
        diagnostics = self.diagnose_stall(watch)
        diagnostics["stall_reason"] = f"UNHANDLED_POLICY_{action}"
        escalation_res = self.escalate_stall(watch, diagnostics)
        watch.current_state = HandoffState.STALLED_ESCALATED
        self.store.save_handoff_watch(watch)
        return {"watch_id": watch.watch_id, "status": "ESCALATED", "policy": "FAIL_CLOSED"}

    def _handle_stall(self, watch: HandoffWatch, reason: str, now_dt: datetime.datetime) -> Dict[str, Any]:
        """
        Transition to STALLED_DIAGNOSING, perform root-cause inspection, and attempt bounded recovery.
        """
        now_iso = now_dt.isoformat()
        watch.current_state = HandoffState.STALLED_DIAGNOSING
        self.store.save_handoff_watch(watch)
        logger.warning(f"⚠️ HANDOFF_STALL_DETECTED: watch_id={watch.watch_id}, reason={reason}, phase={watch.expected_next_phase}")

        diagnostics = self.diagnose_stall(watch)
        diagnostics["stall_reason"] = reason

        if watch.recovery_attempt_count < watch.max_recovery_attempts:
            watch.recovery_attempt_count += 1
            recovered = self.attempt_recovery(watch, diagnostics)
            # Reset deadlines with new budget for retry or progress
            watch.last_progress_at = now_iso
            watch.claim_deadline = (now_dt + datetime.timedelta(seconds=self.claim_timeout_seconds)).isoformat()
            watch.discovery_deadline = (now_dt + datetime.timedelta(seconds=self.discovery_timeout_seconds)).isoformat()
            watch.first_heartbeat_deadline = (now_dt + datetime.timedelta(seconds=self.first_heartbeat_timeout_seconds)).isoformat()
            watch.progress_deadline = (now_dt + datetime.timedelta(seconds=self.progress_timeout_seconds)).isoformat()
            self.store.save_handoff_watch(watch)

            if recovered:
                return {
                    "watch_id": watch.watch_id,
                    "status": "RECOVERED",
                    "recovery_attempt": watch.recovery_attempt_count,
                    "diagnostics": diagnostics,
                }
            else:
                return {
                    "watch_id": watch.watch_id,
                    "status": "RETRYING",
                    "recovery_attempt": watch.recovery_attempt_count,
                    "diagnostics": diagnostics,
                }

        # Max recovery attempts exhausted -> escalate
        escalation_res = self.escalate_stall(watch, diagnostics)
        watch.current_state = HandoffState.STALLED_ESCALATED
        watch.escalation_state = json.dumps(escalation_res)
        self.store.save_handoff_watch(watch)
        return {
            "watch_id": watch.watch_id,
            "status": "ESCALATED",
            "escalation": escalation_res,
            "diagnostics": diagnostics,
        }

    def diagnose_stall(self, watch: HandoffWatch) -> Dict[str, Any]:
        """
        Inspect store, successor existence, lease expiry, bridge, and backend health.
        """
        diag: Dict[str, Any] = {
            "watch_id": watch.watch_id,
            "parent_work_id": watch.parent_work_id,
            "expected_next_phase": watch.expected_next_phase,
            "successor_work_id": watch.successor_work_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        # 1. Store connectivity & item checks
        parent = self.store.load_work_item(watch.parent_work_id)
        diag["parent_found"] = parent is not None
        if parent:
            diag["parent_status"] = parent.status.value
            diag["parent_decision"] = parent.last_decision
            diag["parent_authorized_next_phase"] = parent.authorized_next_phase

        successor = self.store.load_work_item(watch.successor_work_id) if watch.successor_work_id else None
        diag["successor_found"] = successor is not None
        if successor:
            diag["successor_status"] = successor.status.value
            diag["successor_gate"] = successor.current_gate.value
            diag["successor_role"] = successor.assigned_role.value
            diag["successor_claimed_by"] = successor.claimed_by
            diag["successor_lease_id"] = successor.lease_id
            diag["successor_lease_expires_at"] = successor.lease_expires_at

        # 2. Queue eligibility check
        if successor:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            is_lease_expired = bool(successor.lease_expires_at and successor.lease_expires_at < now_iso)
            is_eligible = (
                successor.status in {DAIOStatus.QUEUED, DAIOStatus.AWAITING_REVIEW, DAIOStatus.IN_PROGRESS}
                and (successor.lease_id is None or is_lease_expired)
            )
            diag["queue_eligible"] = is_eligible
            diag["lease_expired"] = is_lease_expired

        # 3. Antigravity backend check
        diag["agy_cli_installed"] = Path(os.path.expanduser("~/.local/bin/agy")).exists() or Path("/usr/local/bin/agy").exists()

        # 4. Chrome CDP Bridge check
        if self.bridge:
            diag["bridge_configured"] = True
            diag["bridge_type"] = self.bridge.__class__.__name__
        else:
            diag["bridge_configured"] = False

        return diag

    def attempt_recovery(self, watch: HandoffWatch, diagnostics: Dict[str, Any]) -> bool:
        """
        Execute bounded safe recovery actions:
        - Materialize missing successor
        - Release expired / orphaned leases
        - Reset eligible queue item
        """
        logger.info(f"🔄 ATTEMPTING_HANDOFF_RECOVERY: watch_id={watch.watch_id}, attempt={watch.recovery_attempt_count}")
        recovered = False

        # Action 1: Materialize successor if missing
        if not diagnostics.get("successor_found") and self.orchestrator:
            parent = self.store.load_work_item(watch.parent_work_id)
            if parent and watch.expected_next_phase:
                successor = self.orchestrator.resolve_next_work_item(parent, watch.expected_next_phase)
                if successor:
                    watch.successor_work_id = successor.work_id
                    watch.current_state = HandoffState.WAITING_FOR_CLAIM
                    recovered = True
                    logger.info(f"✅ RECOVERY_ACTION_SUCCESS: Materialized missing successor work item {successor.work_id}")

        # Action 2: Release expired / orphaned lease / orphan IN_PROGRESS / BLOCKED recoverable
        if diagnostics.get("successor_found"):
            successor = self.store.load_work_item(watch.successor_work_id)
            if successor and (successor.lease_id or successor.status in {DAIOStatus.IN_PROGRESS, DAIOStatus.BLOCKED}):
                # Force release lease so the queue can claim it cleanly
                if successor.lease_id:
                    self.store.release_lease(successor.work_id, successor.lease_id)
                successor.lease_id = None
                successor.lease_expires_at = None
                successor.claimed_by = None
                successor.execution_attempt_id = None
                successor.execution_started_at = None
                successor.status = DAIOStatus.QUEUED
                self.store.save_work_item(successor)
                watch.current_state = HandoffState.WAITING_FOR_CLAIM
                recovered = True
                logger.info(f"✅ RECOVERY_ACTION_SUCCESS: Reset work item {successor.work_id} to QUEUED for clean claim")

        # Action 3: Reset BLOCKED status if recovery budget allows
        if diagnostics.get("successor_found") and not recovered:
            successor = self.store.load_work_item(watch.successor_work_id)
            if successor and successor.status == DAIOStatus.BLOCKED and successor.attempt_count < successor.max_attempts:
                successor.status = DAIOStatus.QUEUED
                successor.lease_id = None
                successor.lease_expires_at = None
                successor.claimed_by = None
                successor.execution_attempt_id = None
                successor.execution_started_at = None
                self.store.save_work_item(successor)
                watch.current_state = HandoffState.WAITING_FOR_CLAIM
                recovered = True
                logger.info(f"✅ RECOVERY_ACTION_SUCCESS: Reset BLOCKED status on {successor.work_id} to QUEUED for retry")

        return recovered

    def escalate_stall(self, watch: HandoffWatch, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Emit a structured HANDOFF_STALLED report when all recovery attempts fail.
        """
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        created_dt = datetime.datetime.fromisoformat(watch.created_at)
        elapsed_seconds = int((now_dt - created_dt).total_seconds())

        report = {
            "event": "HANDOFF_STALLED",
            "stalled_work_id": watch.successor_work_id or watch.parent_work_id,
            "parent_work_id": watch.parent_work_id,
            "expected_next_phase": watch.expected_next_phase,
            "elapsed_seconds": elapsed_seconds,
            "diagnosed_root_cause": diagnostics.get("stall_reason", "UNKNOWN_STALL"),
            "recovery_attempts": watch.recovery_attempt_count,
            "diagnostics": diagnostics,
            "human_action_required": False,
        }

        logger.error(f"🚨 HANDOFF_STALLED_ESCALATION: {json.dumps(report, indent=2)}")

        # Transmit to Architect conversation over bridge if available
        if self.bridge and hasattr(self.bridge, "transmit_review_request"):
            try:
                stall_msg = f"""🚨 **[DAIO HANDOFF STALLED ESCALATION]**

- **Stalled Work ID:** `{watch.successor_work_id or watch.parent_work_id}`
- **Expected Next Phase:** `{watch.expected_next_phase}`
- **Elapsed Duration:** `{elapsed_seconds}s`
- **Diagnosed Root Cause:** `{diagnostics.get('stall_reason', 'UNKNOWN_STALL')}`
- **Recovery Attempts:** `{watch.recovery_attempt_count}/{watch.max_recovery_attempts}`

```json
{json.dumps(report, indent=2)}
```
"""
                # Schedule bridge dispatch if in event loop
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                        fake_work = DAIOWorkItem(
                            work_id=watch.successor_work_id or watch.parent_work_id,
                            project_root=str(self.project_root),
                            change_id=watch.expected_next_phase,
                            current_stage=watch.expected_next_phase,
                            current_gate=DAIOGate.HUMAN_GATE,
                            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
                            requested_action="HANDOFF_STALLED ESCALATION",
                            allowed_scope=[],
                        )

                        async def _handle_escalation_reply(bridge: Any, orchestrator: Any, work_item: DAIOWorkItem, stall_text: str, target_id: str) -> None:
                            try:
                                dec = await bridge.transmit_review_request(work_item, stall_text)
                                if dec and orchestrator:
                                    await orchestrator.process_incoming_architect_decision(target_id, dec)
                            except Exception as sub_ex:
                                logger.error(f"Error handling post-escalation architect decision: {sub_ex}")

                        target_id = watch.successor_work_id or watch.parent_work_id
                        loop.create_task(_handle_escalation_reply(self.bridge, self.orchestrator, fake_work, stall_msg, target_id))
                except RuntimeError:
                    pass
            except Exception as ex:
                logger.warning(f"Could not transmit stall escalation via bridge: {ex}")

        return report

    def get_status_summary(self) -> str:
        """
        Format user-visible human-readable status for CLI / UI surfaces.
        """
        active_watches = self.store.list_active_handoff_watches()
        if not active_watches:
            return "HANDOFF WATCH\nNo active handoff watches registered.\n"

        lines = ["HANDOFF WATCH"]
        now_dt = datetime.datetime.now(datetime.timezone.utc)

        for w in active_watches:
            created_dt = datetime.datetime.fromisoformat(w.created_at)
            elapsed_s = int((now_dt - created_dt).total_seconds())
            successor = self.store.load_work_item(w.successor_work_id) if w.successor_work_id else None
            worker_id = successor.claimed_by if successor else "UNASSIGNED"

            lines.append(f"Change: {w.expected_next_phase}")
            lines.append(f"State: {w.current_state.value}")
            lines.append(f"Elapsed: {elapsed_s}s")
            lines.append(f"Worker: {worker_id}")
            lines.append(f"Last progress: {w.last_progress_at}")
            lines.append(f"Recovery attempts: {w.recovery_attempt_count}/{w.max_recovery_attempts}")
            lines.append("-" * 30)

        return "\n".join(lines)
