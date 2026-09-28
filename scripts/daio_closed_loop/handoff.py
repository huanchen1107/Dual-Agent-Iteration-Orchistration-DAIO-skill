"""Opt-in C1.4 safety controller. No backend discovery, launch, or automatic fallback.

Only the trusted controller calls this API. Backends receive a bounded handoff
and return acknowledgements/proposals; they never receive database access.
Legacy queue, decision and executor paths must reject enrolled work.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import datetime
import json
import uuid

from .handoff_contract import (
    CONTRACT_VERSION, CHECKPOINT_VERSION, BackendIdentity, CAPACITY_OUTCOMES,
    ExecutionOutcome, Outcome, PublicationToken, Reconstruction, ReconstructionAck,
    SafetyError, StaleExecution, TestStatus, canonical, digest, hash_value,
    identifier, require_admission,
)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


class DurableHandoff:
    """Transactional safety foundation; all publications consume a current token."""

    def __init__(self, store):
        self.store = store
        with self._transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS daio_backend_control (
                    work_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                    policy TEXT NOT NULL, manifest TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL, authorization_id TEXT,
                    authorized_backend TEXT, quiescence TEXT NOT NULL DEFAULT 'UNKNOWN'
                );
                CREATE TABLE IF NOT EXISTS daio_backend_attempts (
                    execution_attempt_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    previous_attempt_id TEXT, fencing_token INTEGER NOT NULL,
                    backend TEXT NOT NULL, authorization_id TEXT NOT NULL,
                    started_at TEXT NOT NULL, outcome TEXT, tests TEXT,
                    quiescence TEXT NOT NULL DEFAULT 'UNKNOWN', receipt_id TEXT, quiescence_method TEXT,
                    reconstruction_sha256 TEXT, result_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS daio_backend_authorizations (
                    authorization_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    backend TEXT NOT NULL, checkpoint_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daio_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daio_work_events (
                    work_id TEXT NOT NULL, event_sequence INTEGER NOT NULL,
                    work_revision INTEGER NOT NULL, execution_attempt_id TEXT,
                    fencing_token INTEGER NOT NULL, event TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(work_id, event_sequence)
                );
                CREATE TRIGGER IF NOT EXISTS daio_checkpoint_no_update
                BEFORE UPDATE ON daio_checkpoints BEGIN SELECT RAISE(ABORT, 'immutable checkpoint'); END;
                CREATE TRIGGER IF NOT EXISTS daio_checkpoint_no_delete
                BEFORE DELETE ON daio_checkpoints BEGIN SELECT RAISE(ABORT, 'immutable checkpoint'); END;
                CREATE TRIGGER IF NOT EXISTS daio_event_no_update
                BEFORE UPDATE ON daio_work_events BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
                CREATE TRIGGER IF NOT EXISTS daio_event_no_delete
                BEFORE DELETE ON daio_work_events BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
            """)

    @contextmanager
    def _transaction(self):
        conn = self.store._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            if not self.store._shared_conn:
                conn.close()

    @staticmethod
    def _token(row):
        return PublicationToken(row['work_id'], row['work_revision'], row['event_sequence'],
                                row['execution_attempt_id'], row['fencing_token'])

    def token(self, work_id):
        conn = self.store._get_connection()
        try:
            row = conn.execute("SELECT * FROM daio_work_items WHERE work_id=?", (work_id,)).fetchone()
            if not row or row['handoff_contract'] != CONTRACT_VERSION:
                raise SafetyError("Work is not enrolled")
            return self._token(row)
        finally:
            if not self.store._shared_conn:
                conn.close()

    def _validate(self, conn, token, live=False):
        row = conn.execute("SELECT * FROM daio_work_items WHERE work_id=?", (token.work_id,)).fetchone()
        if not row or row['handoff_contract'] != CONTRACT_VERSION or self._token(row) != token:
            raise StaleExecution("STALE_EXECUTION: revision/sequence/attempt/fence mismatch")
        require_admission(self.store._row_to_work_item(row))
        if live and (not row['lease_expires_at'] or
                     datetime.datetime.fromisoformat(row['lease_expires_at']) <= utcnow()):
            raise StaleExecution("STALE_EXECUTION: expired lease")
        control = conn.execute("SELECT * FROM daio_backend_control WHERE work_id=?", (token.work_id,)).fetchone()
        if not control:
            raise SafetyError("Missing control record")
        return row, control

    def _event(self, conn, work_id, event):
        now = utcnow().isoformat()
        conn.execute("""UPDATE daio_work_items SET work_revision=work_revision+1,
                     event_sequence=event_sequence+1, updated_at=? WHERE work_id=?""", (now, work_id))
        row = conn.execute("SELECT * FROM daio_work_items WHERE work_id=?", (work_id,)).fetchone()
        conn.execute("INSERT INTO daio_work_events VALUES(?,?,?,?,?,?,?)",
                     (work_id, row['event_sequence'], row['work_revision'], row['execution_attempt_id'],
                      row['fencing_token'], event, now))
        return self._token(row)

    def _checkpoint(self, conn, row, manifest, kind):
        payload = dict(contract_version=CHECKPOINT_VERSION, work_id=row['work_id'],
                       execution_attempt_id=row['execution_attempt_id'], fencing_token=row['fencing_token'],
                       work_revision=row['work_revision'], event_sequence=row['event_sequence'],
                       kind=kind, manifest=manifest)
        sha = digest(payload)
        checkpoint_id = 'checkpoint-' + sha
        conn.execute("INSERT INTO daio_checkpoints VALUES(?,?,?,?)",
                     (checkpoint_id, row['work_id'], sha, canonical(payload)))
        return checkpoint_id

    def enroll(self, work_id, baseline: Reconstruction, authorized_backends: tuple[str, ...]):
        manifest = baseline.manifest()
        allowed = {'antigravity_cli', 'codex_cli', 'codex_ide_manual'}
        if not authorized_backends or not set(authorized_backends) <= allowed:
            raise SafetyError("Explicit backend allowlist required")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM daio_work_items WHERE work_id=?", (work_id,)).fetchone()
            if not row:
                raise SafetyError("Work not found")
            require_admission(self.store._row_to_work_item(row))
            if row['handoff_contract'] or row['lease_id'] or row['execution_attempt_id']:
                raise SafetyError("Cannot enroll previously claimed work")
            if row['assigned_role'] != 'ENGINEERING_EXECUTION' or row['status'] != 'QUEUED':
                raise SafetyError("Only approved queued engineering work may enroll")
            checkpoint_id = self._checkpoint(conn, row, manifest, 'BASELINE')
            conn.execute("UPDATE daio_work_items SET handoff_contract=? WHERE work_id=?", (CONTRACT_VERSION, work_id))
            conn.execute("""INSERT INTO daio_backend_control(work_id,state,policy,manifest,checkpoint_id)
                            VALUES(?,?,?,?,?)""", (work_id, 'READY', canonical(sorted(set(authorized_backends))),
                                                  canonical(manifest), checkpoint_id))
            return self._event(conn, work_id, 'ENROLLED')

    def authorize_backend(self, token, backend: BackendIdentity, authorization_id: str):
        """Explicit trusted policy decision. Never called as an automatic fallback."""
        backend.validate()
        identifier(authorization_id)
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token)
            if ctl['state'] not in {'READY', 'CHECKPOINTED'}:
                raise SafetyError("Backend replacement requires a published checkpoint")
            if backend.backend_id not in json.loads(ctl['policy']):
                raise SafetyError("Backend not authorized by work policy")
            if ctl['state'] == 'CHECKPOINTED' and ctl['quiescence'] != 'TERMINATED':
                raise SafetyError("Prior termination is UNKNOWN")
            encoded = canonical(asdict(backend))
            conn.execute("INSERT INTO daio_backend_authorizations VALUES(?,?,?,?)",
                         (authorization_id, token.work_id, encoded, ctl['checkpoint_id']))
            conn.execute("""UPDATE daio_backend_control SET state='AUTHORIZED', authorization_id=?,
                         authorized_backend=? WHERE work_id=?""", (authorization_id, encoded, token.work_id))
            return self._event(conn, token.work_id, 'BACKEND_AUTHORIZED')

    def begin_attempt(self, token, worker_id: str, ttl_seconds=300):
        identifier(worker_id)
        if not 1 <= ttl_seconds <= 3600:
            raise SafetyError("Invalid lease duration")
        with self._transaction() as conn:
            row, ctl = self._validate(conn, token)
            if ctl['state'] != 'AUTHORIZED':
                raise SafetyError("Explicit backend authorization required")
            backend = json.loads(ctl['authorized_backend'])
            if backend['transport'] != 'CLI':
                raise SafetyError("Manual IDE lifecycle is not automatable in Phase 1")
            attempt = 'attempt-' + uuid.uuid4().hex
            fence = row['fencing_token'] + 1
            now = utcnow()
            conn.execute("""INSERT INTO daio_backend_attempts(execution_attempt_id,work_id,previous_attempt_id,
                         fencing_token,backend,authorization_id,started_at) VALUES(?,?,?,?,?,?,?)""",
                         (attempt, token.work_id, row['execution_attempt_id'], fence, ctl['authorized_backend'],
                          ctl['authorization_id'], now.isoformat()))
            conn.execute("""UPDATE daio_work_items SET execution_attempt_id=?, fencing_token=?,
                         status='IN_PROGRESS', lease_id=?, lease_expires_at=?, claimed_by=?,
                         execution_started_at=?, last_heartbeat_at=? WHERE work_id=?""",
                         (attempt, fence, 'lease-' + uuid.uuid4().hex,
                          (now + datetime.timedelta(seconds=ttl_seconds)).isoformat(), worker_id,
                          now.isoformat(), now.isoformat(), token.work_id))
            conn.execute("UPDATE daio_backend_control SET state='RECONSTRUCTION_REQUIRED', quiescence='UNKNOWN' WHERE work_id=?",
                         (token.work_id,))
            return self._event(conn, token.work_id, 'ATTEMPT_CREATED')

    def handoff(self, token):
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token, live=True)
            cp = conn.execute("SELECT * FROM daio_checkpoints WHERE checkpoint_id=?", (ctl['checkpoint_id'],)).fetchone()
            payload = json.loads(cp['payload'])
            if digest(payload) != cp['sha256']:
                raise SafetyError("Checkpoint integrity failure")
            return dict(contract_version=CONTRACT_VERSION, token=asdict(token),
                        checkpoint_id=cp['checkpoint_id'], checkpoint_sha256=cp['sha256'],
                        manifest=payload['manifest'], backend=json.loads(ctl['authorized_backend']))

    def acknowledge(self, ack: ReconstructionAck, observe):
        """observe() is trusted local measurement, never the backend's own assertion."""
        with self._transaction() as conn:
            _, ctl = self._validate(conn, ack.token, live=True)
            if ctl['state'] != 'RECONSTRUCTION_REQUIRED':
                raise SafetyError("Reconstruction not pending")
            cp = conn.execute("SELECT * FROM daio_checkpoints WHERE checkpoint_id=?", (ctl['checkpoint_id'],)).fetchone()
            payload = json.loads(cp['payload'])
            expected = payload['manifest']
            observed = observe().manifest()
            if (ack.checkpoint_id != cp['checkpoint_id'] or ack.checkpoint_sha256 != cp['sha256']
                    or digest(payload) != cp['sha256'] or ack.manifest_sha256 != digest(expected)
                    or observed != expected):
                raise SafetyError("Reconstruction mismatch")
            conn.execute("UPDATE daio_backend_attempts SET reconstruction_sha256=? WHERE execution_attempt_id=?",
                         (ack.manifest_sha256, ack.token.execution_attempt_id))
            conn.execute("UPDATE daio_backend_control SET state='PREPARED' WHERE work_id=?", (ack.token.work_id,))
            return self._event(conn, ack.token.work_id, 'RECONSTRUCTION_VALIDATED')

    def start_execution(self, token, observe):
        """Recheck workspace after acknowledgement; return authority for one proposal."""
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token, live=True)
            if ctl['state'] != 'PREPARED' or observe().manifest() != json.loads(ctl['manifest']):
                raise SafetyError("Execution requires current verified reconstruction")
            conn.execute("UPDATE daio_backend_control SET state='EXECUTING' WHERE work_id=?", (token.work_id,))
            return self._event(conn, token.work_id, 'EXECUTION_STARTED')

    def renew(self, token, ttl_seconds=300):
        if not 1 <= ttl_seconds <= 3600:
            raise SafetyError("Invalid lease duration")
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token, live=True)
            if ctl['state'] not in {'RECONSTRUCTION_REQUIRED', 'PREPARED', 'EXECUTING', 'INTERRUPTED'}:
                raise SafetyError("No active execution lease")
            now = utcnow()
            conn.execute("UPDATE daio_work_items SET lease_expires_at=?,last_heartbeat_at=? WHERE work_id=?",
                         ((now + datetime.timedelta(seconds=ttl_seconds)).isoformat(), now.isoformat(), token.work_id))
            return self._event(conn, token.work_id, 'LEASE_RENEWED')

    def publish_outcome(self, token, result: ExecutionOutcome, result_sha256=None):
        result.validate()
        if result_sha256 is not None:
            hash_value(result_sha256)
        if result.outcome == Outcome.SUCCESS and result_sha256 is None:
            raise SafetyError("Successful proposal requires artifact digest")
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token, live=True)
            if ctl['state'] != 'EXECUTING':
                raise SafetyError("No authorized execution")
            state = 'INTERRUPTED' if result.outcome in CAPACITY_OUTCOMES else 'RESULT_RECORDED'
            status = 'WAITING_FOR_EXECUTION_CAPACITY' if result.outcome in CAPACITY_OUTCOMES else 'AWAITING_REVIEW'
            if result.outcome == Outcome.HUMAN_GATE_REQUIRED:
                status = 'HUMAN_GATE_REQUIRED'
            elif result.outcome == Outcome.SUPERSEDED_WORK:
                status = 'SUPERSEDED'
            conn.execute("UPDATE daio_backend_control SET state=? WHERE work_id=?", (state, token.work_id))
            conn.execute("UPDATE daio_work_items SET status=? WHERE work_id=?", (status, token.work_id))
            conn.execute("UPDATE daio_backend_attempts SET outcome=?,tests=?,result_sha256=? WHERE execution_attempt_id=?",
                         (result.outcome.value, result.tests.value, result_sha256, token.execution_attempt_id))
            return self._event(conn, token.work_id, result.outcome.value)

    def confirm_quiescence(self, token, verify_termination):
        """Trusted lifecycle verifier returns an attempt-bound receipt; UNKNOWN fails closed.

        Expired leases may record a termination receipt with the exact current
        token, but may never publish an execution result or renew expired authority.
        """
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token)
            if ctl['state'] != 'INTERRUPTED':
                raise SafetyError("No capacity interruption awaiting quiescence")
            receipt = verify_termination(token.execution_attempt_id)
            receipt.validate(token.execution_attempt_id)
            conn.execute("UPDATE daio_backend_control SET state='QUIESCENT',quiescence='TERMINATED' WHERE work_id=?", (token.work_id,))
            conn.execute("UPDATE daio_backend_attempts SET quiescence='TERMINATED',receipt_id=?,quiescence_method=? WHERE execution_attempt_id=?",
                         (receipt.receipt_id, receipt.method, token.execution_attempt_id))
            conn.execute("UPDATE daio_work_items SET lease_id=NULL,lease_expires_at=NULL,claimed_by=NULL WHERE work_id=?", (token.work_id,))
            return self._event(conn, token.work_id, 'QUIESCENCE_VERIFIED')

    def publish_checkpoint(self, token, observe):
        with self._transaction() as conn:
            row, ctl = self._validate(conn, token)
            if ctl['state'] != 'QUIESCENT' or ctl['quiescence'] != 'TERMINATED':
                raise SafetyError("Checkpoint requires verified quiescence")
            manifest = observe().manifest()
            if canonical(manifest) != ctl['manifest']:
                raise SafetyError("Workspace changed during proposal-only execution; reconcile manually")
            checkpoint_id = self._checkpoint(conn, row, manifest, 'CAPACITY_INTERRUPTION')
            conn.execute("UPDATE daio_backend_control SET state='CHECKPOINTED',checkpoint_id=? WHERE work_id=?",
                         (checkpoint_id, token.work_id))
            new_token = self._event(conn, token.work_id, 'CHECKPOINT_PUBLISHED')
            return new_token, checkpoint_id

    def complete(self, token, review_authorization_id, observe, verify_termination):
        """Trusted review accepts a proposal-only deliverable, never applies edits.

        Completion requires successful result provenance and verified termination.
        A current token is sufficient after result publication; an expired lease
        grants no further backend execution authority.
        """
        identifier(review_authorization_id)
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token)
            attempt = conn.execute("SELECT * FROM daio_backend_attempts WHERE execution_attempt_id=?",
                                   (token.execution_attempt_id,)).fetchone()
            if (ctl['state'] != 'RESULT_RECORDED' or not attempt
                    or attempt['outcome'] != Outcome.SUCCESS.value or not attempt['result_sha256']):
                raise SafetyError("Completion requires a successful proposal awaiting review")
            if observe().manifest() != json.loads(ctl['manifest']):
                raise SafetyError("Completion workspace measurement mismatch")
            receipt = verify_termination(token.execution_attempt_id)
            receipt.validate(token.execution_attempt_id)
            conn.execute("INSERT INTO daio_backend_authorizations VALUES(?,?,?,?)",
                         (review_authorization_id, token.work_id, attempt['backend'], ctl['checkpoint_id']))
            conn.execute("UPDATE daio_backend_attempts SET quiescence='TERMINATED',receipt_id=?,quiescence_method=? WHERE execution_attempt_id=?",
                         (receipt.receipt_id, receipt.method, token.execution_attempt_id))
            conn.execute("UPDATE daio_backend_control SET state='COMPLETED',quiescence='TERMINATED',authorization_id=? WHERE work_id=?",
                         (review_authorization_id, token.work_id))
            conn.execute("""UPDATE daio_work_items SET status='COMPLETED',fencing_token=fencing_token+1,
                         lease_id=NULL,lease_expires_at=NULL,claimed_by=NULL WHERE work_id=?""", (token.work_id,))
            return self._event(conn, token.work_id, 'COMPLETED')

    def stop(self, token, status='STOP'):
        """Trusted policy revocation invalidates authority without claiming process termination."""
        if status not in {'STOP', 'FROZEN', 'SUPERSEDED', 'HUMAN_GATE_REQUIRED'}:
            raise SafetyError("Invalid stop state")
        with self._transaction() as conn:
            self._validate(conn, token)
            conn.execute("UPDATE daio_work_items SET status=?,fencing_token=fencing_token+1 WHERE work_id=?",
                         (status, token.work_id))
            conn.execute("UPDATE daio_backend_control SET state=? WHERE work_id=?", (status, token.work_id))
            return self._event(conn, token.work_id, status)
