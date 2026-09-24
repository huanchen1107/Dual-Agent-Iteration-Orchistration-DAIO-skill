"""
Tests for Phase S5.6 — Post-Completion Production Handoff & Durable Queue Acceptance.
Verifies:
1. Terminal-work -> new root production work handoff (e.g. STAGE_5_COMPLETE -> CHANGE_051_PREFLIGHT).
2. Worker restart recovery (pending handoff is not lost across process restarts).
3. Exactly-once claim (atomic transaction claiming).
4. Duplicate worker protection (concurrent workers cannot claim the same work).
5. Missing/invalid/terminal next_phase fails closed.
6. STOP / HUMAN_REVIEW halts handoff.
7. Provenance preservation (new root work preserves parent_work_id, authorization metadata, and commit SHAs).
"""

import asyncio
import os
import pytest
from unittest.mock import MagicMock

from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    is_terminal_phase,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.worker import DAIOPersistentWorker
from scripts.daio_closed_loop.adapters.executor import ExecutionResult
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter


def test_terminal_work_to_new_root_production_handoff(tmp_path):
    """
    Scenario 1: When a stage or work item reaches terminal completion (e.g. STAGE_5_COMPLETE),
    an authorized next_phase (e.g. CHANGE_051_PREFLIGHT) is created as a new root production work item
    and claimed.
    """
    db_file = str(tmp_path / "daio_handoff.db")
    store = SqliteDAIOWorkStore(db_path=db_file)
    orchestrator = DAIOClosedLoopOrchestrator(store=store)

    completed_stage5_work = DAIOWorkItem(
        work_id="daio-stage5-final",
        project_root=str(tmp_path),
        change_id="STAGE_5_ACCEPTANCE",
        current_stage="STAGE_5_COMPLETE",
        status=DAIOStatus.COMPLETED,
        last_decision="APPROVE",
        authorized_next_phase="CHANGE_051_PREFLIGHT",
        head_sha="sha-stage5-pass",
        allowed_scope=["src/*", "tests/*"],
        architect_endpoint={"provider": "CHATGPT_WEB"}
    )
    store.save_work_item(completed_stage5_work)

    # Resolve post-completion handoff
    root_work = orchestrator.resolve_next_work_item(completed_stage5_work, "CHANGE_051_PREFLIGHT")
    assert root_work is not None
    assert root_work.work_id == "daio-root-change_051_preflight"
    assert root_work.change_id == "CHANGE_051_PREFLIGHT"
    assert root_work.current_stage == "CHANGE_051_PREFLIGHT"
    assert root_work.current_gate == DAIOGate.CONTRACT_GATE
    assert root_work.assigned_role == DAIORole.LEAD_ARCHITECT_REVIEW
    assert root_work.parent_work_id == "daio-stage5-final"
    assert root_work.metadata["is_production_root"] is True
    assert root_work.metadata["authorization_source"] == "ARCHITECT_POST_COMPLETION_HANDOFF"
    assert root_work.metadata["derived_from_work_id"] == "daio-stage5-final"
    assert root_work.base_sha == "sha-stage5-pass"


def test_exactly_once_claim_and_duplicate_worker_protection(tmp_path):
    """
    Scenario 2: Concurrent worker claim attempts result in exactly ONE worker successfully acquiring the lease.
    """
    db_file = str(tmp_path / "daio_concurrent.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    work = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        status=DAIOStatus.AWAITING_REVIEW,
        allowed_scope=["src/*"]
    )
    store.save_work_item(work)

    # Worker 1 claims
    claim1 = store.claim_next_available_work_item(worker_id="worker-alpha", ttl_seconds=60)
    assert claim1 is not None
    assert claim1.work_id == "daio-root-change_051_preflight"
    assert claim1.claimed_by == "worker-alpha"

    # Worker 2 attempts to claim while Worker 1's lease is active -> must return None
    claim2 = store.claim_next_available_work_item(worker_id="worker-beta", ttl_seconds=60)
    assert claim2 is None


