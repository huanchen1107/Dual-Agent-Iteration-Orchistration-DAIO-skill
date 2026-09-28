"""C1.4 Phase 4D — Capacity-Aware Handoff Controller Tests.

Covers:
- Capacity-aware candidate selection (happy path)
- Same work_id / new execution_attempt_id on handoff
- Capacity failures outside engineering failure budget
- Verified durable checkpoint required for handoff
- Missing checkpoint fails closed (negative)
- Corrupted checkpoint payload fails closed (negative)
- Hash-mismatched checkpoint fails closed (negative)
- Work-mismatched checkpoint fails closed (negative)
- Attempt-mismatched checkpoint fails closed (negative)
- Fencing-token-mismatched checkpoint fails closed (negative)
- Authority revoked before backend-B authorization
- Fencing advances on backend-B authorization
- TOCTOU capacity revalidation (no capacity at time of B selection)
- No-capacity transitions to WAITING_FOR_EXECUTION_CAPACITY
- Restart-safe persisted state (controller reload)
- Stale publication rejection (wrong attempt or fencing)
- Backend-B authority rejected after checkpoint verification failure
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import tempfile
import os
import pytest

from scripts.daio_closed_loop.capacity import (
    CapacityRegistry, CapacityObservation, CapacityState, ExecutionCandidate,
)
from scripts.daio_closed_loop.capacity_handoff_v2 import (
    CapacityHandoffController, HandoffPhase, verify_checkpoint,
)
from scripts.daio_closed_loop.handoff_contract import CHECKPOINT_VERSION, digest, canonical


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_db(tmp_path=None):
    if tmp_path:
        return str(tmp_path / "c14_4d.db")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _make_capacity_registry(db_path):
    return CapacityRegistry(db_path, stale_seconds=300)


def _make_controller(registry, db_path):
    return CapacityHandoffController(registry, db_path)


def _observe(registry, provider, backend, model, state=CapacityState.AVAILABLE):
    registry.record_observation(CapacityObservation(
        provider_id=provider,
        backend_id=backend,
        model_id=model,
        observed_state=state,
        observed_at=_now().isoformat(),
        observation_source="test",
        sanitized_reason="",
        compatibility_state="FULLY_COMPATIBLE",
    ))


def _candidate(provider, backend, model, priority=10):
    return ExecutionCandidate(
        provider_id=provider,
        backend_id=backend,
        model_id=model,
        priority=priority,
        authorized=True,
        requires_safety_contract="ROUTE_B_ISOLATED",
    )


def _make_handoff_conn():
    """Return a real SQLite connection with the DurableHandoff schema (enough for checkpoint tests)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daio_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daio_backend_control (
            work_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            policy TEXT NOT NULL,
            manifest TEXT NOT NULL,
            checkpoint_id TEXT NOT NULL,
            authorization_id TEXT,
            authorized_backend TEXT,
            quiescence TEXT NOT NULL DEFAULT 'UNKNOWN'
        );
    """)
    return conn


def _insert_checkpoint(conn, work_id, attempt_id, fencing_token, tamper=None):
    payload = {
        "contract_version": CHECKPOINT_VERSION,
        "work_id": work_id,
        "execution_attempt_id": attempt_id,
        "fencing_token": fencing_token,
        "work_revision": 0,
        "event_sequence": 0,
        "kind": "BASELINE",
        "manifest": {},
    }
    if tamper:
        tamper(payload)
    sha = digest(payload)
    cp_id = "checkpoint-" + sha
    payload_json = canonical(payload)
    conn.execute(
        "INSERT INTO daio_checkpoints VALUES (?,?,?,?)",
        (cp_id, work_id, sha, payload_json),
    )
    conn.execute(
        "INSERT OR REPLACE INTO daio_backend_control "
        "(work_id, state, policy, manifest, checkpoint_id) VALUES (?,?,?,?,?)",
        (work_id, "QUIESCENT", "[]", "{}", cp_id),
    )
    conn.commit()
    return cp_id, sha


# ---------------------------------------------------------------------------
# 1. Happy path — candidate selection
# ---------------------------------------------------------------------------

def test_4d_candidate_selection_selects_available():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    _observe(reg, "antigravity", "cli", "gemini-2.5-pro")
    cands = [_candidate("antigravity", "cli", "gemini-2.5-pro")]

    ctrl.enroll("work-1", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-1", "attempt-A", 1)

    ctrl.record_capacity_interruption("work-1", "attempt-A", 1, "old-backend")
    ctrl.verify_checkpoint_and_authorize_handoff("work-1", conn)
    ctrl.revoke_current_backend("work-1")

    hr, sel = ctrl.select_and_authorize_backend_b(
        "work-1", cands, "ROUTE_B_ISOLATED", ["FULLY_COMPATIBLE"], now=_now())

    assert hr.success
    assert hr.phase == HandoffPhase.BACKEND_B_AUTHORIZED
    assert sel.selected is not None
    assert sel.reason == "SELECTED"


# ---------------------------------------------------------------------------
# 2. Same work_id, new execution_attempt_id
# ---------------------------------------------------------------------------

def test_4d_new_attempt_id_after_handoff():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    _observe(reg, "p", "b", "m")
    ctrl.enroll("work-2", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-2", "attempt-A", 1)

    ctrl.record_capacity_interruption("work-2", "attempt-A", 1, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-2", conn)
    ctrl.revoke_current_backend("work-2")
    ctrl.select_and_authorize_backend_b(
        "work-2", [_candidate("p", "b", "m")], "ROUTE_B_ISOLATED", [], now=_now())
    result = ctrl.record_backend_b_started("work-2", "attempt-B")

    state = ctrl.get_state("work-2")
    assert state.work_id == "work-2"
    assert state.execution_attempt_id == "attempt-B"
    assert state.phase == HandoffPhase.BACKEND_B_EXECUTING


# ---------------------------------------------------------------------------
# 3. Capacity failure is not an engineering failure
# ---------------------------------------------------------------------------

def test_4d_no_capacity_transitions_to_waiting():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    # No observations — no capacity
    ctrl.enroll("work-3", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-3", "attempt-A", 1)

    ctrl.record_capacity_interruption("work-3", "attempt-A", 1, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-3", conn)
    ctrl.revoke_current_backend("work-3")
    hr, sel = ctrl.select_and_authorize_backend_b(
        "work-3", [], "ROUTE_B_ISOLATED", [], now=_now())

    assert not hr.success
    assert hr.phase == HandoffPhase.WAITING_FOR_EXECUTION_CAPACITY
    assert "WAITING_FOR_EXECUTION_CAPACITY" in hr.reason
    assert sel.reason == "NO_CAPACITY"


# ---------------------------------------------------------------------------
# 4. NEGATIVE: Missing checkpoint fails closed
# ---------------------------------------------------------------------------

def test_4d_missing_checkpoint_fails_closed():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-m", "attempt-A", 1)
    conn = _make_handoff_conn()
    # No checkpoint inserted

    ctrl.record_capacity_interruption("work-m", "attempt-A", 1, "backend-A")
    result = ctrl.verify_checkpoint_and_authorize_handoff("work-m", conn)

    assert not result.success
    assert result.phase == HandoffPhase.FAILED_CLOSED
    assert "MISSING" in result.reason


def test_4d_missing_checkpoint_blocks_backend_b():
    """After a checkpoint failure, backend-B selection must be refused."""
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    _observe(reg, "p", "b", "m")
    ctrl.enroll("work-m2", "attempt-A", 1)
    conn = _make_handoff_conn()

    ctrl.record_capacity_interruption("work-m2", "attempt-A", 1, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-m2", conn)  # fails closed

    # Try to revoke (should also fail because phase is FAILED_CLOSED)
    rev = ctrl.revoke_current_backend("work-m2")
    assert not rev.success
    assert rev.phase == HandoffPhase.FAILED_CLOSED

    # Backend-B selection must be refused
    hr, sel = ctrl.select_and_authorize_backend_b(
        "work-m2", [_candidate("p", "b", "m")], "ROUTE_B_ISOLATED", [], now=_now())
    assert not hr.success
    assert sel.selected is None


# ---------------------------------------------------------------------------
# 5. NEGATIVE: Corrupt checkpoint payload fails closed
# ---------------------------------------------------------------------------

def test_4d_corrupt_checkpoint_payload_fails_closed():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-c", "attempt-A", 1)
    conn = _make_handoff_conn()

    # Insert a checkpoint with corrupted payload (not valid JSON)
    sha = "deadbeef" * 8
    cp_id = "checkpoint-corrupt"
    conn.execute("INSERT INTO daio_checkpoints VALUES (?,?,?,?)",
                 (cp_id, "work-c", sha, "NOT-JSON"))
    conn.execute("INSERT OR REPLACE INTO daio_backend_control "
                 "(work_id,state,policy,manifest,checkpoint_id) VALUES (?,?,?,?,?)",
                 ("work-c", "QUIESCENT", "[]", "{}", cp_id))
    conn.commit()

    ctrl.record_capacity_interruption("work-c", "attempt-A", 1, "backend-A")
    result = ctrl.verify_checkpoint_and_authorize_handoff("work-c", conn)

    assert not result.success
    assert result.phase == HandoffPhase.FAILED_CLOSED
    assert "CORRUPT" in result.reason or "HASH_MISMATCH" in result.reason


# ---------------------------------------------------------------------------
# 6. NEGATIVE: Hash-mismatched checkpoint fails closed
# ---------------------------------------------------------------------------

def test_4d_hash_mismatch_checkpoint_fails_closed():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-h", "attempt-A", 1)
    conn = _make_handoff_conn()

    # Insert checkpoint with wrong stored sha
    payload = {
        "contract_version": CHECKPOINT_VERSION,
        "work_id": "work-h",
        "execution_attempt_id": "attempt-A",
        "fencing_token": 1,
        "work_revision": 0, "event_sequence": 0,
        "kind": "BASELINE", "manifest": {},
    }
    real_sha = digest(payload)
    wrong_sha = "0" * len(real_sha)
    cp_id = "checkpoint-bad"
    conn.execute("INSERT INTO daio_checkpoints VALUES (?,?,?,?)",
                 (cp_id, "work-h", wrong_sha, canonical(payload)))
    conn.execute("INSERT OR REPLACE INTO daio_backend_control "
                 "(work_id,state,policy,manifest,checkpoint_id) VALUES (?,?,?,?,?)",
                 ("work-h", "QUIESCENT", "[]", "{}", cp_id))
    conn.commit()

    ctrl.record_capacity_interruption("work-h", "attempt-A", 1, "backend-A")
    result = ctrl.verify_checkpoint_and_authorize_handoff("work-h", conn)

    assert not result.success
    assert result.phase == HandoffPhase.FAILED_CLOSED
    assert "HASH_MISMATCH" in result.reason


# ---------------------------------------------------------------------------
# 7. NEGATIVE: Wrong work binding fails closed
# ---------------------------------------------------------------------------

def test_4d_wrong_work_id_in_checkpoint_fails_closed():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-ww", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-ww", "attempt-A", 1,
                       tamper=lambda p: p.update({"work_id": "DIFFERENT-WORK"}))

    ctrl.record_capacity_interruption("work-ww", "attempt-A", 1, "backend-A")
    result = ctrl.verify_checkpoint_and_authorize_handoff("work-ww", conn)

    assert not result.success
    assert "HASH_MISMATCH" in result.reason or "WORK_MISMATCH" in result.reason


# ---------------------------------------------------------------------------
# 8. NEGATIVE: Wrong attempt binding fails closed
# ---------------------------------------------------------------------------

def test_4d_wrong_attempt_id_in_checkpoint_fails_closed():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-wa", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-wa", "attempt-A", 1,
                       tamper=lambda p: p.update({"execution_attempt_id": "WRONG-ATTEMPT"}))

    ctrl.record_capacity_interruption("work-wa", "attempt-A", 1, "backend-A")
    result = ctrl.verify_checkpoint_and_authorize_handoff("work-wa", conn)

    assert not result.success
    assert result.phase == HandoffPhase.FAILED_CLOSED
    assert "HASH_MISMATCH" in result.reason or "ATTEMPT_MISMATCH" in result.reason


# ---------------------------------------------------------------------------
# 9. NEGATIVE: Wrong fencing token fails closed
# ---------------------------------------------------------------------------

def test_4d_wrong_fencing_token_in_checkpoint_fails_closed():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-wf", "attempt-A", 5)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-wf", "attempt-A", 5,
                       tamper=lambda p: p.update({"fencing_token": 99}))

    ctrl.record_capacity_interruption("work-wf", "attempt-A", 5, "backend-A")
    result = ctrl.verify_checkpoint_and_authorize_handoff("work-wf", conn)

    assert not result.success
    assert result.phase == HandoffPhase.FAILED_CLOSED
    assert "HASH_MISMATCH" in result.reason or "FENCING_TOKEN_MISMATCH" in result.reason


# ---------------------------------------------------------------------------
# 10. Authority revocation before backend-B
# ---------------------------------------------------------------------------

def test_4d_revocation_before_backend_b_required():
    """Backend-B must be refused if revocation was skipped."""
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    _observe(reg, "p", "b", "m")
    ctrl.enroll("work-rev", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-rev", "attempt-A", 1)

    ctrl.record_capacity_interruption("work-rev", "attempt-A", 1, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-rev", conn)
    # NOTE: intentionally skip revoke_current_backend

    hr, sel = ctrl.select_and_authorize_backend_b(
        "work-rev", [_candidate("p", "b", "m")], "ROUTE_B_ISOLATED", [], now=_now())

    assert not hr.success
    assert sel.selected is None
    assert "AUTHORITY_REVOKED" in hr.reason


# ---------------------------------------------------------------------------
# 11. Fencing token advances on backend-B authorization
# ---------------------------------------------------------------------------

def test_4d_fencing_advances_on_backend_b():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    _observe(reg, "p", "b", "m")
    initial_fence = 3
    ctrl.enroll("work-fence", "attempt-A", initial_fence)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-fence", "attempt-A", initial_fence)

    ctrl.record_capacity_interruption("work-fence", "attempt-A", initial_fence, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-fence", conn)
    ctrl.revoke_current_backend("work-fence")
    hr, _ = ctrl.select_and_authorize_backend_b(
        "work-fence", [_candidate("p", "b", "m")], "ROUTE_B_ISOLATED", [], now=_now())

    assert hr.fencing_token == initial_fence + 1
    state = ctrl.get_state("work-fence")
    assert state.fencing_token == initial_fence + 1


# ---------------------------------------------------------------------------
# 12. TOCTOU: capacity exhausted between checkpoint and selection
# ---------------------------------------------------------------------------

def test_4d_toctou_no_capacity_at_backend_b_selection():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    # Initially available
    _observe(reg, "p", "b", "m")
    ctrl.enroll("work-toctou", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-toctou", "attempt-A", 1)

    ctrl.record_capacity_interruption("work-toctou", "attempt-A", 1, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-toctou", conn)
    ctrl.revoke_current_backend("work-toctou")

    # Capacity exhausted between revocation and backend-B selection
    _observe(reg, "p", "b", "m", state=CapacityState.CAPACITY_EXHAUSTED)

    hr, sel = ctrl.select_and_authorize_backend_b(
        "work-toctou", [_candidate("p", "b", "m")], "ROUTE_B_ISOLATED", [], now=_now())

    assert not hr.success
    assert hr.phase == HandoffPhase.WAITING_FOR_EXECUTION_CAPACITY


# ---------------------------------------------------------------------------
# 13. Restart-safe: controller reload from SQLite
# ---------------------------------------------------------------------------

def test_4d_controller_state_survives_restart():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-restart", "attempt-A", 7)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-restart", "attempt-A", 7)

    ctrl.record_capacity_interruption("work-restart", "attempt-A", 7, "backend-A")
    ctrl.verify_checkpoint_and_authorize_handoff("work-restart", conn)
    ctrl.revoke_current_backend("work-restart")

    # Simulate controller restart by creating a new instance from the same db
    ctrl2 = _make_controller(reg, db)
    state = ctrl2.get_state("work-restart")

    assert state is not None
    assert state.work_id == "work-restart"
    assert state.phase == HandoffPhase.AUTHORITY_REVOKED
    assert state.revocation_recorded is True
    assert state.fencing_token == 7


# ---------------------------------------------------------------------------
# 14. Stale publication rejection — wrong attempt
# ---------------------------------------------------------------------------

def test_4d_stale_publication_wrong_attempt_rejected():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-stale", "attempt-A", 1)
    assert ctrl.is_stale_publication("work-stale", "attempt-WRONG", 1) is True
    assert ctrl.is_stale_publication("work-stale", "attempt-A", 1) is False


def test_4d_stale_publication_wrong_fencing_rejected():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-stale2", "attempt-A", 5)
    assert ctrl.is_stale_publication("work-stale2", "attempt-A", 99) is True
    assert ctrl.is_stale_publication("work-stale2", "attempt-A", 5) is False


def test_4d_stale_publication_unknown_work_rejected():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    assert ctrl.is_stale_publication("no-such-work", "attempt-X", 1) is True


# ---------------------------------------------------------------------------
# 15. Full state machine happy path
# ---------------------------------------------------------------------------

def test_4d_full_state_machine_happy_path():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)
    _observe(reg, "p", "b", "m")

    ctrl.enroll("work-full", "attempt-A", 1)
    conn = _make_handoff_conn()
    _insert_checkpoint(conn, "work-full", "attempt-A", 1)

    r1 = ctrl.record_capacity_interruption("work-full", "attempt-A", 1, "backend-A")
    assert r1.success and r1.phase == HandoffPhase.CAPACITY_INTERRUPTED

    r2 = ctrl.verify_checkpoint_and_authorize_handoff("work-full", conn)
    assert r2.success and r2.phase == HandoffPhase.CHECKPOINT_VERIFIED

    r3 = ctrl.revoke_current_backend("work-full")
    assert r3.success and r3.phase == HandoffPhase.AUTHORITY_REVOKED

    r4, sel = ctrl.select_and_authorize_backend_b(
        "work-full", [_candidate("p", "b", "m")], "ROUTE_B_ISOLATED", [], now=_now())
    assert r4.success and r4.phase == HandoffPhase.BACKEND_B_AUTHORIZED
    assert sel.selected is not None

    r5 = ctrl.record_backend_b_started("work-full", "attempt-B")
    assert r5.success and r5.phase == HandoffPhase.BACKEND_B_EXECUTING

    r6 = ctrl.record_completion("work-full")
    assert r6.success and r6.phase == HandoffPhase.COMPLETED


# ---------------------------------------------------------------------------
# 16. Stale interruption report rejected
# ---------------------------------------------------------------------------

def test_4d_stale_attempt_interruption_rejected():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-si", "attempt-A", 3)
    result = ctrl.record_capacity_interruption("work-si", "attempt-WRONG", 3, "backend-A")
    assert not result.success
    assert result.reason == "STALE_ATTEMPT_ID"


def test_4d_stale_fencing_token_interruption_rejected():
    db = _fresh_db()
    reg = _make_capacity_registry(db)
    ctrl = _make_controller(reg, db)

    ctrl.enroll("work-sft", "attempt-A", 3)
    result = ctrl.record_capacity_interruption("work-sft", "attempt-A", 99, "backend-A")
    assert not result.success
    assert result.reason == "STALE_FENCING_TOKEN"
