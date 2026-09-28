"""Opt-in disposable Route-B integration. Trusted-host API, not a backend RPC.

One controller token and repository lock govern every authority transition. The
host must independently enforce Phase-3B1 isolation; this module does not sandbox
or launch a backend. UNKNOWN lifecycle is never promoted to quiescence.
"""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path

from .handoff import DurableHandoff
from .handoff_contract import (
    PublicationToken, SafetyError, StaleExecution, canonical,
    digest, identifier,
)
from .store import SqliteDAIOWorkStore
from .trusted_writer import TrustedWriter

UNIFIED_VERSION = 'daio-handoff-writer/v1'


class ControllerWriter(TrustedWriter):
    """All authority queries use the controller's live transaction, never a cache."""
    _authority_mode = UNIFIED_VERSION

    def __init__(self, repository, state_dir, controller):
        self.controller = controller
        super().__init__(repository, state_dir)
        with self._lock(), self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS resolutions (
                  approval_id TEXT PRIMARY KEY, apply_id TEXT NOT NULL, observed_sha256 TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_resolution_update BEFORE UPDATE ON resolutions
                  BEGIN SELECT RAISE(ABORT,'immutable resolution approval'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_resolution_delete BEFORE DELETE ON resolutions
                  BEGIN SELECT RAISE(ABORT,'immutable resolution approval'); END;
            """)

    def _initialize_authority_schema(self, conn):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('work','events')").fetchone():
            raise SafetyError('Standalone authority cannot be imported')

    def register(self, *args, **kwargs):
        raise SafetyError('Enroll through UnifiedHandoff')

    def authority_transition(self, *args, **kwargs):
        raise SafetyError('Transition through UnifiedHandoff')

    def token(self, work_id):
        return self.controller.token(work_id)

    def _current(self, conn, token):
        _, ctl = self.controller._validate(conn, token)
        if ctl['authority'] != 'AUTHORIZED' or ctl['state'] != 'EXECUTING':
            raise StaleExecution('No current mutation authority')
        scope = conn.execute('SELECT * FROM daio_writer_scope WHERE work_id=?', (token.work_id,)).fetchone()
        if not scope:
            raise SafetyError('Missing repository scope')
        return scope

    def _admit(self, conn, token):
        self.controller._validate(conn, token, live=True)
        return self._current(conn, token)

    def _event(self, conn, work_id, kind):
        return self.controller._event(conn, work_id, kind)

    def resolve_forward(self, apply_id, approval_id, crash_hook=lambda stage: None):
        """Explicit host-approved roll-forward, only from exact before/after bytes.

        Never removes unexplained files or rebases. A crash requires a fresh
        approval and measurement; already accepted after-images are not replayed.
        """
        identifier(approval_id)
        with self._lock():
            with self._db() as conn:
                pending = conn.execute("SELECT * FROM applies WHERE state!='COMMITTED'").fetchall()
                if len(pending) != 1 or pending[0]['apply_id'] != apply_id:
                    raise SafetyError('Exactly one unresolved journal required')
                journal = pending[0]
                token = PublicationToken(**json.loads(journal['token']))
                self._current(conn, token)  # Recovery, not new lease admission.
                artifact = conn.execute('SELECT * FROM artifacts WHERE artifact_id=?', (journal['artifact_id'],)).fetchone()
                self._sealed(conn, journal['artifact_id'], artifact['sha256'], token)
                before, after = json.loads(journal['before_image']), json.loads(journal['after_image'])
                baseline = json.loads(journal['baseline'])
                observed = self._observed_baseline()
                if any(observed[k] != baseline[k] for k in ('identity', 'head', 'index')):
                    raise SafetyError('BLOCKED: repository identity/HEAD/index drift')
                current = observed['tree']
                if set(current) != set(before) or any(current[p] not in (before[p], after[p]) for p in before):
                    raise SafetyError('BLOCKED: unexplained bytes or staging remnants')
                conn.execute('INSERT INTO approvals VALUES(?)', (approval_id,))
                conn.execute('INSERT INTO resolutions VALUES(?,?,?)', (approval_id, apply_id, digest(observed)))
            self._transition(apply_id, 'APPLYING')
            crash_hook('RESOLUTION_ADMITTED')
            try:
                for i, path in enumerate(sorted(before)):
                    if current[path] != after[path]:
                        self._replace(path, after[path], before[path], apply_id, lambda: None)
                        crash_hook('RESOLUTION_FILE_' + str(i))
                self._transition(apply_id, 'APPLIED')
                return self._commit(apply_id)
            except Exception:
                self._transition(apply_id, 'RECONCILIATION_REQUIRED')
                raise


class UnifiedHandoff(DurableHandoff):
    contract_version = UNIFIED_VERSION

    def __init__(self, repository, state_dir):
        self._initializing = True
        self.writer = ControllerWriter(repository, state_dir, self)
        # Initialization is serialized too, including schema setup after restart.
        with self.writer._lock():
            store = SqliteDAIOWorkStore(str(self.writer.db))
        super().__init__(store)
        with self._transaction() as conn:
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(daio_backend_control)')}
            if 'authority' not in columns:
                conn.execute("ALTER TABLE daio_backend_control ADD COLUMN authority TEXT NOT NULL DEFAULT 'NEVER_GRANTED'")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS daio_writer_scope (
                  work_id TEXT PRIMARY KEY, baseline TEXT NOT NULL, policy TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_writer_policy BEFORE UPDATE OF policy ON daio_writer_scope
                  BEGIN SELECT RAISE(ABORT,'immutable scope'); END;
            """)
        self._initializing = False

    @contextmanager
    def _transaction(self):
        with self.writer._lock(), self.writer._db() as conn:
            if not self._initializing:
                self.writer._no_pending(conn)
            yield conn

    def _event(self, conn, work_id, event):
        if event == 'ENROLLED':
            baseline, policy = self._enrollment
            row = conn.execute('SELECT project_root FROM daio_work_items WHERE work_id=?', (work_id,)).fetchone()
            if Path(row['project_root']).absolute() != self.writer.repo:
                raise SafetyError('Work repository binding mismatch')
            if self.writer._observed_baseline() != baseline:
                raise SafetyError("Enrollment baseline changed")
            conn.execute('INSERT INTO daio_writer_scope VALUES(?,?,?)', (work_id, canonical(baseline), canonical(policy)))
        elif event == 'ATTEMPT_CREATED':
            conn.execute("UPDATE daio_backend_control SET authority='NEVER_GRANTED' WHERE work_id=?", (work_id,))
        elif event == 'EXECUTION_STARTED':
            conn.execute("UPDATE daio_backend_control SET authority='AUTHORIZED' WHERE work_id=?", (work_id,))
        elif event == 'APPLY_COMMITTED':
            journal = conn.execute("SELECT * FROM applies WHERE work_id=? AND state='COMMITTED' ORDER BY rowid DESC LIMIT 1", (work_id,)).fetchone()
            baseline = json.loads(journal['baseline'])
            baseline['tree'] = json.loads(journal['after_image'])
            conn.execute('UPDATE daio_writer_scope SET baseline=? WHERE work_id=?', (canonical(baseline), work_id))
            artifact = conn.execute('SELECT * FROM artifacts WHERE artifact_id=?', (journal['artifact_id'],)).fetchone()
            attempt = json.loads(journal['token'])['execution_attempt_id']
            conn.execute("UPDATE daio_backend_attempts SET outcome='SUCCESS',tests='NOT_RUN',result_sha256=? WHERE execution_attempt_id=?", (artifact['sha256'], attempt))
        elif event in {'STOP', 'FROZEN', 'SUPERSEDED', 'HUMAN_GATE_REQUIRED'}:
            conn.execute("UPDATE daio_backend_control SET authority='REVOKED' WHERE work_id=?", (work_id,))
        return super()._event(conn, work_id, event)

    def enroll(self, work_id, baseline, authorized_backends, *, allowed, frozen=()):
        for path in (*allowed, *frozen):
            self.writer._path(path)
        # super.enroll uses the same lock; perform baseline measurements inside it.
        original = baseline
        controller = self
        class MeasuredBaseline:
            def manifest(self):
                measured = controller.writer._baseline()
                if not allowed or not set(allowed) <= set(measured['tree']):
                    raise SafetyError('Explicit existing-file scope required')
                policy = {'allowed': list(allowed), 'frozen': list(frozen)}
                manifest = original.manifest()
                if (manifest['head_sha'] != measured['head'] or manifest['workspace_sha256'] != digest(measured['tree'])
                        or manifest['scope_sha256'] != digest(list(allowed)) or manifest['frozen_sha256'] != digest(list(frozen))):
                    raise SafetyError('Enrollment manifest does not bind measured repository/scope')
                controller._enrollment = measured, policy
                return manifest
        # Measurement, scope publication and enrollment share one transaction.
        return super().enroll(work_id, MeasuredBaseline(), authorized_backends)

    def authorize_backend(self, token, backend, authorization_id):
        backend.validate(); identifier(authorization_id)
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token)
            if ctl['state'] not in {'READY', 'CHECKPOINTED'} or ctl['authority'] not in {'NEVER_GRANTED', 'REVOKED'}:
                raise SafetyError('Explicit revocation and checkpoint required')
            if backend.backend_id not in json.loads(ctl['policy']):
                raise SafetyError('Backend outside approved policy')
            if conn.execute("SELECT 1 FROM daio_backend_control WHERE work_id!=? AND state IN ('AUTHORIZED','RECONSTRUCTION_REQUIRED','PREPARED','EXECUTING')", (token.work_id,)).fetchone():
                raise SafetyError('Another work owns this repository')
            encoded = canonical(asdict(backend))
            conn.execute('INSERT INTO daio_backend_authorizations VALUES(?,?,?,?)', (authorization_id, token.work_id, encoded, ctl['checkpoint_id']))
            conn.execute("UPDATE daio_backend_control SET state='AUTHORIZED',authorization_id=?,authorized_backend=? WHERE work_id=?", (authorization_id, encoded, token.work_id))
            return self._event(conn, token.work_id, 'BACKEND_AUTHORIZED')

    def acknowledge(self, ack, observe):
        return super().acknowledge(ack, self._checked_observe(ack.token.work_id, observe))

    def start_execution(self, token, observe):
        return super().start_execution(token, self._checked_observe(token.work_id, observe))

    def _checked_observe(self, work_id, observe):
        def checked():
            measurement = observe()
            conn = self.store._get_connection()
            try:
                scope = conn.execute('SELECT * FROM daio_writer_scope WHERE work_id=?', (work_id,)).fetchone()
                baseline = json.loads(scope['baseline'])
                if self.writer._observed_baseline() != baseline or measurement.workspace_sha256 != digest(baseline['tree']):
                    raise SafetyError('Trusted repository reconstruction drift')
            finally:
                conn.close()
            return measurement
        return checked

    def revoke(self, token, approval_id):
        identifier(approval_id)
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token)
            if ctl['authority'] == 'REVOKED':
                raise SafetyError('Already revoked')
            conn.execute('INSERT INTO approvals VALUES(?)', (approval_id,))
            conn.execute("UPDATE daio_backend_control SET authority='REVOKED',state='REVOKED' WHERE work_id=?", (token.work_id,))
            conn.execute('UPDATE daio_work_items SET fencing_token=fencing_token+1,lease_id=NULL,lease_expires_at=NULL,claimed_by=NULL WHERE work_id=?', (token.work_id,))
            return self._event(conn, token.work_id, 'AUTHORITY_REVOKED')

    def publish_checkpoint(self, token, observe):
        with self._transaction() as conn:
            row, ctl = self._validate(conn, token)
            if ctl['authority'] != 'REVOKED' or ctl['state'] != 'REVOKED':
                raise SafetyError('Checkpoint requires positive authority revocation')
            manifest = self._checked_observe(token.work_id, observe)().manifest()
            prior = json.loads(ctl['manifest'])
            for key in ('repository_id', 'head_sha', 'policy_sha256', 'scope_sha256', 'frozen_sha256'):
                if manifest[key] != prior[key]:
                    raise SafetyError('Checkpoint cannot change repository/policy identity')
            completed = manifest['completed_steps']
            if completed[:len(prior['completed_steps'])] != prior['completed_steps']:
                raise SafetyError('Completed steps cannot regress')
            advanced = completed != prior['completed_steps'] or manifest['next_step'] != prior['next_step']
            if advanced:
                if completed != prior['completed_steps'] + [prior['next_step']]:
                    raise SafetyError('Only next incomplete step may advance')
                self._accepted_apply(conn, token)
            cp = self._checkpoint(conn, row, manifest, 'AUTHORITY_HANDOFF')
            conn.execute("UPDATE daio_backend_control SET state='CHECKPOINTED',checkpoint_id=?,manifest=? WHERE work_id=?", (cp, canonical(manifest), token.work_id))
            return self._event(conn, token.work_id, 'CHECKPOINT_PUBLISHED'), cp

    def _accepted_apply(self, conn, token):
        artifact = conn.execute('SELECT * FROM artifacts WHERE work_id=? ORDER BY rowid DESC LIMIT 1', (token.work_id,)).fetchone()
        journal = conn.execute('SELECT * FROM applies WHERE artifact_id=?', (artifact['artifact_id'],)).fetchone() if artifact else None
        if (not journal or journal['state'] != 'COMMITTED'
                or json.loads(artifact['token'])['execution_attempt_id'] != token.execution_attempt_id):
            raise SafetyError('Current accepted proposal lacks a known committed effect')
        # Content integrity and actual authoritative bytes remain part of completion.
        self.writer._sealed(conn, artifact['artifact_id'], artifact['sha256'], PublicationToken(**json.loads(artifact['token'])))
        baseline = json.loads(journal['baseline']); baseline['tree'] = json.loads(journal['after_image'])
        if self.writer._observed_baseline() != baseline:
            raise SafetyError('Accepted effect changed')
        return journal

    def complete(self, token, review_authorization_id):
        identifier(review_authorization_id)
        with self._transaction() as conn:
            _, ctl = self._validate(conn, token)
            if ctl['state'] != 'EXECUTING' or ctl['authority'] != 'AUTHORIZED':
                raise SafetyError('Completion requires current reconstructed owner')
            self._accepted_apply(conn, token)
            conn.execute('INSERT INTO approvals VALUES(?)', (review_authorization_id,))
            conn.execute("UPDATE daio_backend_control SET state='COMPLETED',authority='REVOKED' WHERE work_id=?", (token.work_id,))
            conn.execute("UPDATE daio_work_items SET status='COMPLETED',fencing_token=fencing_token+1,lease_id=NULL,lease_expires_at=NULL,claimed_by=NULL WHERE work_id=?", (token.work_id,))
            return self._event(conn, token.work_id, 'COMPLETED')

    def publish_outcome(self, *args, **kwargs):
        raise SafetyError('Unified path requires sealed artifact/journal evidence')

    def confirm_quiescence(self, *args, **kwargs):
        raise SafetyError('Route-B authority is not a termination receipt')