def test_worker_restart_recovery(tmp_path):
    """
    Scenario 3: If worker restarts after handoff is authorized, the new start recovers and claims
    the pending work item from the durable queue.
    """
    db_file = str(tmp_path / "daio_restart.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # Pending uncompleted work item in durable database
    work = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        current_gate=DAIOGate.CONTRACT_GATE,
        status=DAIOStatus.AWAITING_REVIEW,
        parent_work_id="daio-stage5-final"
    )
    store.save_work_item(work)

    # New worker starts up and claims pending work
    claimed = store.claim_next_available_work_item(worker_id="restarted-worker", ttl_seconds=300)
    assert claimed is not None
    assert claimed.work_id == "daio-root-change_051_preflight"
    assert claimed.parent_work_id == "daio-stage5-final"


def test_missing_or_terminal_next_phase_fails_closed(tmp_path):
    """
    Scenario 4: When next_phase is empty, NONE, STOP, or HUMAN_REVIEW, handoff fails closed without inventing work.
    """
    db_file = str(tmp_path / "daio_term.db")
    store = SqliteDAIOWorkStore(db_path=db_file)
    orchestrator = DAIOClosedLoopOrchestrator(store=store)

    completed_work = DAIOWorkItem(
        work_id="daio-completed-1",
        project_root=str(tmp_path),
        change_id="TEST",
        status=DAIOStatus.COMPLETED
    )
    store.save_work_item(completed_work)

    for term in ["STOP", "HUMAN_REVIEW", "HUMAN_GATE", "NONE", "NULL", "", None]:
        res = orchestrator.resolve_next_work_item(completed_work, term)
        assert res is None


def test_provenance_preservation(tmp_path):
    """
    Scenario 5: Handoff preserves full provenance linking root production work item to authorizing stage.
    """
    db_file = str(tmp_path / "daio_provenance.db")
    store = SqliteDAIOWorkStore(db_path=db_file)
    orchestrator = DAIOClosedLoopOrchestrator(store=store)

    parent_work = DAIOWorkItem(
        work_id="daio-s5-acceptance",
        project_root=str(tmp_path),
        change_id="PHASE_S5_ACCEPTANCE",
        current_stage="STAGE_5_COMPLETE",
        status=DAIOStatus.COMPLETED,
        last_decision="APPROVE",
        head_sha="commit-sha-provenance-123",
        allowed_scope=["src/core/*", "tests/core/*"]
    )
    store.save_work_item(parent_work)

    new_work = orchestrator.resolve_next_work_item(parent_work, "CHANGE_051_PREFLIGHT")
    assert new_work is not None
    assert new_work.parent_work_id == "daio-s5-acceptance"
    assert new_work.base_sha == "commit-sha-provenance-123"
    assert new_work.head_sha == "commit-sha-provenance-123"
    assert new_work.allowed_scope == ["src/core/*", "tests/core/*"]
    assert new_work.metadata["authorization_source"] == "ARCHITECT_POST_COMPLETION_HANDOFF"
    assert new_work.metadata["parent_head_sha"] == "commit-sha-provenance-123"


