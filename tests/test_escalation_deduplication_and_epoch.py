"""
Regression Tests for Escalation Deduplication, Monotonic Recovery Epochs,
Terminal STALLED_ESCALATED Quiescence, and HUMAN_GATE Semantics.
"""

import asyncio
import datetime
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, AsyncMock

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
from scripts.daio_closed_loop.watchdog import DAIOHandoffWatchdog, WatchdogPolicyAction
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter


def test_stalled_escalated_survives_repeated_supervisor_ticks_without_retransmission(tmp_path):
    """
    Invariant 1: Once a watch reaches STALLED_ESCALATED, register_handoff() on subsequent
    supervisor ticks MUST NOT reactivate it or reset its counter.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_quiescent.db"))
    parent = DAIOWorkItem(
        work_id="parent-q1",
        project_root=str(tmp_path),
        change_id="P1",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="P2",
        head_sha="sha1",
    )
    store.save_work_item(parent)

    succ = DAIOWorkItem(
        work_id="succ-q1",
        project_root=str(tmp_path),
        change_id="P2",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        parent_work_id="parent-q1",
        attempt_count=3,
        max_attempts=3,
    )
    store.save_work_item(succ)

    mock_bridge = MagicMock()
    mock_bridge.transmit_review_request = AsyncMock()

    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        bridge=mock_bridge,
        max_recovery_attempts=2,
    )

    watch = watchdog.register_handoff(parent, "P2", successor_work_id="succ-q1")
    watch.recovery_attempt_count = 2
    store.save_handoff_watch(watch)

    # First evaluation: triggers escalation to STALLED_ESCALATED
    eval1 = watchdog.evaluate_watches()
    assert len(eval1) == 1
    assert eval1[0]["status"] == "ESCALATED"

    reloaded = store.load_handoff_watch(watch.watch_id)
    assert reloaded.current_state == HandoffState.STALLED_ESCALATED
    assert reloaded.recovery_attempt_count == 2

    # Simulate 10 subsequent supervisor ticks calling register_handoff()
    for _ in range(10):
        tick_watch = watchdog.register_handoff(parent, "P2", successor_work_id="succ-q1")
        assert tick_watch.current_state == HandoffState.STALLED_ESCALATED
        assert tick_watch.recovery_attempt_count == 2

    # Verify evaluate_watches() on quiescent state does not re-evaluate or re-emit
    eval_subsequent = watchdog.evaluate_watches()
    assert len(eval_subsequent) == 0  # Ignored by list_active_handoff_watches()


def test_supervisor_restart_does_not_retransmit_unchanged_escalation(tmp_path):
    """
    Invariant 5 & 6: Restarting the supervisor must durably suppress unchanged escalations.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_restart_esc.db"))
    parent = DAIOWorkItem(
        work_id="parent-r1",
        project_root=str(tmp_path),
        change_id="P1",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="P2",
        head_sha="sha1",
    )
    store.save_work_item(parent)

    succ = DAIOWorkItem(
        work_id="succ-r1",
        project_root=str(tmp_path),
        change_id="P2",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        parent_work_id="parent-r1",
        attempt_count=3,
        max_attempts=3,
    )
    store.save_work_item(succ)

    mock_bridge1 = MagicMock()
    mock_bridge1.transmit_review_request = AsyncMock()

    watchdog1 = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path), bridge=mock_bridge1)
    watch = watchdog1.register_handoff(parent, "P2", successor_work_id="succ-r1")
    watchdog1.evaluate_watches()

    # Verify escalation hash was recorded durably
    reloaded_watch = store.load_handoff_watch(watch.watch_id)
    esc_state = json.loads(reloaded_watch.escalation_state)
    esc_hash = esc_state["escalation_hash"]
    assert store.is_escalation_emitted(esc_hash) is True

    # Simulate supervisor process death and new supervisor instance start
    mock_bridge2 = MagicMock()
    mock_bridge2.transmit_review_request = AsyncMock()
    watchdog2 = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path), bridge=mock_bridge2)

    # Calling escalate_stall directly on the same unchanged watch returns suppressed report
    diag = watchdog2.diagnose_stall(reloaded_watch)
    diag["stall_reason"] = "HUMAN_GATE_REQUIRED"
    report2 = watchdog2.escalate_stall(reloaded_watch, diag)
    assert report2["escalation_hash"] == esc_hash
    # Bridge should not have been called on watchdog2
    mock_bridge2.transmit_review_request.assert_not_called()


