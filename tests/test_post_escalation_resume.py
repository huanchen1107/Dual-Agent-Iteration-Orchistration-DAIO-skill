"""
Regression tests for DAIO-DEFECT-POST-ESCALATION-RESUME-004.
Validates post-escalation Architect decision ingestion, ACK dispatch,
resumption lifecycle, and fail-closed safety invariants.
"""

import pytest
import asyncio
import datetime
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
from scripts.daio_closed_loop.watchdog import DAIOHandoffWatchdog, WatchdogPolicyAction, classify_work_status_for_watchdog
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter
from scripts.daio_closed_loop.adapters.executor import EngineeringExecutorAdapter, ExecutionResult


def test_scenario_1_handoff_stalled_to_revise_ack_and_claim(tmp_path):
    """
    Scenario 1: HANDOFF_STALLED -> Architect REVISE -> decision ACK -> work eligible -> claim.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s1.db"))
        bridge = MockArchitectBridgeAdapter()
        bridge.transmit_review_request = AsyncMock(return_value=ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            human_approval_required=False,
            instruction="Execute OpenSpec scaffold pass"
        ))
        orchestrator = DAIOClosedLoopOrchestrator(store=store, bridge=bridge)

        # Initial work item in BLOCKED / HUMAN_GATE state
        work = DAIOWorkItem(
            work_id="daio-root-change_051_openspec_scaffold",
            project_root="/tmp",
            change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
            current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
            allowed_scope=[],
        )
        store.save_work_item(work)

        # Process incoming architect REVISE decision
        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            human_approval_required=False,
            instruction="Execute OpenSpec scaffold pass"
        )
        success, updated_work, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=True)

        assert success is True
        assert updated_work.status == DAIOStatus.QUEUED
        assert updated_work.current_gate == DAIOGate.ENGINEERING_TASK
        assert updated_work.assigned_role == DAIORole.ENGINEERING_EXECUTION
        assert updated_work.allowed_scope == ["openspec/**", "_myplan/**", "docs/**"]
        assert ack["event"] == "DECISION_ACKNOWLEDGED"
        assert ack["resulting_durable_status"] == "QUEUED"
        assert ack["human_action_required"] is False

        # Verify work item is now eligible for worker claim
        claimed = store.claim_next_available_work_item(worker_id="worker-001", ttl_seconds=60)
        assert claimed is not None
        assert claimed.work_id == work.work_id

    asyncio.run(_test())


def test_scenario_2_architect_approve_resume(tmp_path):
    """
    Scenario 2: Architect APPROVE resume -> advances contract gate to engineering task or completes.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s2.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        work = DAIOWorkItem(
            work_id="work-approve-001",
            project_root="/tmp",
            change_id="CHANGE_052",
            current_stage="CHANGE_052",
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            status=DAIOStatus.AWAITING_REVIEW,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="APPROVE",
            current_phase="CHANGE_052",
            action="RUN",
            human_approval_required=False,
            instruction="Approved to execute"
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)
        assert success is True
        assert updated.status == DAIOStatus.QUEUED
        assert updated.current_gate == DAIOGate.ENGINEERING_TASK

    asyncio.run(_test())


def test_scenario_3_architect_reject_stop_does_not_resume(tmp_path):
    """
    Scenario 3: Architect REJECT/STOP does not resume.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s3.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        work = DAIOWorkItem(
            work_id="work-stop-001",
            project_root="/tmp",
            change_id="CHANGE_053",
            current_stage="CHANGE_053",
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            status=DAIOStatus.AWAITING_REVIEW,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="STOP",
            current_phase="CHANGE_053",
            action="STOP",
            human_approval_required=True,
            instruction="Halt execution"
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)
        assert success is True
        assert updated.status == DAIOStatus.HUMAN_GATE_REQUIRED
        assert ack["human_action_required"] is True

        # Cannot be claimed by normal queue
        claimed = store.claim_next_available_work_item(worker_id="worker-001")
        assert claimed is None

    asyncio.run(_test())


def test_scenario_4_human_approval_required_true_remains_gated(tmp_path):
    """
    Scenario 4: human_approval_required=true remains genuinely gated.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s4.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        work = DAIOWorkItem(
            work_id="work-gate-001",
            project_root="/tmp",
            change_id="CHANGE_054",
            current_stage="CHANGE_054",
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            status=DAIOStatus.AWAITING_REVIEW,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_054",
            action="RUN",
            human_approval_required=True,
            instruction="Human budget sign-off required before revision"
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)
        assert success is True
        assert updated.status == DAIOStatus.HUMAN_GATE_REQUIRED
        assert updated.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
        assert ack["human_action_required"] is True

    asyncio.run(_test())


def test_scenario_5_human_approval_required_false_never_requires_ide_permission(tmp_path):
    """
    Scenario 5: human_approval_required=false never requires IDE permission merely because previous state was HUMAN_GATE_REQUIRED.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s5.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        work = DAIOWorkItem(
            work_id="daio-root-change_051_openspec_scaffold",
            project_root="/tmp",
            change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
            current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
            current_gate=DAIOGate.HUMAN_GATE,
            assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
            human_gate_reason="Scope violation previously detected",
            allowed_scope=[],
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_051_OPENSPEC_SCAFFOLD",
            action="RUN",
            human_approval_required=False,
            instruction="Execute OpenSpec scaffold pass"
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)
        assert success is True
        assert updated.status == DAIOStatus.QUEUED
        assert updated.human_gate_reason is None
        assert ack["human_action_required"] is False

    asyncio.run(_test())


def test_scenario_6_decision_persistence_failure_emits_architect_decision_not_applied(tmp_path):
    """
    Scenario 6: Decision received but persistence fails (missing work item) -> ARCHITECT_DECISION_NOT_APPLIED.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s6.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="NON_EXISTENT_WORK",
            action="RUN",
            human_approval_required=False,
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision("non-existent-work-id", dec, send_ack=False)
        assert success is False
        assert ack["event"] == "ARCHITECT_DECISION_NOT_APPLIED"
        assert "not found in durable store" in ack["reason"]

    asyncio.run(_test())