def test_root_work_contract_gate_revise_run_full_execution_callback_and_recovery(tmp_path):
    """
    Scenario 6 (Regression):
    Durable root work -> autonomous claim -> CONTRACT_GATE -> Architect REVISE/RUN
    -> durable transition -> worker resumes/executes -> callback to Architect (IMPLEMENTATION_GATE)
    -> Architect APPROVE -> durable COMPLETED status.
    Verifies duplicate claim protection and restart recovery across turns.
    """
    db_file = str(tmp_path / "daio_full_cycle.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # 1. Setup canned Architect decisions:
    # Turn 1: CONTRACT_GATE -> REVISE / RUN (with arbitrary preflight instruction)
    # Turn 2: IMPLEMENTATION_GATE -> APPROVE (with next_phase=None)
    decisions = [
        ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_PREFLIGHT",
            action="RUN",
            instruction="Perform read-only preflight and verify contracts",
            human_approval_required=False
        ),
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_PREFLIGHT",
            action="PROCEED",
            instruction="Preflight report verified and approved",
            human_approval_required=False
        )
    ]
    bridge = MockArchitectBridgeAdapter(canned_decisions=decisions)

    # 2. Setup mock executor
    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        base_sha="sha-base-051",
        head_sha="sha-base-051",
        generated_commit_sha="sha-base-051",
        output="Preflight check completed successfully. All contracts verified."
    )

    orchestrator = DAIOClosedLoopOrchestrator(
        store=store,
        executor=mock_executor,
        bridge=bridge,
        max_rounds=10
    )

    # 3. Create root production work item
    root_work = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        current_stage="CHANGE_051_PREFLIGHT",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        parent_work_id="daio-stage5-acceptance-final",
        allowed_scope=["src/*", "tests/*"],
        base_sha="sha-base-051",
        head_sha="sha-base-051"
    )
    store.save_work_item(root_work)

    # 4. Verify duplicate claim protection: Worker Alpha claims, Worker Beta gets None
    claim_alpha = store.claim_next_available_work_item(worker_id="worker-alpha", ttl_seconds=300)
    assert claim_alpha is not None
    assert claim_alpha.work_id == "daio-root-change_051_preflight"
    assert claim_alpha.claimed_by == "worker-alpha"

    claim_beta = store.claim_next_available_work_item(worker_id="worker-beta", ttl_seconds=300)
    assert claim_beta is None, "Duplicate worker claimed an active leased item!"

    # 5. Worker Alpha executes the autonomous closed loop
    final_work = asyncio.run(orchestrator.run_autonomous_loop(claim_alpha.work_id))

    # 6. Verify completed state, full state transitions, and evidence callback
    assert final_work.status == DAIOStatus.COMPLETED
    assert final_work.last_decision == "APPROVE"
    assert len(bridge.call_history) == 2, f"Expected 2 turns with Architect (CONTRACT_GATE and IMPLEMENTATION_GATE), got {len(bridge.call_history)}"
    assert "CONTRACT_GATE" in bridge.call_history[0]
    assert "IMPLEMENTATION_GATE" in bridge.call_history[1]
    assert "Preflight check completed successfully" in bridge.call_history[1]

    # 7. Verify process restart recovery: reloading from DB shows terminal COMPLETED
    reloaded = store.load_work_item("daio-root-change_051_preflight")
    assert reloaded is not None
    assert reloaded.status == DAIOStatus.COMPLETED
    assert reloaded.parent_work_id == "daio-stage5-acceptance-final"


