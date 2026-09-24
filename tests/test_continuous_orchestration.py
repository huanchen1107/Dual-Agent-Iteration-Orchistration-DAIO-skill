"""
Tests for Phase S5.5 — Autonomous Next-Work Claim / Continuous Orchestration.
Verifies:
1. APPROVE with valid next_phase -> next work automatically created, claimed, and executed.
2. Restart between APPROVE and claim (recovery of pending transition).
3. Idempotency: repeated processing does not duplicate work items.
4. HUMAN_REVIEW / Human Gate does not continue.
5. STOP does not continue.
6. Unresolved / invalid / terminal next_phase fails closed (stops gracefully without inventing work).
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    TERMINAL_PHASES,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.router import DAIORoleRouter
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.adapters.executor import ExecutionResult
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter


def test_approve_triggers_automatic_next_work_claim(tmp_path):
    """Scenario 1: APPROVE with next_phase causes automatic creation, claim, and execution of Work B."""
    db_file = str(tmp_path / "daio_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # Bridge provides decisions for Work A (REVISE -> APPROVE with next_phase=PHASE_B) and Work B (APPROVE with STOP)
    decisions = [
        ArchitectDecision(decision="REVISE", current_phase="PHASE_A", instruction="Implement Part A"),
        ArchitectDecision(decision="APPROVE", current_phase="PHASE_A", next_phase="PHASE_B", instruction="Approved Part A"),
        ArchitectDecision(decision="REVISE", current_phase="PHASE_B", instruction="Implement Part B"),
        ArchitectDecision(decision="APPROVE", current_phase="PHASE_B", next_phase="STAGE_5_COMPLETE", instruction="Approved Part B"),
    ]
    bridge = MockArchitectBridgeAdapter(canned_decisions=decisions)

    # Mock executor that advances SHA on each execution
    sha_counter = 0
    def fake_execute_task(*args, **kwargs):
        nonlocal sha_counter
        sha_counter += 1
        return ExecutionResult(
            success=True,
            test_passed=True,
            generated_commit_sha=f"commit-sha-{sha_counter}",
            diff_files=["src/part.py"]
        )

    mock_executor = MagicMock()
    mock_executor.execute_task.side_effect = fake_execute_task

    orchestrator = DAIOClosedLoopOrchestrator(
        store=store,
        executor=mock_executor,
        bridge=bridge,
        max_rounds=10
    )

    work_a = orchestrator.create_work_item(
        change_id="PHASE_A",
        project_root=str(tmp_path),
        initial_action="Start Work A",
        allowed_scope=["src/*"]
    )

    completed_works = asyncio.run(orchestrator.run_continuous_loop(initial_work_id=work_a.work_id))

    assert len(completed_works) == 2
    assert completed_works[0].work_id == work_a.work_id
    assert completed_works[0].status == DAIOStatus.COMPLETED
    assert completed_works[0].authorized_next_phase == "PHASE_B"

    work_b = completed_works[1]
    assert work_b.parent_work_id == work_a.work_id
    assert work_b.current_stage == "PHASE_B"
    assert work_b.status == DAIOStatus.COMPLETED
    assert work_b.authorized_next_phase == "STAGE_5_COMPLETE"


def test_restart_recovery_between_approve_and_claim(tmp_path):
    """Scenario 2: Worker dies after APPROVE is persisted. Next start recovers and claims the pending transition."""
    db_file = str(tmp_path / "daio_recovery_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # Work A was approved with next_phase=PHASE_RECOVERY, but process died before Work B ran
    work_a = DAIOWorkItem(
        work_id="daio-work-a-completed",
        project_root=str(tmp_path),
        change_id="PHASE_A",
        current_stage="PHASE_A",
        current_gate=DAIOGate.IMPLEMENTATION_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.COMPLETED,
        last_decision="APPROVE",
        authorized_next_phase="PHASE_RECOVERY",
        head_sha="sha-a-done",
        allowed_scope=["src/*"]
    )
    store.save_work_item(work_a)

    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        generated_commit_sha="sha-b-done",
        diff_files=["src/recovery.py"]
    )
    bridge = MockArchitectBridgeAdapter(canned_decisions=[
        ArchitectDecision(decision="APPROVE", current_phase="PHASE_RECOVERY", next_phase="STAGE_5_COMPLETE", instruction="Done")
    ])

    orchestrator = DAIOClosedLoopOrchestrator(
        store=store,
        executor=mock_executor,
        bridge=bridge
    )

    # Resolve next work item (recovery)
    recovered_work = orchestrator.resolve_next_work_item(work_a, "PHASE_RECOVERY")
    assert recovered_work is not None
    assert recovered_work.parent_work_id == work_a.work_id
    assert recovered_work.change_id == "PHASE_RECOVERY"

    # Run loop on recovered work
    completed_works = asyncio.run(orchestrator.run_continuous_loop(initial_work_id=recovered_work.work_id))
    assert len(completed_works) == 1
    assert completed_works[0].status == DAIOStatus.COMPLETED


def test_idempotency_no_duplicate_work_items(tmp_path):
    """Scenario 3: Repeated resolution or processing does not create duplicate work items in store."""
    db_file = str(tmp_path / "daio_idempotency_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    orchestrator = DAIOClosedLoopOrchestrator(store=store)
    parent_work = DAIOWorkItem(
        work_id="daio-parent-item",
        project_root=str(tmp_path),
        change_id="PHASE_PARENT",
        status=DAIOStatus.COMPLETED,
        allowed_scope=["src/*"]
    )
    store.save_work_item(parent_work)

    # Call resolve_next_work_item multiple times
    res1 = orchestrator.resolve_next_work_item(parent_work, "PHASE_CHILD")
    res2 = orchestrator.resolve_next_work_item(parent_work, "PHASE_CHILD")
    res3 = orchestrator.resolve_next_work_item(parent_work, "PHASE_CHILD")

    assert res1.work_id == res2.work_id == res3.work_id
    all_items = store.list_all_work_items()
    child_items = [it for it in all_items if it.parent_work_id == parent_work.work_id]
    assert len(child_items) == 1


def test_human_review_does_not_continue(tmp_path):
    """Scenario 4: Architect decision HUMAN_REVIEW routes to Human Gate and halts continuous loop."""
    db_file = str(tmp_path / "daio_human_gate_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    decisions = [
        ArchitectDecision(
            decision="HUMAN_REVIEW",
            current_phase="PHASE_A",
            human_approval_required=True,
            instruction="Escalate to Human Project Owner"
        )
    ]
    bridge = MockArchitectBridgeAdapter(canned_decisions=decisions)
    orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=bridge)

    work_a = orchestrator.create_work_item(
        change_id="PHASE_A",
        project_root=str(tmp_path),
        initial_action="Work A",
    )

    completed_works = asyncio.run(orchestrator.run_continuous_loop(initial_work_id=work_a.work_id))

    assert len(completed_works) == 1
    assert completed_works[0].status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert completed_works[0].current_gate == DAIOGate.HUMAN_GATE
    assert completed_works[0].assigned_role == DAIORole.HUMAN_PROJECT_OWNER


def test_stop_decision_does_not_continue(tmp_path):
    """Scenario 5: Architect decision STOP halts continuous loop and does not claim new work."""
    db_file = str(tmp_path / "daio_stop_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    decisions = [
        ArchitectDecision(
            decision="STOP",
            current_phase="PHASE_A",
            next_phase="STOP",
            instruction="Abort execution"
        )
    ]
    bridge = MockArchitectBridgeAdapter(canned_decisions=decisions)
    orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=bridge)

    work_a = orchestrator.create_work_item(
        change_id="PHASE_A",
        project_root=str(tmp_path),
        initial_action="Work A",
    )

    completed_works = asyncio.run(orchestrator.run_continuous_loop(initial_work_id=work_a.work_id))

    assert len(completed_works) == 1
    assert completed_works[0].status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_unresolved_or_terminal_next_phase_fails_closed(tmp_path):
    """Scenario 6: Terminal next_phase (STAGE_5_COMPLETE, NONE, null, empty) does not create spurious work."""
    db_file = str(tmp_path / "daio_terminal_test.db")
    store = SqliteDAIOWorkStore(db_path=db_file)
    orchestrator = DAIOClosedLoopOrchestrator(store=store)

    parent_work = DAIOWorkItem(
        work_id="daio-parent-test",
        project_root=str(tmp_path),
        change_id="PHASE_DONE",
        status=DAIOStatus.COMPLETED
    )
    store.save_work_item(parent_work)

    for term_phase in ["STAGE_5_COMPLETE", "STAGE_COMPLETE", "STOP", "COMPLETE", "TERMINAL", "NONE", "", None]:
        res = orchestrator.resolve_next_work_item(parent_work, term_phase)
        assert res is None, f"Expected None for terminal phase '{term_phase}' but got {res}"
