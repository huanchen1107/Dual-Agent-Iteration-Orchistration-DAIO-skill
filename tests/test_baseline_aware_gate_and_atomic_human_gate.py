"""
Tests for Baseline-Aware Test Gate, Validation-Only Resume Semantics,
and Atomic HUMAN_GATE_REQUIRED State Invariants.
"""

import os
from pathlib import Path
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock

from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    check_work_item_invariants,
    transition_to_human_gate,
)
from scripts.daio_closed_loop.router import DAIORoleRouter
from scripts.daio_closed_loop.adapters.executor import (
    ExecutionResult,
    SubprocessWorkspaceExecutor,
    extract_pytest_failures,
    is_failure_in_baseline,
)
from scripts.daio_closed_loop.adapters.agent_contract import (
    AgentTaskProposal,
    EngineeringAgentAdapter,
)


def test_extract_pytest_failures_various_formats():
    pytest_output = """
============================= test session starts ==============================
rootdir: /repo, configfile: pytest.ini
collected 533 items / 4 errors

tests/test_pine_smc_reference.py ...................................F.F... [ 50%]
tests/test_pine_smc_reference.py .F.F.................................... [100%]

=================================== FAILURES ===================================
FAILED tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected - AssertionError: assert False
FAILED tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish] - AssertionError: 404
FAILED tests/test_pine_smc_reference.py::test_raw_adapter_payload_matches_direct_public_evaluator_payload - AssertionError
FAILED tests/test_pine_smc_reference.py::test_initial_release_is_frozen_reproducible_and_ledger_is_unverified - AssertionError

=========================== short test summary info ============================
FAILED tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected
FAILED tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish]
FAILED tests/test_pine_smc_reference.py::test_raw_adapter_payload_matches_direct_public_evaluator_payload
FAILED tests/test_pine_smc_reference.py::test_initial_release_is_frozen_reproducible_and_ledger_is_unverified
4 failed, 529 passed, 3 warnings in 4.12s
"""
    failures = extract_pytest_failures(pytest_output)
    assert len(failures) == 4
    assert "tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected" in failures
    assert "tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish]" in failures
    assert "tests/test_pine_smc_reference.py::test_raw_adapter_payload_matches_direct_public_evaluator_payload" in failures
    assert "tests/test_pine_smc_reference.py::test_initial_release_is_frozen_reproducible_and_ledger_is_unverified" in failures


def test_is_failure_in_baseline_matching():
    baseline = [
        "tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected",
        "tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish]",
        "test_raw_adapter_payload_matches_direct_public_evaluator_payload",
        "tests/test_pine_smc_reference.py::test_initial_release_is_frozen_reproducible_and_ledger_is_unverified",
    ]

    # Exact match
    assert is_failure_in_baseline(
        "tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected",
        baseline
    )

    # Parametrized match
    assert is_failure_in_baseline(
        "tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish]",
        baseline
    )

    # Suffix / test name match
    assert is_failure_in_baseline(
        "tests/test_pine_smc_reference.py::test_raw_adapter_payload_matches_direct_public_evaluator_payload",
        baseline
    )

    # Unapproved regression fails
    assert not is_failure_in_baseline(
        "tests/test_agent_governance.py::test_governance_rule",
        baseline
    )


def test_baseline_aware_executor_passes_when_only_approved_failures_present():
    import asyncio

    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path))

            approved_failures = [
                "tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected",
                "tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish]",
                "tests/test_pine_smc_reference.py::test_raw_adapter_payload_matches_direct_public_evaluator_payload",
                "tests/test_pine_smc_reference.py::test_initial_release_is_frozen_reproducible_and_ledger_is_unverified",
            ]

            work = DAIOWorkItem(
                work_id="work-051-test",
                project_root=str(tmp_path),
                change_id="change_051",
                allowed_scope=["src/**", "tests/**"],
                metadata={
                    "baseline_sha": "3836a3e",
                    "baseline_test_failures": approved_failures,
                }
            )

            mock_pytest_output = """
FAILED tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected
FAILED tests/test_pine_smc_reference.py::test_real_fixture_reaches_step_5_and_step_6_for_each_direction[bearish]
FAILED tests/test_pine_smc_reference.py::test_raw_adapter_payload_matches_direct_public_evaluator_payload
FAILED tests/test_pine_smc_reference.py::test_initial_release_is_frozen_reproducible_and_ledger_is_unverified
4 failed, 529 passed
"""
            def mock_run_cmd(cmd):
                if "pytest" in cmd:
                    return 1, mock_pytest_output
                if "git rev-parse HEAD" in cmd:
                    return 0, "mock-sha-123"
                if "git status" in cmd:
                    return 0, ""
                return 0, ""

            executor.run_cmd = MagicMock(side_effect=mock_run_cmd)

            res = await executor.execute_task_async(work)
            assert res.test_passed is True
            assert res.regression_status == "NO_NEW_REGRESSIONS_PASS"
            assert len(res.test_regressions) == 0
            assert len(res.current_failures) == 4

    asyncio.run(_run())