def test_scenario_7_decision_persisted_but_work_transition_fails(tmp_path):
    """
    Scenario 7: Invalid decision payload triggers ARCHITECT_DECISION_NOT_APPLIED with failed transition details.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s7.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        work = DAIOWorkItem(
            work_id="work-invalid-dec",
            project_root="/tmp",
            change_id="CHANGE_055",
            status=DAIOStatus.QUEUED,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="INVALID_DECISION_TYPE",
            current_phase="CHANGE_055",
        )
        success, updated, ack = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)
        assert success is False
        assert ack["event"] == "ARCHITECT_DECISION_NOT_APPLIED"
        assert ack["human_action_required"] is True

    asyncio.run(_test())


def test_scenario_8_supervisor_restart_during_decision_application_resumes_idempotently(tmp_path):
    """
    Scenario 8: Supervisor restart during decision application resumes idempotently.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s8.db"))
        work = DAIOWorkItem(
            work_id="daio-root-change_051_openspec_scaffold",
            project_root=str(tmp_path),
            change_id="CHANGE_051_OPENSPEC_SCAFFOLD",
            current_stage="CHANGE_051_OPENSPEC_SCAFFOLD",
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
            metadata={
                "last_architect_decision": {
                    "decision": "REVISE",
                    "current_phase": "CHANGE_051_OPENSPEC_SCAFFOLD",
                    "action": "RUN",
                    "human_approval_required": False,
                    "instruction": "Continue OpenSpec work"
                }
            }
        )
        store.save_work_item(work)

        mock_executor = MagicMock()
        mock_executor.execute_task_async = AsyncMock(return_value=ExecutionResult(
            success=True,
            test_passed=True,
            head_sha="abc1234",
            diff_files=["openspec/changes/051-unattended-acceptance-loop/proposal.md"],
            scope_violation=False,
        ))
        mock_executor.execute_task = MagicMock(return_value=ExecutionResult(
            success=True,
            test_passed=True,
            head_sha="abc1234",
            diff_files=["openspec/changes/051-unattended-acceptance-loop/proposal.md"],
            scope_violation=False,
        ))

        supervisor = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            executor=mock_executor,
            bridge=MockArchitectBridgeAdapter(),
        )

        tick_res = await supervisor.run_tick()
        assert tick_res["worker_processed_item"] == work.work_id
        reloaded = store.load_work_item(work.work_id)
        assert reloaded.status == DAIOStatus.COMPLETED
        assert reloaded.allowed_scope == ["openspec/**", "_myplan/**", "docs/**"]

    asyncio.run(_test())


def test_scenario_9_duplicate_architect_response_does_not_duplicate_work(tmp_path):
    """
    Scenario 9: Duplicate Architect response does not duplicate work items.
    """
    async def _test():
        store = SqliteDAIOWorkStore(db_path=str(tmp_path / "test_s9.db"))
        orchestrator = DAIOClosedLoopOrchestrator(store=store)
        work = DAIOWorkItem(
            work_id="work-dup-001",
            project_root="/tmp",
            change_id="CHANGE_056",
            status=DAIOStatus.QUEUED,
        )
        store.save_work_item(work)

        dec = ArchitectDecision(
            decision="REVISE",
            current_phase="CHANGE_056",
            action="RUN",
            human_approval_required=False,
        )
        # Apply first time
        s1, w1, a1 = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)
        # Apply duplicate second time
        s2, w2, a2 = await orchestrator.process_incoming_architect_decision(work.work_id, dec, send_ack=False)

        all_works = store.list_work_items()
        matching = [w for w in all_works if w.work_id == work.work_id]
        assert len(matching) == 1
        assert len(all_works) == 1

    asyncio.run(_test())


def test_scenario_10_decision_watch_timeout_can_never_silently_return_ok():
    """
    Scenario 10: Watchdog classification for an unhandled or expired state can never silently return OK.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    watch = HandoffWatch(
        watch_id="watch-test",
        parent_work_id="parent-001",
        expected_next_phase="CHANGE_099",
        discovery_deadline=(now - datetime.timedelta(seconds=10)).isoformat(),
        claim_deadline=(now - datetime.timedelta(seconds=10)).isoformat(),
        progress_deadline=(now - datetime.timedelta(seconds=10)).isoformat(),
    )

    # 1. Unknown status -> ESCALATE (never OK)
    mock_work = DAIOWorkItem(
        work_id="work-unknown",
        project_root="/tmp",
        change_id="CHANGE_099",
        status="INVALID_STATUS",  # type: ignore
    )
    action, reason = classify_work_status_for_watchdog(mock_work, watch, now)
    assert action == WatchdogPolicyAction.ESCALATE

    # 2. Blocked item with exhausted budget -> ESCALATE (never OK)
    blocked_work = DAIOWorkItem(
        work_id="work-blocked",
        project_root="/tmp",
        change_id="CHANGE_099",
        status=DAIOStatus.BLOCKED,
        attempt_count=3,
        max_attempts=3,
    )
    action, reason = classify_work_status_for_watchdog(blocked_work, watch, now)
    assert action == WatchdogPolicyAction.ESCALATE
