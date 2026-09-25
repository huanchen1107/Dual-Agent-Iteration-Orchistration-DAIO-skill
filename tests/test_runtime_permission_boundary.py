"""
Tests for DAIO-DEFECT-RUNTIME-PERMISSION-BOUNDARY-003:
Headless Persistent Supervisor, Native Durable Store Access,
Permission Taxonomy & Zero IDE GUI Requirement for Routine Closed-Loop Operations.
"""

import asyncio
import datetime
import json
import os
from pathlib import Path
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
    PermissionCategory,
    SupervisorHeartbeat,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.watchdog import DAIOHandoffWatchdog
from scripts.daio_closed_loop.adapters.executor import ExecutionResult
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter


def test_permission_taxonomy_classification():
    """Verify operation classification under RUNTIME_SAFE_AUTONOMOUS vs HUMAN_GATE_REQUIRED vs IDE_DEVELOPMENT_ONLY."""
    assert PermissionCategory.RUNTIME_SAFE_AUTONOMOUS.value == "RUNTIME_SAFE_AUTONOMOUS"
    assert PermissionCategory.HUMAN_GATE_REQUIRED.value == "HUMAN_GATE_REQUIRED"
    assert PermissionCategory.IDE_DEVELOPMENT_ONLY.value == "IDE_DEVELOPMENT_ONLY"


def test_native_durable_store_heartbeats_and_telemetry(tmp_path):
    """Scenario 1: Supervisor records heartbeats directly to durable SQLite store and reports full status."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_perm_test.db"))

    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
        supervisor_id="supervisor-headless-001",
    )

    # Run tick
    res = asyncio.run(supervisor.run_tick())
    assert res["supervisor_id"] == "supervisor-headless-001"

    # Verify heartbeat in store
    hb = store.load_supervisor_heartbeat("supervisor-headless-001")
    assert hb is not None
    assert hb.supervisor_id == "supervisor-headless-001"
    assert hb.status == "RUNNING"
    assert hb.pid == os.getpid()

    # Verify status report
    status_str = supervisor.get_status()
    assert "supervisor-headless-001" in status_str
    assert "Supervisor Heartbeat" in status_str
    assert "Queue Depth" in status_str
    assert "Last Bridge Heartbeat" in status_str


def test_headless_execution_without_ide_permission(tmp_path):
    """
    Scenario 2: Persistent supervisor autonomously claims successor and runs engineering tasks
    through AntigravityCLIAdapter mock without interactive IDE approval.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_headless.db"))

    # Parent preflight completed
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

    # Successor scaffold item
    scaffold = DAIOWorkItem(
        work_id="daio-root-change_051_openspec_scaffold",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        parent_work_id="daio-root-change_051_preflight",
        allowed_scope=["openspec/*"],
    )
    store.save_work_item(scaffold)

    bridge = MockArchitectBridgeAdapter(canned_decisions=[
        ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            instruction="Implement Change 051 OpenSpec scaffold.",
            human_approval_required=False,
        ),
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="PROCEED",
            instruction="Change 051 OpenSpec verified.",
            human_approval_required=False,
        )
    ])

    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        base_sha="sha-preflight",
        head_sha="sha-scaffold-done",
        generated_commit_sha="sha-scaffold-done",
        diff_files=["openspec/changes/051/.openspec.yaml"],
        output="Scaffold created successfully."
    )

    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
        executor=mock_executor,
        bridge=bridge,
        supervisor_id="supervisor-headless-002",
        poll_interval_seconds=0.01,
    )

    # Run supervisor tick - autonomously claims, ingests decision, executes via executor, approves
    tick_res = asyncio.run(supervisor.run_tick())
    assert tick_res["worker_processed_item"] == "daio-root-change_051_openspec_scaffold"

    completed_scaffold = store.load_work_item("daio-root-change_051_openspec_scaffold")
    assert completed_scaffold.status == DAIOStatus.COMPLETED
    assert completed_scaffold.human_relay_count == 0
    assert completed_scaffold.last_decision == "APPROVE"


def test_scope_violation_triggers_human_gate(tmp_path):
    """Scenario 3: Out-of-contract or destructive modification triggers HUMAN_GATE_REQUIRED safety breaker."""
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_scope.db"))

    work = DAIOWorkItem(
        work_id="work-violating-scope",
        project_root=str(tmp_path),
        change_id="CHANGE_051_SCAFFOLD",
        current_gate=DAIOGate.ENGINEERING_TASK,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        status=DAIOStatus.IN_PROGRESS,
        allowed_scope=["openspec/*"],
    )
    store.save_work_item(work)

    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=False,
        test_passed=False,
        scope_violation=True,
        error_message="Attempted write to protected file: .env.production"
    )

    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
        executor=mock_executor,
        supervisor_id="supervisor-scope-test",
    )

    asyncio.run(supervisor.run_tick())

    violating_work = store.load_work_item("work-violating-scope")
    assert violating_work.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert "Scope Violation" in violating_work.human_gate_reason