def test_baseline_aware_executor_fails_when_new_regression_detected():
    import asyncio

    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path))

            approved_failures = [
                "tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected",
            ]

            work = DAIOWorkItem(
                work_id="work-051-test",
                project_root=str(tmp_path),
                change_id="change_051",
                allowed_scope=["src/**", "tests/**"],
                metadata={
                    "baseline_sha": "3836a3e",
                    "baseline_test_failures": approved_failures,
                }
            )

            mock_pytest_output = """
FAILED tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected
FAILED tests/test_agent_governance.py::test_unexpected_new_failure
2 failed, 531 passed
"""
            def mock_run_cmd(cmd):
                if "pytest" in cmd:
                    return 1, mock_pytest_output
                if "git rev-parse HEAD" in cmd:
                    return 0, "mock-sha-123"
                if "git status" in cmd:
                    return 0, ""
                return 0, ""

            executor.run_cmd = MagicMock(side_effect=mock_run_cmd)

            res = await executor.execute_task_async(work)
            assert res.test_passed is False
            assert res.regression_status == "NEW_REGRESSIONS_FAIL"
            assert "tests/test_agent_governance.py::test_unexpected_new_failure" in res.test_regressions

    asyncio.run(_run())


def test_validation_only_fast_path_bypasses_agent_proposal():
    import asyncio

    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            mock_adapter = MagicMock(spec=EngineeringAgentAdapter)
            mock_adapter.propose_task_solution = AsyncMock()

            executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path), agent_adapter=mock_adapter)

            work = DAIOWorkItem(
                work_id="work-fast-path",
                project_root=str(tmp_path),
                change_id="change_051",
                requested_action="Validate the existing workspace using the verified Base SHA 3836a3e and baseline-aware no-new-regressions criteria.",
                allowed_scope=["src/**", "tests/**"],
            )

            def mock_run_cmd(cmd):
                if "pytest" in cmd:
                    return 0, "533 passed"
                if "git rev-parse HEAD" in cmd:
                    return 0, "mock-head-sha"
                if "git status" in cmd:
                    return 0, ""
                return 0, ""

            executor.run_cmd = MagicMock(side_effect=mock_run_cmd)

            res = await executor.execute_task_async(work)
            assert res.test_passed is True
            assert res.success is True
            # Coding agent should NOT have been called
            mock_adapter.propose_task_solution.assert_not_called()
            assert "FAST_PATH_VALIDATION_ONLY" in res.output

    asyncio.run(_run())



def test_atomic_human_gate_transition_and_invariants():
    work = DAIOWorkItem(
        work_id="work-invariant-test",
        project_root="/tmp",
        change_id="change_051",
        current_gate=DAIOGate.ENGINEERING_TASK,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        status=DAIOStatus.IN_PROGRESS,
        claimed_by="worker-123",
        lease_id="lease-abc",
        lease_expires_at="2026-09-25T12:00:00Z",
    )

    # Trigger transition
    transition_to_human_gate(work, "Test human gate transition reason")

    # Verify atomic synchronization
    assert work.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert work.current_gate == DAIOGate.HUMAN_GATE
    assert work.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
    assert work.claimed_by is None
    assert work.lease_id is None
    assert work.lease_expires_at is None
    assert work.execution_attempt_id is None
    assert work.human_gate_reason == "Test human gate transition reason"

    # Invariant check must pass with 0 violations
    violations = check_work_item_invariants(work)
    assert len(violations) == 0