def test_worker_kill_restart_between_contract_gate_and_decision_resumes_automatically(tmp_path):
    """
    Scenario 7 (Integration):
    Worker 1 processes CONTRACT_GATE -> Lead Architect returns REVISE / RUN -> decision is persisted.
    Worker 1 is killed / crashes.
    Worker 2 (persistent daemon) starts up, autonomously discovers the existing uncompleted work item,
    claims it exactly once without creating a duplicate item, executes the engineering turn,
    transmits the callback to the Lead Architect at IMPLEMENTATION_GATE, and completes.
    """
    from scripts.daio_closed_loop.worker import DAIOPersistentWorker
    from scripts.daio_closed_loop.router import DAIORoleRouter

    db_file = str(tmp_path / "daio_restart_cycle.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # 1. Create durable root work item at CONTRACT_GATE
    root_work = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        current_stage="CHANGE_051_PREFLIGHT",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        parent_work_id="daio-stage5-final",
        allowed_scope=["src/*", "tests/*"],
        base_sha="sha-init",
        head_sha="sha-init"
    )
    store.save_work_item(root_work)

    # 2. Worker 1 claims and transmits CONTRACT_GATE
    claim1 = store.claim_next_available_work_item(worker_id="worker-1-instance", ttl_seconds=300)
    assert claim1 is not None
    assert claim1.work_id == "daio-root-change_051_preflight"

    # Simulate Architect returning REVISE / RUN at CONTRACT_GATE
    decision1 = ArchitectDecision(
        decision="REVISE",
        current_phase="CHANGE_051_PREFLIGHT",
        action="RUN",
        instruction="Perform read-only preflight analysis",
        human_approval_required=False
    )
    routed_work = DAIORoleRouter.process_architect_review(claim1, decision1, DAIORole.LEAD_ARCHITECT_REVIEW)
    store.save_work_item(routed_work)

    # 3. Simulate Worker 1 CRASH / KILL:
    # Release or expire lease to simulate process death
    store.release_lease(routed_work.work_id, routed_work.lease_id)

    # Verify state in database is IN_PROGRESS at ENGINEERING_TASK
    persisted = store.load_work_item("daio-root-change_051_preflight")
    assert persisted.status == DAIOStatus.IN_PROGRESS
    assert persisted.current_gate == DAIOGate.ENGINEERING_TASK
    assert persisted.assigned_role == DAIORole.ENGINEERING_EXECUTION

    # 4. Worker 2 starts up (new process / daemon instance)
    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        base_sha="sha-init",
        head_sha="sha-init",
        generated_commit_sha="sha-init",
        output="Preflight analysis complete: all governance rules checked."
    )

    # Lead Architect returns APPROVE at IMPLEMENTATION_GATE
    bridge2 = MockArchitectBridgeAdapter(canned_decisions=[
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_PREFLIGHT",
            action="PROCEED",
            instruction="Preflight analysis verified and approved",
            human_approval_required=False
        )
    ])

    worker2 = DAIOPersistentWorker(
        project_root=str(tmp_path),
        store=store,
        executor=mock_executor,
        bridge=bridge2,
        worker_id="worker-2-daemon",
        poll_interval_seconds=0.1
    )

    # 5. Worker 2 executes one iteration of the persistent loop
    completed_item = asyncio.run(worker2.run_once())

    # 6. Verify assertions
    assert completed_item is not None
    assert completed_item.work_id == "daio-root-change_051_preflight"
    assert completed_item.status == DAIOStatus.COMPLETED
    assert completed_item.last_decision == "APPROVE"

    # Verify that NO duplicate work items were created in the store
    all_items = store.list_all_work_items()
    assert len(all_items) == 1, f"Expected exactly 1 work item in database, but found {len(all_items)}: {[it.work_id for it in all_items]}"

    # Verify that the callback to Architect included the preflight execution report
    assert len(bridge2.call_history) == 1
    assert "IMPLEMENTATION_GATE" in bridge2.call_history[0]
    assert "Preflight analysis complete" in bridge2.call_history[0]


