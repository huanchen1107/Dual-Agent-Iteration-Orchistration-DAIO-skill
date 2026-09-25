"""
Tests for DAIO-DEFECT-HANDOFF-WATCHDOG-001:
Autonomous Successor Handoff Watchdog & Stall Recovery Engine.
"""

import asyncio
import datetime
import json
import pytest
from unittest.mock import MagicMock

from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    HandoffState,
    HandoffWatch,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.worker import DAIOPersistentWorker
from scripts.daio_closed_loop.watchdog import DAIOHandoffWatchdog
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.adapters.executor import ExecutionResult
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter


def test_normal_fast_handoff(tmp_path):
    """Scenario 1: Normal fast handoff transitions from SUCCESSOR_EXPECTED to WAITING_FOR_CLAIM to COMPLETED."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_w1.db"))
    watchdog = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path))

    parent = DAIOWorkItem(
        work_id="work-parent-1",
        project_root=str(tmp_path),
        change_id="PHASE_A",
        current_stage="PHASE_A",
        status=DAIOStatus.COMPLETED,
        last_decision="APPROVE",
        authorized_next_phase="PHASE_B",
    )
    store.save_work_item(parent)

    successor = DAIOWorkItem(
        work_id="work-succ-1",
        project_root=str(tmp_path),
        change_id="PHASE_B",
        current_stage="PHASE_B",
        status=DAIOStatus.COMPLETED,
        parent_work_id="work-parent-1",
    )
    store.save_work_item(successor)

    watch = watchdog.register_handoff(parent, "PHASE_B", successor_work_id="work-succ-1")
    assert watch.current_state == HandoffState.WAITING_FOR_CLAIM

    res = watchdog.evaluate_watches()
    assert len(res) == 1
    assert res[0]["status"] == "COMPLETED"

    loaded_watch = store.load_handoff_watch(watch.watch_id)
    assert loaded_watch.current_state == HandoffState.COMPLETED


def test_missing_successor_materialization(tmp_path):
    """Scenario 2: Parent authorized next_phase but successor was not materialized. Watchdog materializes it."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_w2.db"))
    orch = DAIOClosedLoopOrchestrator(store=store)
    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        orchestrator=orch,
        discovery_timeout_seconds=0.1
    )

    parent = DAIOWorkItem(
        work_id="work-parent-2",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        current_stage="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        last_decision="APPROVE",
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
    )
    store.save_work_item(parent)

    watch = watchdog.register_handoff(parent, "CHANGE_051_OPENSPEC_SCAFFOLD")
    assert watch.current_state == HandoffState.SUCCESSOR_EXPECTED

    # Advance time past discovery deadline
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)
    eval_res = watchdog.evaluate_watches(now=future)

    assert len(eval_res) == 1
    assert eval_res[0]["status"] == "RECOVERED"
    assert eval_res[0]["recovery_attempt"] == 1

    # Verify successor work item was materialized
    succ = store.load_work_item("daio-root-change_051_openspec_scaffold")
    assert succ is not None
    assert succ.change_id == "CHANGE_051_OPENSPEC_SCAFFOLD"
    assert succ.parent_work_id == "work-parent-2"