def test_router_human_gate_transitions_maintain_invariants():
    work = DAIOWorkItem(
        work_id="work-router-test",
        project_root="/tmp",
        change_id="change_051",
        current_gate=DAIOGate.IMPLEMENTATION_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        claimed_by="worker-1",
        lease_id="lease-1",
    )

    # Decision: STOP
    stop_dec = ArchitectDecision(
        decision="STOP",
        current_phase="change_051",
        instruction="Halt execution for audit",
    )
    routed = DAIORoleRouter.process_architect_review(work, stop_dec, DAIORole.LEAD_ARCHITECT_REVIEW)
    assert check_work_item_invariants(routed) == []
    assert routed.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert routed.current_gate == DAIOGate.HUMAN_GATE
    assert routed.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
    assert routed.claimed_by is None
    assert routed.lease_id is None

    # Engineering max attempts exceeded
    eng_work = DAIOWorkItem(
        work_id="work-eng-fail",
        project_root="/tmp",
        change_id="change_051",
        current_gate=DAIOGate.ENGINEERING_TASK,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        status=DAIOStatus.IN_PROGRESS,
        attempt_count=2,
        max_attempts=3,
        claimed_by="worker-2",
        lease_id="lease-2",
    )
    eng_routed = DAIORoleRouter.process_engineering_completion(
        work=eng_work,
        acting_role=DAIORole.ENGINEERING_EXECUTION,
        test_passed=False,
        commit_sha="dummy",
        execution_error="Persistent test failure",
    )
    assert check_work_item_invariants(eng_routed) == []
    assert eng_routed.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert eng_routed.current_gate == DAIOGate.HUMAN_GATE
    assert eng_routed.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
    assert eng_routed.claimed_by is None


def test_storage_and_acceptance_isolation_invariants():
    from scripts.daio_closed_loop.models import assert_storage_isolation, validate_work_item_isolation

    # Valid sandbox path
    sandbox_root = "/tmp/daio_sandbox_test"
    valid_db = "/tmp/daio_sandbox_test/_daio/daio_work_state.db"
    assert_storage_isolation(valid_db, sandbox_root)

    # Invariant: DB path outside project root must raise PermissionError
    production_db = "/Users/huanchen/Desktop/2026 Projects/2026.8.26AwinFinTechSMCHybridSystemFolder/_AwinFinTechHybridSystem_/_daio/daio_work_state.db"
    with pytest.raises(PermissionError) as exc:
        assert_storage_isolation(production_db, sandbox_root)
    assert "Storage isolation violation" in str(exc.value)

    # Work item root validation
    item = DAIOWorkItem(
        work_id="item-sandbox",
        project_root=sandbox_root,
        change_id="ACCEPTANCE_S56_SYNTHETIC",
    )
    assert validate_work_item_isolation(item, sandbox_root) is True
    assert validate_work_item_isolation(item, "/tmp/other_sandbox") is False


def test_post_completion_handoff_isolation_prevents_production_leakage():
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox_root = str(Path(tmpdir).resolve())
        db_path = str(Path(sandbox_root) / "_daio" / "daio_work.db")
        Path(sandbox_root, "_daio").mkdir(parents=True, exist_ok=True)

        from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
        from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator

        store = SqliteDAIOWorkStore(db_path=db_path)
        orchestrator = DAIOClosedLoopOrchestrator(store=store)

        # Terminal synthetic work item in isolated sandbox
        terminal_item = DAIOWorkItem(
            work_id="daio-synthetic-stage5",
            project_root=sandbox_root,
            change_id="ACCEPTANCE_S56_STAGE_5_TERMINAL",
            current_stage="STAGE_5_COMPLETE",
            current_gate=DAIOGate.FREEZE_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            status=DAIOStatus.COMPLETED,
            last_decision="APPROVE",
            authorized_next_phase="ACCEPTANCE_S56_SYNTHETIC_HANDOFF",
        )
        store.save_work_item(terminal_item)

        # Resolve next work item
        resolved = orchestrator.resolve_next_work_item(terminal_item, terminal_item.authorized_next_phase)
        assert resolved is not None
        assert resolved.project_root == sandbox_root
        assert resolved.change_id == "ACCEPTANCE_S56_SYNTHETIC_HANDOFF"
        assert resolved.parent_work_id == "daio-synthetic-stage5"
        assert resolved.status == DAIOStatus.AWAITING_REVIEW
        assert resolved.current_gate == DAIOGate.CONTRACT_GATE

        # Ensure that only items in this sandbox exist in the store
        all_items = store.list_work_items()
        assert len(all_items) == 2
        for it in all_items:
            assert it.project_root == sandbox_root
            assert "051" not in it.change_id

