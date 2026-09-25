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
    recovery_epoch_id: str = "epoch-initial"
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


def transition_to_human_gate(work: DAIOWorkItem, reason: str) -> DAIOWorkItem:
    """
    Atomically transitions a work item to HUMAN_GATE_REQUIRED.
    Guarantees that status, current_gate, assigned_role, and lease state remain strictly synchronized.
    """
    work.status = DAIOStatus.HUMAN_GATE_REQUIRED
    work.current_gate = DAIOGate.HUMAN_GATE
    work.assigned_role = DAIORole.HUMAN_PROJECT_OWNER
    work.human_gate_reason = reason
    work.claimed_by = None
    work.lease_id = None
    work.lease_expires_at = None
    work.execution_attempt_id = None
    work.execution_started_at = None
    work.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return work


def check_work_item_invariants(work: DAIOWorkItem) -> List[str]:
    """
    Validates structural invariants on DAIOWorkItem state.
    Returns a list of invariant violation error messages (empty if valid).
    """
    violations: List[str] = []
    if work.status == DAIOStatus.HUMAN_GATE_REQUIRED:
        if work.current_gate != DAIOGate.HUMAN_GATE:
            violations.append(f"Invariant violation: status is HUMAN_GATE_REQUIRED but current_gate is {work.current_gate}")
        if work.assigned_role != DAIORole.HUMAN_PROJECT_OWNER:
            violations.append(f"Invariant violation: status is HUMAN_GATE_REQUIRED but assigned_role is {work.assigned_role}")
        if work.claimed_by is not None:
            violations.append(f"Invariant violation: status is HUMAN_GATE_REQUIRED but claimed_by is '{work.claimed_by}'")
        if work.lease_id is not None:
            violations.append(f"Invariant violation: status is HUMAN_GATE_REQUIRED but lease_id is '{work.lease_id}'")
    return violations


def assert_storage_isolation(store_db_path: str, project_root: str) -> None:
    """
    Enforces storage and work-item isolation.
    Verifies that the SQLite database resides strictly within the declared project root
    and prevents test harnesses or foreign processes from mutating other workspaces.
    """
    from pathlib import Path
    db_p = Path(store_db_path).resolve()
    root_p = Path(project_root).resolve()
    if not (db_p == root_p or root_p in db_p.parents):
        raise PermissionError(f"Storage isolation violation: DB '{db_p}' is outside project root '{root_p}'")


def validate_work_item_isolation(work: DAIOWorkItem, expected_project_root: str) -> bool:
    """
    Verifies that a work item strictly belongs to the expected project root.
    Prevents cross-workspace claiming or mutation.
    """
    from pathlib import Path
    work_root = Path(work.project_root).resolve()
    exp_root = Path(expected_project_root).resolve()
    return work_root == exp_root


# ---------------------------------------------------------------------------
# Remote Project Cockpit (RPC) - Two-Plane Models & Freshness State Engine
# ---------------------------------------------------------------------------

class FreshnessEnum(str, Enum):
    FRESH = "FRESH"      # Heartbeat age < 30 seconds
    STALE = "STALE"      # Heartbeat age 30s..180s
    OFFLINE = "OFFLINE"  # Heartbeat age > 180s or supervisor stopped
    UNKNOWN = "UNKNOWN"  # Heartbeat source uninitialized or cannot be determined


