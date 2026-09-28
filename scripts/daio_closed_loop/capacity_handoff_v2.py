"""C1.4 Phase 4D — Capacity-Aware Safe Handoff Controller.

Integrates the Phase-4C CapacityRegistry with the Phase-3B3 DurableHandoff
to produce a safe, automatic capacity-aware handoff state machine.

Contract:
- Capacity failures are outside the engineering failure budget (not FAIL).
- A VALID, VERIFIED durable checkpoint is required before any handoff.
- Missing / corrupt / hash-mismatched / work-mismatched / attempt-mismatched
  checkpoints FAIL CLOSED; no backend-B authority is granted.
- Authority is explicitly revoked from backend-A before backend-B is authorized.
- The fencing token advances on every attempt transition.
- Capacity is revalidated (TOCTOU guard) immediately before backend-B launch.
- State is persisted to SQLite so controller restarts are safe.
- Stale publications from a superseded attempt are rejected.
- No real backend is invoked; backends are represented as ExecutionCandidate +
  BackendIdentity objects supplied by the trusted controller.
"""
from __future__ import annotations

import datetime
import enum
import json
import sqlite3
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple

from .capacity import CapacityRegistry, ExecutionCandidate, CapacityState
from .handoff_contract import (
    CHECKPOINT_VERSION, digest, canonical,
)


# ---------------------------------------------------------------------------
# Handoff state machine states
# ---------------------------------------------------------------------------

class HandoffPhase(enum.Enum):
    IDLE = "IDLE"
    ENROLLED = "ENROLLED"
    BACKEND_A_EXECUTING = "BACKEND_A_EXECUTING"
    CAPACITY_INTERRUPTED = "CAPACITY_INTERRUPTED"
    CHECKPOINT_VERIFIED = "CHECKPOINT_VERIFIED"
    AUTHORITY_REVOKED = "AUTHORITY_REVOKED"
    BACKEND_B_AUTHORIZED = "BACKEND_B_AUTHORIZED"
    BACKEND_B_EXECUTING = "BACKEND_B_EXECUTING"
    COMPLETED = "COMPLETED"
    WAITING_FOR_EXECUTION_CAPACITY = "WAITING_FOR_EXECUTION_CAPACITY"
    FAILED_CLOSED = "FAILED_CLOSED"


@dataclass
class HandoffState:
    work_id: str
    execution_attempt_id: str
    fencing_token: int
    phase: HandoffPhase
    checkpoint_id: Optional[str]
    checkpoint_sha256: Optional[str]
    active_backend_id: Optional[str]
    revocation_recorded: bool
    failure_reason: Optional[str]

    def to_dict(self):
        d = asdict(self)
        d["phase"] = self.phase.value
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            work_id=d["work_id"],
            execution_attempt_id=d["execution_attempt_id"],
            fencing_token=d["fencing_token"],
            phase=HandoffPhase(d["phase"]),
            checkpoint_id=d.get("checkpoint_id"),
            checkpoint_sha256=d.get("checkpoint_sha256"),
            active_backend_id=d.get("active_backend_id"),
            revocation_recorded=d.get("revocation_recorded", False),
            failure_reason=d.get("failure_reason"),
        )


@dataclass
class CheckpointVerificationResult:
    verified: bool
    failure_reason: Optional[str]
    checkpoint_id: Optional[str]
    checkpoint_sha256: Optional[str]


@dataclass
class CandidateSelectionResult:
    selected: Optional[ExecutionCandidate]
    reason: str  # SELECTED / NO_CAPACITY / TOCTOU_REVALIDATION_FAILED / STALE_OBSERVATION


@dataclass
class HandoffResult:
    success: bool
    phase: HandoffPhase
    reason: str
    new_attempt_id: Optional[str] = None
    fencing_token: Optional[int] = None


# ---------------------------------------------------------------------------
# Strict checkpoint verifier (fail-closed)
# ---------------------------------------------------------------------------

