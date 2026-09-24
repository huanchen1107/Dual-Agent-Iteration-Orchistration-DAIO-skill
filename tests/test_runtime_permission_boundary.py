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