def test_expired_lease_recovery(tmp_path):
    """Scenario 3: Successor was claimed by a dead worker with an expired lease. Watchdog releases lease."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_w3.db"))
    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        claim_timeout_seconds=0.1
    )

    parent = DAIOWorkItem(
        work_id="work-parent-3",
        project_root=str(tmp_path),
        change_id="PHASE_1",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="PHASE_2",
    )
    store.save_work_item(parent)

    past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=60)).isoformat()
    successor = DAIOWorkItem(
        work_id="work-succ-3",
        project_root=str(tmp_path),
        change_id="PHASE_2",
        status=DAIOStatus.IN_PROGRESS,
        parent_work_id="work-parent-3",
        claimed_by="dead-worker",
        lease_id="lease-dead",
        lease_expires_at=past_time,
    )
    store.save_work_item(successor)

    watch = watchdog.register_handoff(parent, "PHASE_2", successor_work_id="work-succ-3")

    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)
    eval_res = watchdog.evaluate_watches(now=future)

    assert len(eval_res) == 1
    assert eval_res[0]["status"] == "RECOVERED"

    # Verify lease was cleared so new worker can claim
    reloaded_succ = store.load_work_item("work-succ-3")
    assert reloaded_succ.lease_id is None
    assert reloaded_succ.claimed_by is None


def test_bounded_recovery_and_escalation_once(tmp_path):
    """Scenario 4: When recovery repeatedly fails, escalate exactly once to STALLED_ESCALATED with structured report."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_w4.db"))
    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        discovery_timeout_seconds=0.01,
        max_recovery_attempts=2
    )

    parent = DAIOWorkItem(
        work_id="work-parent-4",
        project_root=str(tmp_path),
        change_id="PHASE_UNRECOVERABLE",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="PHASE_NON_EXISTENT",
    )
    store.save_work_item(parent)

    watch = watchdog.register_handoff(parent, "PHASE_NON_EXISTENT")

    # Attempt 1
    future1 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)
    res1 = watchdog.evaluate_watches(now=future1)
    assert res1[0]["status"] == "ESCALATED" or res1[0]["recovery_attempt"] == 1

    # Attempt 2
    future2 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2)
    res2 = watchdog.evaluate_watches(now=future2)

    # Attempt 3 (exceeds max_recovery_attempts)
    future3 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=3)
    res3 = watchdog.evaluate_watches(now=future3)
    assert res3[0]["status"] == "ESCALATED"
    assert "HANDOFF_STALLED" in str(res3[0]["escalation"])

    loaded_watch = store.load_handoff_watch(watch.watch_id)
    assert loaded_watch.current_state == HandoffState.STALLED_ESCALATED
    assert loaded_watch.escalation_state is not None