def test_autonomous_continuation_on_approve_with_next_phase(tmp_path):
    """
    Scenario 8 (Regression test for DAIO-DEFECT-AUTONOMOUS-CONTINUATION-002):
    Reproduces:
    CHANGE_051_PREFLIGHT -> Architect APPROVE (next_phase='CHANGE_051_OPENSPEC_SCAFFOLD', action='RUN')
    -> Successor work item daio-root-change_051_openspec_scaffold is created exactly once
    -> Persistent worker autonomously claims and begins CHANGE_051_OPENSPEC_SCAFFOLD without human intervention.
    """
    db_file = str(tmp_path / "daio_continuation.db")
    store = SqliteDAIOWorkStore(db_path=db_file)

    # 1. Initial preflight root work item
    preflight_work = DAIOWorkItem(
        work_id="daio-root-change_051_preflight",
        project_root=str(tmp_path),
        change_id="CHANGE_051_PREFLIGHT",
        current_stage="CHANGE_051_PREFLIGHT",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        requested_action="Perform canonical preflight audit",
        status=DAIOStatus.AWAITING_REVIEW,
        architect_endpoint={"provider": "CHATGPT_WEB", "conversation_id": "test-conv-051"},
        allowed_scope=["openspec/*"],
    )
    store.save_work_item(preflight_work)

    # 2. Canned decisions:
    # Turn 1: Architect APPROVE on preflight with next_phase=CHANGE_051_OPENSPEC_SCAFFOLD
    # Turn 2: Architect REVISE/RUN on scaffold CONTRACT_GATE
    # Turn 3: Architect APPROVE on scaffold IMPLEMENTATION_GATE
    bridge = MockArchitectBridgeAdapter(canned_decisions=[
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_PREFLIGHT",
            next_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            human_approval_required=False,
            instruction="Preflight verified. Proceed to OpenSpec scaffolding."
        ),
        ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            next_phase=None,
            action="RUN",
            human_approval_required=False,
            instruction="Create proposal.md, design.md, and tasks.md for Change 051."
        ),
        ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            next_phase=None,
            action="PROCEED",
            human_approval_required=False,
            instruction="OpenSpec scaffolding verified."
        ),
    ])

    mock_executor = MagicMock()
    mock_executor.execute_task.return_value = ExecutionResult(
        success=True,
        test_passed=True,
        base_sha="sha-init",
        head_sha="sha-scaffold-pass",
        generated_commit_sha="sha-scaffold-pass",
        output="Created openspec/changes/051-0050-financial-research-assistant-e2e-vertical-slice scaffold."
    )

    worker = DAIOPersistentWorker(
        project_root=str(tmp_path),
        store=store,
        executor=mock_executor,
        bridge=bridge,
        worker_id="worker-continuation-002",
        poll_interval_seconds=0.05,
    )

    # 3. Iteration 1: Worker claims and completes preflight work item
    completed_preflight = asyncio.run(worker.run_once())
    assert completed_preflight is not None
    assert completed_preflight.work_id == "daio-root-change_051_preflight"
    assert completed_preflight.status == DAIOStatus.COMPLETED
    assert completed_preflight.last_decision == "APPROVE"
    assert completed_preflight.authorized_next_phase == "CHANGE_051_OPENSPEC_SCAFFOLD"

    # 4. Verify successor work item was created and persisted in SQLite
    successor_work = store.load_work_item("daio-root-change_051_openspec_scaffold")
    assert successor_work is not None
    assert successor_work.work_id == "daio-root-change_051_openspec_scaffold"
    assert successor_work.change_id == "CHANGE_051_OPENSPEC_SCAFFOLD"
    assert successor_work.parent_work_id == "daio-root-change_051_preflight"
    assert successor_work.metadata["is_production_root"] is True
    assert successor_work.metadata["derived_from_work_id"] == "daio-root-change_051_preflight"
    assert successor_work.status == DAIOStatus.AWAITING_REVIEW

    # 5. Iteration 2: Worker autonomously claims and executes successor work item
    completed_scaffold = asyncio.run(worker.run_once())
    assert completed_scaffold is not None
    assert completed_scaffold.work_id == "daio-root-change_051_openspec_scaffold"
    assert completed_scaffold.status == DAIOStatus.COMPLETED
    assert completed_scaffold.last_decision == "APPROVE"

    # 6. Verify zero-intervention invariants and database state
    all_items = store.list_all_work_items()
    assert len(all_items) == 2
    item_ids = {it.work_id for it in all_items}
    assert item_ids == {"daio-root-change_051_preflight", "daio-root-change_051_openspec_scaffold"}

    for it in all_items:
        assert it.human_relay_count == 0
        assert it.status == DAIOStatus.COMPLETED

    # 7. Verify call history to Lead Architect bridge
    assert len(bridge.call_history) == 3
    # Call 1: CONTRACT_GATE for preflight
    assert "daio-root-change_051_preflight" in bridge.call_history[0]
    assert "CONTRACT_GATE" in bridge.call_history[0]
    # Call 2: CONTRACT_GATE for scaffold
    assert "daio-root-change_051_openspec_scaffold" in bridge.call_history[1]
    assert "CONTRACT_GATE" in bridge.call_history[1]
    # Call 3: IMPLEMENTATION_GATE for scaffold
    assert "daio-root-change_051_openspec_scaffold" in bridge.call_history[2]
    assert "IMPLEMENTATION_GATE" in bridge.call_history[2]