def verify_checkpoint(
    conn: sqlite3.Connection,
    work_id: str,
    expected_attempt_id: str,
    expected_fencing_token: int,
) -> CheckpointVerificationResult:
    """Verify the durable checkpoint for a work item.

    Returns verified=True only if ALL of the following hold:
    1. A checkpoint record exists.
    2. The stored SHA-256 matches the re-computed digest of the payload.
    3. The checkpoint work_id matches the expected work_id.
    4. The checkpoint execution_attempt_id matches expected_attempt_id.
    5. The checkpoint fencing_token matches expected_fencing_token.
    6. The checkpoint contract_version matches CHECKPOINT_VERSION.

    Any deviation => verified=False, fail closed, reason recorded.
    """
    cursor = conn.execute(
        "SELECT checkpoint_id, sha256, payload FROM daio_checkpoints "
        "WHERE checkpoint_id = ("
        "  SELECT checkpoint_id FROM daio_backend_control WHERE work_id = ?"
        ")",
        (work_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_MISSING",
            checkpoint_id=None,
            checkpoint_sha256=None,
        )

    checkpoint_id, stored_sha, payload_json = row[0], row[1], row[2]

    # Integrity: re-digest the raw payload text
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_CORRUPT_PAYLOAD",
            checkpoint_id=checkpoint_id,
            checkpoint_sha256=stored_sha,
        )

    recomputed = digest(payload)
    if recomputed != stored_sha:
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_HASH_MISMATCH",
            checkpoint_id=checkpoint_id,
            checkpoint_sha256=stored_sha,
        )

    # Work binding
    if payload.get("work_id") != work_id:
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_WORK_MISMATCH",
            checkpoint_id=checkpoint_id,
            checkpoint_sha256=stored_sha,
        )

    # Attempt binding
    if payload.get("execution_attempt_id") != expected_attempt_id:
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_ATTEMPT_MISMATCH",
            checkpoint_id=checkpoint_id,
            checkpoint_sha256=stored_sha,
        )

    # Fencing token binding
    if payload.get("fencing_token") != expected_fencing_token:
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_FENCING_TOKEN_MISMATCH",
            checkpoint_id=checkpoint_id,
            checkpoint_sha256=stored_sha,
        )

    # Contract version
    if payload.get("contract_version") != CHECKPOINT_VERSION:
        return CheckpointVerificationResult(
            verified=False,
            failure_reason="CHECKPOINT_VERSION_MISMATCH",
            checkpoint_id=checkpoint_id,
            checkpoint_sha256=stored_sha,
        )

    return CheckpointVerificationResult(
        verified=True,
        failure_reason=None,
        checkpoint_id=checkpoint_id,
        checkpoint_sha256=stored_sha,
    )


# ---------------------------------------------------------------------------
# Capacity-aware handoff controller
# ---------------------------------------------------------------------------