def test_recovery_attempt_count_never_decreases_within_epoch(tmp_path):
    """
    Invariant 3: recovery_attempt_count is strictly monotonic within one recovery epoch.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_monotonic.db"))
    parent = DAIOWorkItem(
        work_id="parent-m1",
        project_root=str(tmp_path),
        change_id="P1",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="P2",
        head_sha="sha1",
    )
    store.save_work_item(parent)

    succ = DAIOWorkItem(
        work_id="succ-m1",
        project_root=str(tmp_path),
        change_id="P2",
        status=DAIOStatus.BLOCKED,
        parent_work_id="parent-m1",
        attempt_count=1,
        max_attempts=3,
    )
    store.save_work_item(succ)

    watchdog = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path), max_recovery_attempts=3)
    watch = watchdog.register_handoff(parent, "P2", successor_work_id="succ-m1")

    # Attempt 1
    eval1 = watchdog.evaluate_watches()
    assert eval1[0]["status"] == "RECOVERED"
    assert eval1[0]["recovery_attempt"] == 1
    w1 = store.load_handoff_watch(watch.watch_id)
    assert w1.recovery_attempt_count == 1

    # Simulate successor failing again
    succ.status = DAIOStatus.BLOCKED
    succ.attempt_count = 2
    store.save_work_item(succ)

    # Attempt 2
    eval2 = watchdog.evaluate_watches()
    assert eval2[0]["status"] == "RECOVERED"
    assert eval2[0]["recovery_attempt"] == 2
    w2 = store.load_handoff_watch(watch.watch_id)
    assert w2.recovery_attempt_count == 2
    assert w2.recovery_attempt_count > w1.recovery_attempt_count  # Monotonic increase!


def test_explicit_architect_decision_creates_new_recovery_epoch(tmp_path):
    """
    Invariant 4: Ingesting an explicit Architect decision (REVISE/RUN) establishes a new recovery epoch,
    clears quiescent STALLED_ESCALATED state, and resets the attempt counter with epoch metadata.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_epoch.db"))
    parent = DAIOWorkItem(
        work_id="parent-e1",
        project_root=str(tmp_path),
        change_id="P1",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="P2",
        head_sha="sha1",
    )
    store.save_work_item(parent)

    succ = DAIOWorkItem(
        work_id="succ-e1",
        project_root=str(tmp_path),
        change_id="P2",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        parent_work_id="parent-e1",
        attempt_count=3,
        max_attempts=3,
    )
    store.save_work_item(succ)

    mock_bridge = MagicMock()
    mock_bridge.transmit_review_request = AsyncMock()
    mock_bridge.emit_telemetry = AsyncMock()

    orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=mock_bridge)
    watchdog = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path), bridge=mock_bridge)

    watch = watchdog.register_handoff(parent, "P2", successor_work_id="succ-e1")
    watchdog.evaluate_watches()

    w_escalated = store.load_handoff_watch(watch.watch_id)
    assert w_escalated.current_state == HandoffState.STALLED_ESCALATED
    initial_epoch = w_escalated.recovery_epoch_id

    # Ingest explicit Architect REVISE decision
    dec = ArchitectDecision(
        decision="REVISE",
        current_phase="P2",
        action="RUN",
        instruction="Updated scope and retry authorized",
        human_approval_required=False
    )
    ok, updated_work, payload = asyncio.run(orchestrator.process_incoming_architect_decision(succ.work_id, dec))
    assert ok is True
    assert updated_work.status == DAIOStatus.QUEUED

    # Verify watch was reactivated into a new epoch
    w_reactivated = store.load_handoff_watch(watch.watch_id)
    assert w_reactivated.current_state == HandoffState.WAITING_FOR_CLAIM
    assert w_reactivated.recovery_epoch_id != initial_epoch
    assert w_reactivated.recovery_attempt_count == 0
    assert len(w_reactivated.metadata.get("epochs", [])) >= 1
    assert w_reactivated.metadata["epochs"][-1]["predecessor_epoch_id"] == initial_epoch


def test_human_gate_required_semantics_and_review_request(tmp_path):
    """
    Invariant 7: If status is HUMAN_GATE_REQUIRED:
    - human_action_required MUST be True
    - required_human_role is explicit ("HUMAN_PROJECT_OWNER")
    - event is "HUMAN_REVIEW_REQUEST"
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_human_gate.db"))
    parent = DAIOWorkItem(
        work_id="parent-hg",
        project_root=str(tmp_path),
        change_id="P1",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="P2",
        head_sha="sha1",
    )
    store.save_work_item(parent)

    succ = DAIOWorkItem(
        work_id="succ-hg",
        project_root=str(tmp_path),
        change_id="P2",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        parent_work_id="parent-hg",
        attempt_count=3,
        max_attempts=3,
        human_gate_reason="Security policy violation on protected branch",
    )
    store.save_work_item(succ)

    watchdog = DAIOHandoffWatchdog(store=store, project_root=str(tmp_path))
    watch = watchdog.register_handoff(parent, "P2", successor_work_id="succ-hg")

    diag = watchdog.diagnose_stall(watch)
    report = watchdog.escalate_stall(watch, diag)

    assert report["event"] == "HUMAN_REVIEW_REQUEST"
    assert report["human_action_required"] is True
    assert report["required_human_role"] == "HUMAN_PROJECT_OWNER"
    assert "Review blocked work item" in report["required_action"]
    assert report["diagnostics"]["successor_status"] == "HUMAN_GATE_REQUIRED"
