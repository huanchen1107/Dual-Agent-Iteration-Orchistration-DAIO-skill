"""
Domain Models for DAIO Autonomous Closed Loop (Generic Core).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import datetime
import uuid


class DAIOGate(str, Enum):
    CONTRACT_GATE = "CONTRACT_GATE"
    IMPLEMENTATION_GATE = "IMPLEMENTATION_GATE"
    ENGINEERING_TASK = "ENGINEERING_TASK"
    FREEZE_GATE = "FREEZE_GATE"
    HUMAN_GATE = "HUMAN_GATE"


class DAIORole(str, Enum):
    LEAD_ARCHITECT_REVIEW = "LEAD_ARCHITECT_REVIEW"
    ENGINEERING_EXECUTION = "ENGINEERING_EXECUTION"
    EVIDENCE_AUDIT = "EVIDENCE_AUDIT"
    HUMAN_PROJECT_OWNER = "HUMAN_PROJECT_OWNER"


class DAIOStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"


TERMINAL_PHASES = {
    "STAGE_5_COMPLETE",
    "STAGE_COMPLETE",
    "STAGE_6_COMPLETE",
    "COMPLETE",
    "DONE",
    "TERMINAL",
    "STOP",
    "HUMAN_REVIEW",
    "HUMAN_GATE",
    "NONE",
    "NULL",
    "EXIT",
    "ABORT",
}


def is_terminal_phase(phase: Optional[str]) -> bool:
    """Check if a phase string represents an absolute terminal state that stops execution or indicates completion with no further work."""
    if not phase or not isinstance(phase, str):
        return True
    clean = phase.strip().upper()
    return clean in TERMINAL_PHASES or clean == ""



@dataclass
class ArchitectDecision:
    decision: str  # APPROVE, REVISE, REJECT, HUMAN_REVIEW, STOP
    current_phase: str
    next_phase: Optional[str] = None
    action: str = "RUN"
    human_approval_required: bool = False
    instruction: str = ""
    raw_text: str = ""


@dataclass
class DAIOWorkItem:
    work_id: str
    project_root: str
    change_id: str
    current_stage: str = "S3"
    current_gate: DAIOGate = DAIOGate.CONTRACT_GATE
    assigned_role: DAIORole = DAIORole.LEAD_ARCHITECT_REVIEW
    requested_action: str = ""
    allowed_scope: List[str] = field(default_factory=list)
    base_sha: str = ""
    head_sha: str = ""
    status: DAIOStatus = DAIOStatus.QUEUED
    attempt_count: int = 0
    max_attempts: int = 3
    lease_id: Optional[str] = None
    lease_expires_at: Optional[str] = None
    next_role: Optional[DAIORole] = None
    human_gate_reason: Optional[str] = None
    human_relay_count: int = 0
    architect_endpoint: Dict[str, Any] = field(default_factory=dict)
    parent_work_id: Optional[str] = None
    last_decision: Optional[str] = None
    authorized_next_phase: Optional[str] = None
    claimed_by: Optional[str] = None
    execution_attempt_id: Optional[str] = None
    execution_started_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class DecisionLifecycleStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PERSISTED = "PERSISTED"
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    FAILED_TO_APPLY = "FAILED_TO_APPLY"


class HandoffState(str, Enum):
    SUCCESSOR_EXPECTED = "SUCCESSOR_EXPECTED"
    SUCCESSOR_CREATED = "SUCCESSOR_CREATED"
    WAITING_FOR_CLAIM = "WAITING_FOR_CLAIM"
    CLAIMED = "CLAIMED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    STALLED_DIAGNOSING = "STALLED_DIAGNOSING"
    STALLED_ESCALATED = "STALLED_ESCALATED"


@dataclass
class HandoffWatch:
    watch_id: str
    parent_work_id: str
    expected_next_phase: str
    successor_work_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    discovery_deadline: str = ""
    claim_deadline: str = ""
    first_heartbeat_deadline: str = ""
    progress_deadline: str = ""
    current_state: HandoffState = HandoffState.SUCCESSOR_EXPECTED
    last_progress_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    recovery_attempt_count: int = 0
    max_recovery_attempts: int = 3
    escalation_state: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class PermissionCategory(str, Enum):
    RUNTIME_SAFE_AUTONOMOUS = "RUNTIME_SAFE_AUTONOMOUS"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"
    IDE_DEVELOPMENT_ONLY = "IDE_DEVELOPMENT_ONLY"


class DecisionWatchState(str, Enum):
    DECISION_EXPECTED = "DECISION_EXPECTED"
    DECISION_RECEIVED = "DECISION_RECEIVED"
    DECISION_PERSISTED = "DECISION_PERSISTED"
    RESUME_AUTHORIZED = "RESUME_AUTHORIZED"
    WORK_ELIGIBLE = "WORK_ELIGIBLE"
    WORK_CLAIMED = "WORK_CLAIMED"
    EXECUTING = "EXECUTING"


@dataclass
class DecisionWatch:
    decision_watch_id: str
    work_id: str
    current_phase: str
    state: DecisionWatchState = DecisionWatchState.DECISION_EXPECTED
    decision: Optional[str] = None
    action: Optional[str] = None
    decision_hash: Optional[str] = None
    received_at: Optional[str] = None
    deadline: str = ""
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SupervisorHeartbeat:
    supervisor_id: str
    pid: int
    project_root: str
    status: str = "RUNNING"
    started_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_heartbeat_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_bridge_heartbeat_at: Optional[str] = None
    last_agent_heartbeat_at: Optional[str] = None
    last_progress_at: Optional[str] = None
    active_work_id: Optional[str] = None
    queue_depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)