def evaluate_freshness(
    heartbeat_timestamp: Optional[str],
    current_time: Optional[datetime.datetime] = None,
    is_supervisor_running: bool = True,
) -> tuple[FreshnessEnum, Optional[float]]:
    """
    Calculates freshness classification and heartbeat age in seconds according to canonical thresholds:
    - FRESH: age < 30.0s
    - STALE: 30.0s <= age <= 180.0s
    - OFFLINE: age > 180.0s OR not is_supervisor_running
    - UNKNOWN: heartbeat_timestamp is None/empty/unparseable
    """
    if not heartbeat_timestamp or not isinstance(heartbeat_timestamp, str):
        return FreshnessEnum.UNKNOWN, None

    try:
        ts_clean = heartbeat_timestamp.strip()
        if ts_clean.endswith("Z"):
            ts_clean = ts_clean[:-1] + "+00:00"
        parsed_ts = datetime.datetime.fromisoformat(ts_clean)
        if parsed_ts.tzinfo is None:
            parsed_ts = parsed_ts.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return FreshnessEnum.UNKNOWN, None

    now = current_time or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    age_seconds = (now - parsed_ts).total_seconds()
    if age_seconds < 0:
        age_seconds = 0.0
    age_rounded = round(age_seconds, 1)

    if not is_supervisor_running:
        return FreshnessEnum.OFFLINE, age_rounded

    if age_seconds < 30.0:
        return FreshnessEnum.FRESH, age_rounded
    elif age_seconds <= 180.0:
        return FreshnessEnum.STALE, age_rounded
    else:
        return FreshnessEnum.OFFLINE, age_rounded


@dataclass
class LivePlaneStatus:
    project_name: str = "unknown"
    host: str = "unknown"
    host_status: str = "UNKNOWN"  # "ONLINE", "OFFLINE", "UNKNOWN"
    freshness: FreshnessEnum = FreshnessEnum.UNKNOWN
    last_heartbeat_timestamp: Optional[str] = None
    heartbeat_age_seconds: Optional[float] = None
    supervisor_running: bool = False
    supervisor_pid: Optional[int] = None
    active_work_id: Optional[str] = None
    active_work_item: Optional[str] = None
    current_phase: Optional[str] = None
    current_gate: Optional[str] = None
    assigned_role: Optional[str] = None
    human_gate_required: bool = False
    human_gate_reason: Optional[str] = None
    recovery_epoch_id: Optional[str] = None
    active_agent: Optional[str] = None
    queue_depth: int = 0
    degraded_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "host": self.host,
            "host_status": self.host_status,
            "freshness": self.freshness.value if isinstance(self.freshness, FreshnessEnum) else str(self.freshness),
            "last_heartbeat_timestamp": self.last_heartbeat_timestamp,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "supervisor_running": self.supervisor_running,
            "supervisor_pid": self.supervisor_pid,
            "active_work_id": self.active_work_id,
            "active_work_item": self.active_work_item,
            "current_phase": self.current_phase,
            "current_gate": self.current_gate,
            "assigned_role": self.assigned_role,
            "human_gate_required": self.human_gate_required,
            "human_gate_reason": self.human_gate_reason,
            "recovery_epoch_id": self.recovery_epoch_id,
            "active_agent": self.active_agent,
            "queue_depth": self.queue_depth,
            "degraded_note": self.degraded_note,
        }


@dataclass
class DurablePlaneStatus:
    repository: Optional[str] = None
    git_branch: Optional[str] = None
    local_head_sha: Optional[str] = None
    remote_origin_sha: Optional[str] = None
    ahead_count: int = 0
    behind_count: int = 0
    working_tree_clean: bool = True
    push_synchronized: bool = False
    latest_durable_milestone: Optional[str] = None
    latest_completed_change: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repository": self.repository,
            "git_branch": self.git_branch,
            "local_head_sha": self.local_head_sha,
            "remote_origin_sha": self.remote_origin_sha,
            "ahead_count": self.ahead_count,
            "behind_count": self.behind_count,
            "working_tree_clean": self.working_tree_clean,
            "push_synchronized": self.push_synchronized,
            "latest_durable_milestone": self.latest_durable_milestone,
            "latest_completed_change": self.latest_completed_change,
        }


@dataclass
class DAIOProjectStatusResponse:
    live_plane: LivePlaneStatus
    durable_plane: DurablePlaneStatus
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "live_plane": self.live_plane.to_dict(),
            "durable_plane": self.durable_plane.to_dict(),
            "provenance": self.provenance,
        }







