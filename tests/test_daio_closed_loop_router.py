import pytest
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole, ArchitectDecision
from scripts.daio_closed_loop.router import DAIORoleRouter

def test_router_contract_gate_approval():
    work = DAIOWorkItem(
        work_id="work-101",
        project_root="/tmp",
        change_id="change-01",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.QUEUED
    )
    decision = ArchitectDecision(decision="APPROVE", current_phase="CONTRACT_GATE")
    updated = DAIORoleRouter.process_architect_review(work, decision, DAIORole.LEAD_ARCHITECT_REVIEW)
    
    assert updated.current_gate == DAIOGate.ENGINEERING_TASK
    assert updated.assigned_role == DAIORole.ENGINEERING_EXECUTION
    assert updated.status == DAIOStatus.QUEUED

def test_router_revision_loop():
    work = DAIOWorkItem(
        work_id="work-102",
        project_root="/tmp",
        change_id="change-01",
        current_gate=DAIOGate.IMPLEMENTATION_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.AWAITING_REVIEW,
        attempt_count=0
    )
    decision = ArchitectDecision(decision="REVISE", current_phase="IMPLEMENTATION_GATE", instruction="Fix bugs")
    updated = DAIORoleRouter.process_architect_review(work, decision, DAIORole.LEAD_ARCHITECT_REVIEW)
    
    assert updated.current_gate == DAIOGate.ENGINEERING_TASK
    assert updated.assigned_role == DAIORole.ENGINEERING_EXECUTION
    assert updated.status == DAIOStatus.QUEUED
    assert updated.attempt_count == 0
    assert "Fix bugs" in updated.requested_action

def test_router_human_gate_escalation():
    work = DAIOWorkItem(
        work_id="work-103",
        project_root="/tmp",
        change_id="change-01",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        status=DAIOStatus.QUEUED
    )
    decision = ArchitectDecision(decision="HUMAN_REVIEW", current_phase="CONTRACT_GATE", human_approval_required=True, instruction="Requires human budget sign-off")
    updated = DAIORoleRouter.process_architect_review(work, decision, DAIORole.LEAD_ARCHITECT_REVIEW)
    
    assert updated.current_gate == DAIOGate.HUMAN_GATE
    assert updated.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
    assert updated.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert "Requires human budget sign-off" in updated.human_gate_reason