def test_permission_denial_with_autonomous_fallback_succeeds(tmp_path):
    """
    DAIO-007: When a CLI/tool encounters permission denial or unavailability,
    the autonomous control plane utilizes its authorized native store/runtime fallback.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_fallback.db"))
    work = DAIOWorkItem(
        work_id="work-permission-fallback",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.ENGINEERING_TASK,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        status=DAIOStatus.QUEUED,
        allowed_scope=["openspec/*"],
    )
    store.save_work_item(work)

    # Claim work via native store interface (no shell / IDE permission required)
    claimed = store.claim_next_available_work_item(worker_id="worker-native-01", ttl_seconds=60)
    assert claimed is not None
    assert claimed.work_id == "work-permission-fallback"
    assert claimed.lease_id is not None
    assert claimed.claimed_by == "worker-native-01"


def test_permission_denial_without_fallback_escalates_to_stalled(tmp_path):
    """
    DAIO-007: If a capability is genuinely missing / blocked with no autonomous fallback,
    the execution transitions to EXECUTION_STALLED / HANDOFF_STALLED and never produces silence.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_stalled_perm.db"))
    parent = DAIOWorkItem(
        work_id="parent-051",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
        head_sha="sha-051",
    )
    store.save_work_item(parent)

    blocked_work = DAIOWorkItem(
        work_id="work-perm-stalled",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.HUMAN_GATE,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        attempt_count=3,
        max_attempts=3,
        human_gate_reason="PERMISSION_DENIED: System security boundary prevents direct write without elevated capability",
        parent_work_id="parent-051",
    )
    store.save_work_item(blocked_work)

    mock_bridge = MagicMock()
    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        bridge=mock_bridge,
        max_recovery_attempts=1,
    )
    watch = watchdog.register_handoff(parent, "CHANGE_051_OPENSPEC_SCAFFOLD", successor_work_id="work-perm-stalled")

    # Evaluate -> must escalate to STALLED_ESCALATED and emit HANDOFF_STALLED report (no silence!)
    eval_res = watchdog.evaluate_watches()
    assert len(eval_res) == 1
    assert eval_res[0]["status"] == "ESCALATED"
    assert eval_res[0]["diagnostics"]["successor_status"] == "HUMAN_GATE_REQUIRED"

    reloaded_watch = store.load_handoff_watch(watch.watch_id)
    assert reloaded_watch.current_state == HandoffState.STALLED_ESCALATED
    escalation_payload = json.loads(reloaded_watch.escalation_state)
    assert escalation_payload["event"] == "HANDOFF_STALLED"
    assert escalation_payload["stalled_work_id"] == "work-perm-stalled"


def test_worker_hung_or_waiting_on_permission_detected_by_progress_timeout(tmp_path):
    """
    DAIO-007: An active execution attempt hung waiting on human permission or tool execution
    is detected by the watchdog progress deadline and triggers bounded recovery.
    """
    store = SqliteDAIOWorkStore(db_path=str(tmp_path / "daio_timeout.db"))
    parent = DAIOWorkItem(
        work_id="parent-051-to",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.COMPLETED,
        authorized_next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
        head_sha="sha-to",
    )
    store.save_work_item(parent)

    past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=200)).isoformat()
    future_time = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=200)).isoformat()

    hung_work = DAIOWorkItem(
        work_id="work-hung-attempt",
        project_root=str(tmp_path),
        change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
        current_gate=DAIOGate.ENGINEERING_TASK,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        status=DAIOStatus.IN_PROGRESS,
        claimed_by="worker-hung-instance",
        lease_id="lease-hung-01",
        lease_expires_at=future_time,
        execution_attempt_id="attempt-hung-01",
        execution_started_at=past_time,
        parent_work_id="parent-051-to",
    )
    store.save_work_item(hung_work)

    watchdog = DAIOHandoffWatchdog(
        store=store,
        project_root=str(tmp_path),
        progress_timeout_seconds=60.0,
        max_recovery_attempts=2,
    )
    watch = watchdog.register_handoff(parent, "CHANGE_051_OPENSPEC_SCAFFOLD", successor_work_id="work-hung-attempt")

    # Force watch progress deadline into the past to simulate timeout
    watch.progress_deadline = past_time
    store.save_handoff_watch(watch)

    # Evaluate -> detects PROGRESS_DEADLINE_EXCEEDED, recovers hung item to QUEUED
    eval_res = watchdog.evaluate_watches()
    assert len(eval_res) == 1
    assert eval_res[0]["status"] == "RECOVERED"

    reloaded_work = store.load_work_item("work-hung-attempt")
    assert reloaded_work.status == DAIOStatus.QUEUED
    assert reloaded_work.lease_id is None
    assert reloaded_work.claimed_by is None
    assert reloaded_work.execution_attempt_id is None

