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

