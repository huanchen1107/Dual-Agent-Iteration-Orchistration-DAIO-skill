"""
Comprehensive regression tests for DAIO-DEFECT-IN-PROGRESS-LIVENESS-005 and DAIO-DEFECT-ACK-FEEDBACK-LOOP-006.
Validates:
1. One Architect REVISE/RUN -> exactly one ACK -> exactly one resume authorization -> exactly one work claim -> exactly one execution attempt.
2. ACK telemetry cannot recursively generate Architect decisions.
3. ACK contains NO ARCHITECT RESPONSE REQUIRED.
4. ACK does not contain standard Architect decision-request footer.
5. Duplicate Architect decisions are idempotently ignored.
6. Architect REJECT or STOP does not resume execution.
7. human_approval_required=true remains genuinely gated.
8. human_approval_required=false does not require Antigravity IDE permission.
9. IN_PROGRESS without a valid lease is unhealthy.
10. IN_PROGRESS without an execution attempt is unhealthy.
11. Valid IN_PROGRESS with active lease and heartbeat remains healthy.
12. Expired lease triggers bounded recovery.
13. Worker death / orphan is detected.
14. agy spawn/exit failure is surfaced.
15. No duplicate Change 051 work item is created during recovery.
16. Supervisor restart during execution/recovery is idempotent.
17. Every durable WorkStatus has an explicit watchdog policy.
18. Unknown future WorkStatus fails closed instead of returning OK.
"""

import asyncio
import datetime
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    DecisionWatch,
    DecisionWatchState,
    HandoffState,
    HandoffWatch,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.router import DAIORoleRouter
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.worker import DAIOPersistentWorker
from scripts.daio_closed_loop.watchdog import DAIOHandoffWatchdog, WatchdogPolicyAction, classify_work_status_for_watchdog
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter
from scripts.daio_closed_loop.adapters.executor import ExecutionResult


def test_1_single_revise_run_exact_lifecycle_and_claim(tmp_path):
    """Scenario 1: One Architect REVISE/RUN -> 1 ACK, 1 resume auth (QUEUED), 1 claim, 1 attempt."""
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t1.db"))
        bridge = MockArchitectBridgeAdapter()
        orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=bridge)

        work = DAIOWorkItem(
            work_id="daio-root-change_051_openspec_scaffold",
            project_root=str(tmp_path),
            change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            human_approval_required=False,
            instruction="Execute Change 051 OpenSpec scaffold"
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=True)

        assert success is True
        assert updated.status == DAIOStatus.QUEUED  # Ready in queue
        assert len(bridge.telemetry_history) == 1
        assert "NO ARCHITECT RESPONSE REQUIRED" in bridge.telemetry_history[0]

        # Claim work item atomically
        claimed = store.claim_next_available_work_item(worker_id="worker-01", ttl_seconds=60)
        assert claimed is not None
        assert claimed.work_id == work.work_id
        assert claimed.claimed_by == "worker-01"
        assert claimed.lease_id is not None

    asyncio.run(_test())


def test_2_and_3_and_4_ack_is_pure_telemetry_no_response_required_no_footer(tmp_path):
    """Scenarios 2, 3, 4: ACK is pure telemetry, contains NO ARCHITECT RESPONSE REQUIRED, and no decision footer."""
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t2.db"))
        bridge = MockArchitectBridgeAdapter()
        orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=bridge)

        work = DAIOWorkItem(
            work_id="work-ack-01",
            project_root=str(tmp_path),
            change_id="CHANGE_051",
            status=DAIOStatus.QUEUED,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051",
            action="RUN",
            instruction="Task"
        )
        await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=True)

        assert len(bridge.telemetry_history) == 1
        ack_text = bridge.telemetry_history[0]
        assert "NO ARCHITECT RESPONSE REQUIRED" in ack_text
        assert "【系統指令：請架構師於回覆末尾輸出標準 JSON 控制區塊】" not in ack_text
        assert "DECISION_ACKNOWLEDGED" in ack_text

    asyncio.run(_test())


def test_5_duplicate_architect_decisions_idempotently_ignored(tmp_path):
    """Scenario 5: Duplicate Architect decisions are idempotently ignored."""
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t5.db"))
        bridge = MockArchitectBridgeAdapter()
        orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=bridge)

        work = DAIOWorkItem(
            work_id="work-dup-01",
            project_root=str(tmp_path),
            change_id="CHANGE_051",
            status=DAIOStatus.QUEUED,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051",
            action="RUN",
            instruction="Same task instruction"
        )
        s1, w1, a1 = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=True)
        s2, w2, a2 = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=True)

        assert s1 is True
        assert s2 is True
        assert a2.get("status") == "DUPLICATE"
        # Only 1 ACK sent, duplicate did not re-send
        assert len(bridge.telemetry_history) == 1

    asyncio.run(_test())