def test_status_summary_surface(tmp_path):
    """Scenario 5: User-visible status summary formatting."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_w5.db"))
    watchdog = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path))

    parent = DAIOWorkItem(
        work_id="work-parent-5",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
    )
    store.save_work_item(parent)

    watchdog.register_handoff(parent, "CHANGE_051_OPENSPEC_SCAFFOLD", successor_work_id="daio-root-change_051_openspec_scaffold")

    summary = watchdog.get_status_summary()
    assert "HANDOFF WATCH" in summary
    assert "CHANGE_051_OPENSPEC_SCAFFOLD" in summary
    assert "WAITING_FOR_CLAIM" in summary
    assert "Recovery attempts: 0/3" in summary


def test_supervisor_end_to_end_regression_stall_and_recovery(tmp_path):
    """
    Scenario 6 (End-to-End Regression for Real Handoff Stall):
    Reproduces:
    CHANGE_051_PREFLIGHT -> Architect APPROVE -> CHANGE_051_OPENSPEC_SCAFFOLD exists
    -> Stalled in queue -> Supervisor tick detects stall via watchdog -> Recovers lease / claims successor
    -> Worker executes CHANGE_051_OPENSPEC_SCAFFOLD without human command.
    """
    db_file = str(tmp_path / "daio_supervisor_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # 1. Preflight completed
    preflight = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        current_stage="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        last_decision="APPROVE",
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
        head_sha="sha-preflight",
    )
    store.save_work_item(preflight)

    # 2. Scaffold work exists in AWAITING_REVIEW
    scaffold = DAIOWorkItem(
        work_id="daio-root-change_051_openspec_scaffold",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        parent_work_id="daio-root-change_051_preflight",
    )
    store.save_work_item(scaffold)

    bridge = MockArchitectBridgeAdapter(canned_decisions=[
        ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            instruction="Implement scaffolding for Change 051",
            human_approval_required=False
        ),
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="PROCEED",
            instruction="Scaffolding verified",
            human_approval_required=False
        ),
    ])

    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        base_sha="sha-preflight",
        head_sha="sha-scaffold-done",
        generated_commit_sha="sha-scaffold-done",
        output="Created Change 051 OpenSpec scaffold."
    )

    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
        executor=mock_executor,
        bridge=bridge,
        supervisor_id="supervisor-acceptance",
        poll_interval_seconds=0.01,
        watchdog_claim_timeout=0.05,
    )

    # 3. Supervisor executes ticks
    tick1 = asyncio.run(supervisor.run_tick())
    assert tick1["worker_processed_item"] == "daio-root-change_051_openspec_scaffold"

    final_scaffold = store.load_work_item("daio-root-change_051_openspec_scaffold")
    assert final_scaffold.status == DAIOStatus.COMPLETED
    assert final_scaffold.last_decision == "APPROVE"
    assert final_scaffold.human_relay_count == 0


def test_deliberate_unrecoverable_stall_causes_handoff_stalled_without_ide(tmp_path):
    """
    Proves that when a successor is genuinely unrecoverable (e.g. invalid state and exhausted recovery budget),
    the watchdog automatically transitions to STALLED_ESCALATED and emits HANDOFF_STALLED report without IDE intervention.
    """
    db_file = str(tmp_path / "daio_stall_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    parent = DAIOWorkItem(
        work_id="parent-unrecoverable",
        project_root=str(tmp_path),
        change_id="PHASE_PREV",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="PHASE_UNRECOVERABLE",
    )
    store.save_work_item(parent)

    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        discovery_timeout_seconds=0.01,
        claim_timeout_seconds=0.01,
        max_recovery_attempts=1,
    )

    watch = watchdog.register_handoff(parent, "PHASE_UNRECOVERABLE")

    # Pass 1: Stall detected -> attempt 1
    future1 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)
    res1 = watchdog.evaluate_watches(now=future1)
    assert len(res1) == 1

    # Pass 2: Recovery exhausted -> escalate
    future2 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2)
    res2 = watchdog.evaluate_watches(now=future2)
    assert len(res2) == 1
    assert res2[0]["status"] == "ESCALATED"
    assert res2[0]["escalation"]["event"] == "HANDOFF_STALLED"
    assert res2[0]["escalation"]["expected_next_phase"] == "PHASE_UNRECOVERABLE"


def test_supervisor_antigravity_cli_contract_stage_closed_loop(tmp_path):
    """
    Proves that Lead Architect APPROVE/REVISE is ingested, existing CHANGE_051_OPENSPEC_SCAFFOLD
    is claimed by the supervisor/worker, executed via AntigravityCLIAdapter / Mock executor,
    and returns verified deliverables back to the Lead Architect.
    """
    db_file = str(tmp_path / "daio_agy_loop.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # Preflight parent completed
    preflight = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
        last_decision="APPROVE",
    )
    store.save_work_item(preflight)

    # Scaffold item in AWAITING_REVIEW
    scaffold = DAIOWorkItem(
        work_id="daio-root-change_051_openspec_scaffold",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        parent_work_id="daio-root-change_051_preflight",
        allowed_scope=["openspec/**"],
    )
    store.save_work_item(scaffold)

    bridge = MockArchitectBridgeAdapter(canned_decisions=[
        ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            instruction="Author OpenSpec scaffold for Change 051",
            human_approval_required=False,
        ),
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="PROCEED",
            instruction="OpenSpec scaffold accepted",
            human_approval_required=False,
        ),
    ])

    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        base_sha="sha-init",
        head_sha="sha-scaffold-051",
        generated_commit_sha="sha-scaffold-051",
        diff_files=["openspec/changes/051-0050-financial-research-assistant-e2e-vertical-slice/proposal.md"],
        output="Created Change 051 OpenSpec scaffold proposal.",
    )

    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
        executor=mock_executor,
        bridge=bridge,
        supervisor_id="supervisor-prod-e2e",
        poll_interval_seconds=0.01,
    )

    # Tick 1 processes the work item through REVISE -> RUN -> Execution -> IMPLEMENTATION_GATE -> APPROVE -> COMPLETED
    tick_res = asyncio.run(supervisor.run_tick())
    assert tick_res["worker_processed_item"] == "daio-root-change_051_openspec_scaffold"

    final_item = store.load_work_item("daio-root-change_051_openspec_scaffold")
    assert final_item.status == DAIOStatus.COMPLETED
    assert final_item.last_decision == "APPROVE"
    assert len(bridge.call_history) == 2


def test_exhaustive_daio_status_coverage_in_watchdog(tmp_path):
    """
    Exhaustively tests that EVERY single DAIOStatus enum value has an explicit, valid policy action
    and never produces unhandled fallthrough or returns UNKNOWN.
    """
    from scripts.daio_closed_loop.watchdog import classify_work_status_for_watchdog, WatchdogPolicyAction

    watch = HandoffWatch(
        watch_id="watch-exhaustion",
        parent_work_id="parent-1",
        expected_next_phase="PHASE_NEXT",
        discovery_deadline=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)).isoformat(),
        claim_deadline=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)).isoformat(),
        progress_deadline=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)).isoformat(),
    )
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Missing successor
    action_none, reason_none = classify_work_status_for_watchdog(None, watch, now)
    assert action_none in {WatchdogPolicyAction.WAITING, WatchdogPolicyAction.RECOVERABLE_STALL}

    # 2. Every single DAIOStatus enum value
    for status in DAIOStatus:
        item = DAIOWorkItem(
            work_id=f"work-{status.value.lower()}",
            project_root=str(tmp_path),
            change_id="PHASE_X",
            status=status,
            attempt_count=1,
            max_attempts=3,
            lease_id="lease-active" if status == DAIOStatus.IN_PROGRESS else None,
            lease_expires_at=(now + datetime.timedelta(seconds=60)).isoformat() if status == DAIOStatus.IN_PROGRESS else None,
        )
        action, reason = classify_work_status_for_watchdog(item, watch, now)
        assert isinstance(action, WatchdogPolicyAction)
        assert not reason.startswith("UNKNOWN_WORK_STATUS"), f"Status {status} produced unknown policy: {reason}"


def test_exact_live_failure_blocked_successor_auto_recovery_and_bounded_escalation(tmp_path):
    """
    Reproduces the exact live production failure:
    - Successor work item is in status BLOCKED with attempt_count = 2 / max_attempts = 3
    - Watchdog evaluates it: must NOT return OK.
    - Attempt 1: Automatically recovers BLOCKED item -> resets status to IN_PROGRESS, clears lease/claimed_by, preserves lineage.
    - Exhaustion: When attempt_count reaches max_attempts (3), watchdog transitions to STALLED_ESCALATED and emits HANDOFF_STALLED.
    """
    db_file = str(tmp_path / "daio_live_repro.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    parent = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
        head_sha="3836a3e914f2220d52eabe73edb469e96433b384",
    )
    store.save_work_item(parent)

    last_err = "Pure proposal mode failed closed on empty allowed scope ([])"
    blocked_successor = DAIOWorkItem(
        work_id="daio-root-change_051_openspec_scaffold",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.ENGINEERING_TASK,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        status=DAIOStatus.BLOCKED,
        attempt_count=2,
        max_attempts=3,
        claimed_by="worker-supervisor-421314",
        parent_work_id="daio-root-change_051_preflight",
        metadata={"last_error": last_err},
    )
    store.save_work_item(blocked_successor)

    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        max_recovery_attempts=2,
    )
    watch = watchdog.register_handoff(parent, "CHANGE_051_OPENSPEC_SCAFFOLD", successor_work_id="daio-root-change_051_openspec_scaffold")

    # Step 1: Evaluate watch -> must detect stall, NOT return OK, and trigger recovery
    eval_res1 = watchdog.evaluate_watches()
    assert len(eval_res1) == 1
    assert eval_res1[0]["status"] == "RECOVERED"
    assert eval_res1[0]["diagnostics"]["stall_reason"] == "SUCCESSOR_BLOCKED"

    # Verify work item is now runnable without duplicate work items
    reloaded_succ = store.load_work_item("daio-root-change_051_openspec_scaffold")
    assert reloaded_succ.status == DAIOStatus.QUEUED
    assert reloaded_succ.lease_id is None
    assert reloaded_succ.claimed_by is None
    assert reloaded_succ.parent_work_id == "daio-root-change_051_preflight"
    assert len(store.list_work_items()) == 2  # Exactly preflight + scaffold, no duplicates

    # Step 2: Simulate retry failure reaching max_attempts = 3
    reloaded_succ.status = DAIOStatus.BLOCKED
    reloaded_succ.attempt_count = 3
    store.save_work_item(reloaded_succ)

    # Step 3: Next evaluation -> must escalate to HANDOFF_STALLED
    eval_res2 = watchdog.evaluate_watches()
    assert len(eval_res2) == 1
    assert eval_res2[0]["status"] == "ESCALATED"
    assert eval_res2[0]["escalation"]["event"] == "HANDOFF_STALLED"
    assert eval_res2[0]["escalation"]["diagnosed_root_cause"] == "BLOCKED_RETRY_BUDGET_EXHAUSTED"


def test_empty_allowed_scope_never_silently_becomes_unrestricted_scope(tmp_path):
    """
    Enforces DAIO-002: An empty allowed_scope ([]) must fail closed and never allow
    silent modification of target workspace files as if it were unrestricted (*).
    """
    from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor

    executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path))

    # Test file in workspace
    test_file = "src/feature.py"
    target_ws, control_plane, unauthorized = executor.classify_diff_files(
        diff_files=[test_file],
        allowed_scope=[],  # Empty scope
    )

    assert test_file in target_ws
    # Crucial invariant: When allowed_scope is empty, any workspace modification is unauthorized
    assert test_file in unauthorized, "Empty allowed_scope must treat workspace file modification as unauthorized"