class CapacityHandoffController:
    """Capacity-aware handoff state machine.

    Integrates CapacityRegistry (Phase 4C) with DurableHandoff (Phase 3B3).
    Uses deterministic fake backends for tests; no real backend invocation.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS c14_handoff_controller_state (
            work_id TEXT PRIMARY KEY,
            phase TEXT NOT NULL,
            execution_attempt_id TEXT NOT NULL,
            fencing_token INTEGER NOT NULL,
            checkpoint_id TEXT,
            checkpoint_sha256 TEXT,
            active_backend_id TEXT,
            revocation_recorded INTEGER NOT NULL DEFAULT 0,
            failure_reason TEXT,
            updated_at TEXT NOT NULL
        );
    """

    def __init__(self, capacity_registry: CapacityRegistry, db_path: str):
        self.capacity_registry = capacity_registry
        self.db_path = db_path
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self._DDL)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self, work_id: str) -> Optional[HandoffState]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT work_id, execution_attempt_id, fencing_token, phase, "
                "checkpoint_id, checkpoint_sha256, active_backend_id, "
                "revocation_recorded, failure_reason "
                "FROM c14_handoff_controller_state WHERE work_id = ?",
                (work_id,),
            ).fetchone()
        if row is None:
            return None
        return HandoffState(
            work_id=row[0],
            execution_attempt_id=row[1],
            fencing_token=row[2],
            phase=HandoffPhase(row[3]),
            checkpoint_id=row[4],
            checkpoint_sha256=row[5],
            active_backend_id=row[6],
            revocation_recorded=bool(row[7]),
            failure_reason=row[8],
        )

    def _save(self, state: HandoffState) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO c14_handoff_controller_state
                   (work_id, phase, execution_attempt_id, fencing_token,
                    checkpoint_id, checkpoint_sha256, active_backend_id,
                    revocation_recorded, failure_reason, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(work_id) DO UPDATE SET
                   phase=excluded.phase,
                   execution_attempt_id=excluded.execution_attempt_id,
                   fencing_token=excluded.fencing_token,
                   checkpoint_id=excluded.checkpoint_id,
                   checkpoint_sha256=excluded.checkpoint_sha256,
                   active_backend_id=excluded.active_backend_id,
                   revocation_recorded=excluded.revocation_recorded,
                   failure_reason=excluded.failure_reason,
                   updated_at=excluded.updated_at""",
                (
                    state.work_id, state.phase.value, state.execution_attempt_id,
                    state.fencing_token, state.checkpoint_id, state.checkpoint_sha256,
                    state.active_backend_id, int(state.revocation_recorded),
                    state.failure_reason, now,
                ),
            )

    def _fail_closed(self, state: HandoffState, reason: str) -> HandoffResult:
        state.phase = HandoffPhase.FAILED_CLOSED
        state.failure_reason = reason
        self._save(state)
        return HandoffResult(
            success=False,
            phase=HandoffPhase.FAILED_CLOSED,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enroll(self, work_id: str, attempt_id: str, fencing_token: int) -> HandoffState:
        state = HandoffState(
            work_id=work_id,
            execution_attempt_id=attempt_id,
            fencing_token=fencing_token,
            phase=HandoffPhase.ENROLLED,
            checkpoint_id=None,
            checkpoint_sha256=None,
            active_backend_id=None,
            revocation_recorded=False,
            failure_reason=None,
        )
        self._save(state)
        return state

    def record_capacity_interruption(
        self,
        work_id: str,
        interrupted_attempt_id: str,
        interrupted_fencing_token: int,
        backend_id: str,
    ) -> HandoffResult:
        state = self._load(work_id)
        if state is None:
            return HandoffResult(success=False, phase=HandoffPhase.FAILED_CLOSED,
                                 reason="CONTROLLER_STATE_NOT_FOUND")
        if state.execution_attempt_id != interrupted_attempt_id:
            return HandoffResult(success=False, phase=state.phase,
                                 reason="STALE_ATTEMPT_ID")
        if state.fencing_token != interrupted_fencing_token:
            return HandoffResult(success=False, phase=state.phase,
                                 reason="STALE_FENCING_TOKEN")
        state.phase = HandoffPhase.CAPACITY_INTERRUPTED
        state.active_backend_id = backend_id
        self._save(state)
        return HandoffResult(success=True, phase=state.phase,
                             reason="CAPACITY_INTERRUPTION_RECORDED")

    def verify_checkpoint_and_authorize_handoff(
        self,
        work_id: str,
        handoff_conn: sqlite3.Connection,
    ) -> HandoffResult:
        """Verify the durable checkpoint; fail closed if any issue.

        VALID + VERIFIED checkpoint => advance to CHECKPOINT_VERIFIED.
        MISSING / CORRUPT / HASH MISMATCH / WORK MISMATCH / ATTEMPT MISMATCH /
        FENCING MISMATCH / VERSION MISMATCH => FAILED_CLOSED.
        Backend-B is never authorized after a checkpoint verification failure.
        """
        state = self._load(work_id)
        if state is None:
            return HandoffResult(success=False, phase=HandoffPhase.FAILED_CLOSED,
                                 reason="CONTROLLER_STATE_NOT_FOUND")
        if state.phase not in (HandoffPhase.CAPACITY_INTERRUPTED, HandoffPhase.ENROLLED):
            return self._fail_closed(
                state, f"INVALID_PHASE_FOR_CHECKPOINT_VERIFY:{state.phase.value}")

        result = verify_checkpoint(
            handoff_conn, work_id,
            state.execution_attempt_id, state.fencing_token)
        if not result.verified:
            return self._fail_closed(state, result.failure_reason)

        state.phase = HandoffPhase.CHECKPOINT_VERIFIED
        state.checkpoint_id = result.checkpoint_id
        state.checkpoint_sha256 = result.checkpoint_sha256
        self._save(state)
        return HandoffResult(success=True, phase=HandoffPhase.CHECKPOINT_VERIFIED,
                             reason="CHECKPOINT_VERIFIED")

    def revoke_current_backend(self, work_id: str) -> HandoffResult:
        """Explicitly revoke backend-A authority before authorizing backend-B."""
        state = self._load(work_id)
        if state is None:
            return HandoffResult(success=False, phase=HandoffPhase.FAILED_CLOSED,
                                 reason="CONTROLLER_STATE_NOT_FOUND")
        if state.phase != HandoffPhase.CHECKPOINT_VERIFIED:
            return self._fail_closed(
                state, f"REVOCATION_REQUIRES_CHECKPOINT_VERIFIED:{state.phase.value}")
        state.phase = HandoffPhase.AUTHORITY_REVOKED
        state.revocation_recorded = True
        self._save(state)
        return HandoffResult(success=True, phase=HandoffPhase.AUTHORITY_REVOKED,
                             reason="BACKEND_AUTHORITY_REVOKED")

    def select_and_authorize_backend_b(
        self,
        work_id: str,
        candidates: List[ExecutionCandidate],
        required_safety_contract: str,
        work_compatibility_reqs: List[str],
        now: Optional[datetime.datetime] = None,
    ) -> Tuple[HandoffResult, CandidateSelectionResult]:
        """TOCTOU-revalidate capacity and select backend-B."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)

        state = self._load(work_id)
        if state is None:
            return (
                HandoffResult(success=False, phase=HandoffPhase.FAILED_CLOSED,
                              reason="CONTROLLER_STATE_NOT_FOUND"),
                CandidateSelectionResult(selected=None, reason="CONTROLLER_STATE_NOT_FOUND"),
            )
        if state.phase != HandoffPhase.AUTHORITY_REVOKED:
            fr = self._fail_closed(
                state, f"BACKEND_B_REQUIRES_AUTHORITY_REVOKED:{state.phase.value}")
            return fr, CandidateSelectionResult(selected=None, reason=fr.reason)

        selected = self.capacity_registry.select_candidate(
            candidates, required_safety_contract, work_compatibility_reqs, now)
        if selected is None:
            state.phase = HandoffPhase.WAITING_FOR_EXECUTION_CAPACITY
            state.failure_reason = "NO_AVAILABLE_BACKEND_B_CAPACITY"
            self._save(state)
            return (
                HandoffResult(success=False,
                              phase=HandoffPhase.WAITING_FOR_EXECUTION_CAPACITY,
                              reason="WAITING_FOR_EXECUTION_CAPACITY"),
                CandidateSelectionResult(selected=None, reason="NO_CAPACITY"),
            )

        # Advance fencing token for backend-B attempt
        state.fencing_token += 1
        state.phase = HandoffPhase.BACKEND_B_AUTHORIZED
        state.active_backend_id = (
            f"{selected.provider_id}:{selected.backend_id}:{selected.model_id}")
        self._save(state)
        return (
            HandoffResult(success=True, phase=HandoffPhase.BACKEND_B_AUTHORIZED,
                          reason="BACKEND_B_AUTHORIZED",
                          fencing_token=state.fencing_token),
            CandidateSelectionResult(selected=selected, reason="SELECTED"),
        )

    def record_backend_b_started(self, work_id: str, new_attempt_id: str) -> HandoffResult:
        state = self._load(work_id)
        if state is None:
            return HandoffResult(success=False, phase=HandoffPhase.FAILED_CLOSED,
                                 reason="CONTROLLER_STATE_NOT_FOUND")
        if state.phase != HandoffPhase.BACKEND_B_AUTHORIZED:
            return self._fail_closed(
                state, f"NOT_IN_BACKEND_B_AUTHORIZED:{state.phase.value}")
        state.execution_attempt_id = new_attempt_id
        state.phase = HandoffPhase.BACKEND_B_EXECUTING
        self._save(state)
        return HandoffResult(success=True, phase=HandoffPhase.BACKEND_B_EXECUTING,
                             reason="BACKEND_B_EXECUTING", new_attempt_id=new_attempt_id)

    def record_completion(self, work_id: str) -> HandoffResult:
        state = self._load(work_id)
        if state is None:
            return HandoffResult(success=False, phase=HandoffPhase.FAILED_CLOSED,
                                 reason="CONTROLLER_STATE_NOT_FOUND")
        state.phase = HandoffPhase.COMPLETED
        self._save(state)
        return HandoffResult(success=True, phase=HandoffPhase.COMPLETED, reason="COMPLETED")

    def get_state(self, work_id: str) -> Optional[HandoffState]:
        """Return persisted controller state (restart-safe)."""
        return self._load(work_id)

    def is_stale_publication(
        self, work_id: str, attempt_id: str, fencing_token: int
    ) -> bool:
        """Return True if the publication is from a superseded attempt."""
        state = self._load(work_id)
        if state is None:
            return True
        return (
            state.execution_attempt_id != attempt_id
            or state.fencing_token != fencing_token
        )
