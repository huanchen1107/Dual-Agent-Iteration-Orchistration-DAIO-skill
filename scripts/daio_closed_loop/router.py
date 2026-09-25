"""
Role Router & Gate Authority Engine for Generic DAIO Closed Loop.
"""

from __future__ import annotations
import datetime
from typing import Optional

from .models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    is_terminal_phase,
    transition_to_human_gate,
)


class DAIORoleRouter:
    """
    Enforces Gate Authority Matrix and routes work to authorized roles.
    Prevents unauthorized self-promotion across architecture gates.
    """

    @staticmethod
    def process_architect_review(work: DAIOWorkItem, decision: ArchitectDecision, acting_role: DAIORole) -> DAIOWorkItem:
        """Route work item following Architect review decision."""
        if acting_role not in {DAIORole.LEAD_ARCHITECT_REVIEW, DAIORole.HUMAN_PROJECT_OWNER}:
            raise PermissionError(f"Role '{acting_role.value}' is not authorized to perform Architect Gate review.")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        work.updated_at = now
        work.last_decision = decision.decision
        work.authorized_next_phase = decision.next_phase
        if not hasattr(work, "metadata") or work.metadata is None:
            work.metadata = {}
        work.metadata["last_architect_decision"] = {
            "decision": decision.decision,
            "current_phase": decision.current_phase,
            "next_phase": decision.next_phase,
            "action": decision.action,
            "human_approval_required": decision.human_approval_required,
            "instruction": decision.instruction,
            "timestamp": now,
        }

        if decision.human_approval_required or decision.decision == "HUMAN_REVIEW":
            reason = decision.instruction or "Architect requested Human Project Owner review."
            return transition_to_human_gate(work, reason)

        if decision.decision == "APPROVE":
            # Check if this APPROVE authorized a distinct next phase
            if (
                decision.next_phase
                and isinstance(decision.next_phase, str)
                and decision.next_phase.strip()
                and decision.next_phase.strip().upper() != work.current_stage.strip().upper()
                and decision.next_phase.strip().upper() != work.change_id.strip().upper()
                and not is_terminal_phase(decision.next_phase)
            ):
                work.status = DAIOStatus.COMPLETED
                work.requested_action = decision.instruction or f"Completed {work.change_id} -> authorized {decision.next_phase}"
                return work

            if work.current_gate == DAIOGate.CONTRACT_GATE or (work.current_gate == DAIOGate.HUMAN_GATE and decision.action == "RUN"):
                # Contract Gate or Human Gate passed -> advance to Engineering Task (READY in queue)
                work.current_gate = DAIOGate.ENGINEERING_TASK
                work.assigned_role = DAIORole.ENGINEERING_EXECUTION
                work.status = DAIOStatus.QUEUED
                work.requested_action = decision.instruction or "Execute approved engineering milestones."
                work.human_gate_reason = None
                work.attempt_count = 0
                work.claimed_by = None
                work.lease_id = None
                work.lease_expires_at = None
                work.execution_attempt_id = None
                work.execution_started_at = None
            elif work.current_gate == DAIOGate.IMPLEMENTATION_GATE:
                # Implementation Gate passed -> Complete or advance phase
                work.status = DAIOStatus.COMPLETED
                work.requested_action = decision.instruction or "Implementation verified and approved."
            return work

        if decision.decision == "REVISE":
            # Revision requested -> loop back to engineering queue (READY)
            work.current_gate = DAIOGate.ENGINEERING_TASK
            work.assigned_role = DAIORole.ENGINEERING_EXECUTION
            work.status = DAIOStatus.QUEUED
            work.requested_action = decision.instruction or "Implement requested revisions."
            work.human_gate_reason = None
            work.claimed_by = None
            work.lease_id = None
            work.lease_expires_at = None
            work.execution_attempt_id = None
            work.execution_started_at = None
            work.attempt_count = 0  # Reset attempt budget for new authorized turn

            # If work item is in OpenSpec/contract planning stage and allowed_scope is empty,
            # derive and persist the explicit bounded planning scope (never unrestricted)
            if (not work.allowed_scope or work.allowed_scope == []) and (
                "OPENSPEC" in work.current_stage.upper()
                or "SCAFFOLD" in work.current_stage.upper()
                or "CONTRACT" in work.current_stage.upper()
                or "openspec" in (decision.instruction or "").lower()
            ):
                work.allowed_scope = ["openspec/**", "_myplan/**", "docs/**"]

            return work

        if decision.decision == "REJECT" or decision.decision == "STOP" or decision.action == "STOP":
            reason = f"Architect issued {decision.decision}: {decision.instruction}"
            return transition_to_human_gate(work, reason)

        raise ValueError(f"Unknown architect decision value: '{decision.decision}'")

    @staticmethod
    def process_engineering_completion(
        work: DAIOWorkItem,
        acting_role: DAIORole,
        test_passed: bool,
        commit_sha: str,
        execution_error: Optional[str] = None,
    ) -> DAIOWorkItem:
        """Route work item following engineering task execution."""
        if acting_role != DAIORole.ENGINEERING_EXECUTION:
            raise PermissionError(f"Role '{acting_role.value}' is not authorized to execute engineering tasks.")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        work.updated_at = now
        work.head_sha = commit_sha

        if not test_passed:
            work.attempt_count += 1
            if work.attempt_count >= work.max_attempts:
                # Exhausted recovery budget -> escalate to human
                reason = f"Test integrity gate failed max attempts ({work.max_attempts}). Detail: {execution_error or 'Tests failed'}"
                return transition_to_human_gate(work, reason)
            else:
                work.status = DAIOStatus.BLOCKED
            return work

        # Engineering success -> advance to Lead Architect review
        work.current_gate = DAIOGate.IMPLEMENTATION_GATE
        work.assigned_role = DAIORole.LEAD_ARCHITECT_REVIEW
        work.status = DAIOStatus.AWAITING_REVIEW
        work.requested_action = "Review engineering deliverables and test evidence."
        return work