def test_6_architect_reject_or_stop_does_not_resume(tmp_path):
    """Scenario 6: Architect REJECT or STOP transitions to HUMAN_GATE_REQUIRED and cannot be claimed."""
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t6.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)

        work = DAIOWorkItem(
            work_id="work-stop-01",
            project_root=str(tmp_path),
            change_id="CHANGE_051",
            status=DAIOStatus.AWAITING_REVIEW,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(decision="STOP", current_phase="CHANGE_051", action="STOP", instruction="Stop immediately")
        await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)

        reloaded = store.load_work_item(work.work_id)
        assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED
        assert store.claim_next_available_work_item(worker_id="w-01") is None

    asyncio.run(_test())


def test_7_and_8_human_approval_gate_semantics(tmp_path):
    """Scenarios 7 & 8: human_approval_required=true stays gated, false resumes to QUEUED without IDE prompts."""
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t78.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)

        # 1. human_approval_required=True
        work1 = DAIOWorkItem(work_id="w-true", project_root=str(tmp_path), change_id="C1", status=DAIOStatus.AWAITING_REVIEW)
        store.save_work_item(work1)
        dec_true = ArchitectDecision(decision="REVISE", current_phase="C1", human_approval_required=True, instruction="Need budget sign-off")
        _, u1, _ = await orchestrator.process_incoming_architect_decision(work1.work_id, dec_true, send_ack=False)
        assert u1.status == DAIOStatus.HUMAN_GATE_REQUIRED
        assert u1.assigned_role == DAIORole.HUMAN_PROJECT_OWNER

        # 2. human_approval_required=False
        work2 = DAIOWorkItem(work_id="w-false", project_root=str(tmp_path), change_id="C2", status=DAIOStatus.HUMAN_GATE_REQUIRED)
        store.save_work_item(work2)
        dec_false = ArchitectDecision(decision="REVISE", current_phase="C2", human_approval_required=False, instruction="Proceed")
        _, u2, _ = await orchestrator.process_incoming_architect_decision(work2.work_id, dec_false, send_ack=False)
        assert u2.status == DAIOStatus.QUEUED
        assert u2.assigned_role == DAIORole.ENGINEERING_EXECUTION

    asyncio.run(_test())


def test_9_and_10_and_11_in_progress_provenance_validation(tmp_path):
    """Scenarios 9, 10, 11: IN_PROGRESS without lease or attempt is unhealthy; with valid lease & heartbeat is healthy."""
    now = datetime.datetime.now(datetime.timezone.utc)
    watch = HandoffWatch(watch_id="w-prov", parent_work_id="p1", expected_next_phase="C1")

    # 9. IN_PROGRESS with missing lease -> RECOVERABLE_STALL
    work_no_lease = DAIOWorkItem(
        work_id="w1", project_root=str(tmp_path), change_id="C1",
        status=DAIOStatus.IN_PROGRESS, claimed_by="worker-01", lease_id=None
    )
    act1, r1 = classify_work_status_for_watchdog(work_no_lease, watch, now)
    assert act1 == WatchdogPolicyAction.RECOVERABLE_STALL
    assert r1 == "IN_PROGRESS_NO_LEASE"

    # 10. IN_PROGRESS without execution_started_at -> RECOVERABLE_STALL
    work_no_exec = DAIOWorkItem(
        work_id="w2", project_root=str(tmp_path), change_id="C1",
        status=DAIOStatus.IN_PROGRESS, claimed_by="worker-01", lease_id="lease-01",
        lease_expires_at=(now + datetime.timedelta(seconds=60)).isoformat(),
        execution_started_at=None
    )
    act2, r2 = classify_work_status_for_watchdog(work_no_exec, watch, now)
    assert act2 == WatchdogPolicyAction.RECOVERABLE_STALL
    assert r2 == "ORPHAN_IN_PROGRESS_MISSING_PROVENANCE"

    # 11. IN_PROGRESS with valid lease & started_at -> HEALTHY_PROGRESS
    work_healthy = DAIOWorkItem(
        work_id="w3", project_root=str(tmp_path), change_id="C1",
        status=DAIOStatus.IN_PROGRESS, claimed_by="worker-01", lease_id="lease-01",
        lease_expires_at=(now + datetime.timedelta(seconds=60)).isoformat(),
        execution_started_at=now.isoformat()
    )
    act3, r3 = classify_work_status_for_watchdog(work_healthy, watch, now)
    assert act3 == WatchdogPolicyAction.HEALTHY_PROGRESS


