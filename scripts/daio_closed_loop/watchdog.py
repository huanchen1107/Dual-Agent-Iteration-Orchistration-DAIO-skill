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
        parent = self.store.load_work_item(watch.parent_work_id)
        successor = self.store.load_work_item(watch.successor_work_id) if watch.successor_work_id else None

        # If successor_work_id was not bound, try to locate it by parent
        if not successor:
            all_items = self.store.list_work_items()
            for it in all_items:
                if it.parent_work_id == watch.parent_work_id or it.change_id == watch.expected_next_phase:
                    successor = it
                    watch.successor_work_id = it.work_id
                    break

        # 1. State: Successor Completed
        if successor and successor.status == DAIOStatus.COMPLETED:
            watch.current_state = HandoffState.COMPLETED
            watch.last_progress_at = now_iso
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "COMPLETED", "state": watch.current_state.value}

        # Check for expired lease on any active work item
        if successor and successor.lease_id and successor.lease_expires_at and successor.lease_expires_at < now_iso:
            return self._handle_stall(watch, "LEASE_EXPIRED", now_dt)

        # 2. State: Successor Executing
        if successor and successor.status == DAIOStatus.IN_PROGRESS and successor.lease_id:
            watch.current_state = HandoffState.EXECUTING
            watch.last_progress_at = successor.updated_at
            # Check progress deadline
            if watch.progress_deadline and now_iso > watch.progress_deadline:
                return self._handle_stall(watch, "PROGRESS_DEADLINE_EXCEEDED", now_dt)
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value}

        # 3. State: Successor Claimed (awaiting execution / review)
        if successor and successor.claimed_by and successor.lease_id:
            watch.current_state = HandoffState.CLAIMED
            watch.last_progress_at = successor.updated_at
            if watch.first_heartbeat_deadline and now_iso > watch.first_heartbeat_deadline:
                return self._handle_stall(watch, "FIRST_HEARTBEAT_DEADLINE_EXCEEDED", now_dt)
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value}

        # 4. State: Successor Created, Waiting for Claim
        if successor and successor.status in {DAIOStatus.QUEUED, DAIOStatus.AWAITING_REVIEW, DAIOStatus.IN_PROGRESS}:
            watch.current_state = HandoffState.WAITING_FOR_CLAIM
            if watch.claim_deadline and now_iso > watch.claim_deadline:
                return self._handle_stall(watch, "CLAIM_DEADLINE_EXCEEDED", now_dt)
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value}

        # 5. State: Successor Not Yet Materialized
        if not successor:
            watch.current_state = HandoffState.SUCCESSOR_EXPECTED
            if watch.discovery_deadline and now_iso > watch.discovery_deadline:
                return self._handle_stall(watch, "DISCOVERY_DEADLINE_EXCEEDED", now_dt)
            self.store.save_handoff_watch(watch)
            return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value}

        return {"watch_id": watch.watch_id, "status": "OK", "state": watch.current_state.value}

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

        # Action 2: Release expired or orphaned lease
        if diagnostics.get("successor_found"):
            successor = self.store.load_work_item(watch.successor_work_id)
            if successor and successor.lease_id:
                # Force release lease so the queue can claim it again
                self.store.release_lease(successor.work_id, successor.lease_id)
                successor.lease_id = None
                successor.lease_expires_at = None
                successor.claimed_by = None
                self.store.save_work_item(successor)
                watch.current_state = HandoffState.WAITING_FOR_CLAIM
                recovered = True
                logger.info(f"✅ RECOVERY_ACTION_SUCCESS: Released stale lease on {successor.work_id} to re-enable queue claiming")

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