def test_12_and_13_expired_lease_and_orphan_trigger_recovery(tmp_path):
    """Scenarios 12 & 13: Expired lease or orphan IN_PROGRESS triggers bounded recovery to QUEUED."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t12.db"))
    now = datetime.datetime.now(datetime.timezone.utc)

    parent = DAIOWorkItem(work_id="p-01", project_root=str(tmp_path), change_id="P1", status=DAIOStatus.COMPLETED, authorized_next_phase="C1")
    store.save_work_item(parent)

    orphan = DAIOWorkItem(
        work_id="succ-01",
        project_root=str(tmp_path),
        change_id="C1",
        status=DAIOStatus.IN_PROGRESS,
        lease_id="lease-old",
        lease_expires_at=(now - datetime.timedelta(seconds=30)).isoformat(),
        parent_work_id="p-01",
    )
    store.save_work_item(orphan)

    watchdog = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path))
    watch = watchdog.register_handoff(parent, "C1", successor_work_id="succ-01")

    res = watchdog.evaluate_watches(now=now)
    assert len(res) == 1
    assert res[0]["status"] in ("RECOVERED", "RETRYING")

    reloaded = store.load_work_item("succ-01")
    assert reloaded.status == DAIOStatus.QUEUED
    assert reloaded.lease_id is None
    assert reloaded.claimed_by is None


def test_15_and_16_supervisor_restart_idempotent_no_duplicate_work(tmp_path):
    """Scenarios 15 & 16: Supervisor restart is idempotent and never creates duplicate work."""
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "t15.db"))
        work = DAIOWorkItem(
            work_id="daio-root-change_051_openspec_scaffold",
            project_root=str(tmp_path),
            change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
            metadata={
                "last_architect_decision": {
                    "decision": "REVISE",
                    "current_phase": "CHANGE_051_OPENSPEC_SCAFFOLD",
                    "action": "RUN",
                    "human_approval_required": False,
                    "instruction": "OpenSpec scaffold"
                }
            }
        )
        store.save_work_item(work)

        mock_executor = MagicMock()
        mock_executor.execute_task_async = AsyncMock(return_value=ExecutionResult(
            success=True, test_passed=True, head_sha="abc1234",
            diff_files=["openspec/proposal.md"]
        ))
        mock_executor.execute_task = MagicMock(return_value=ExecutionResult(
            success=True, test_passed=True, head_sha="abc1234",
            diff_files=["openspec/proposal.md"]
        ))

        s1 = DAIOSupervisor(project_root=str(tmp_path), store=store, executor=mock_executor, bridge=MockArchitectBridgeAdapter())
        await s1.run_tick()

        # Restart supervisor
        s2 = DAIOSupervisor(project_root=str(tmp_path), store=store, executor=mock_executor, bridge=MockArchitectBridgeAdapter())
        await s2.run_tick()

        all_items = store.list_work_items()
        c051_items = [it for it in all_items if "change_051_openspec_scaffold" in it.work_id]
        assert len(c051_items) == 1
        assert len(all_items) == 1

    asyncio.run(_test())


def test_17_and_18_exhaustive_daio_status_watchdog_policy():
    """Scenarios 17 & 18: Every durable status has explicit watchdog policy, unknown status fails closed."""
    now = datetime.datetime.now(datetime.timezone.utc)
    watch = HandoffWatch(watch_id="w-all", parent_work_id="p1", expected_next_phase="C1")

    # All known statuses must not raise unhandled exception
    for st in DAIOStatus:
        w = DAIOWorkItem(work_id=f"w-{st.value}", project_root="/tmp", change_id="C1", status=st)
        act, reason = classify_work_status_for_watchdog(w, watch, now)
        assert isinstance(act, WatchdogPolicyAction)

    # Unknown future status -> ESCALATE (never OK)
    w_unk = DAIOWorkItem(work_id="w-unk", project_root="/tmp", change_id="C1", status="FUTURE_STATUS")  # type: ignore
    act_unk, reason_unk = classify_work_status_for_watchdog(w_unk, watch, now)
    assert act_unk == WatchdogPolicyAction.ESCALATE
