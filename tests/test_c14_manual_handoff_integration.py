"""Disposable integration: no provider, browser, deployed DB or domain work."""
from dataclasses import asdict, replace
import hashlib
import json
import subprocess

import pytest

from scripts.daio_closed_loop.handoff import DurableHandoff
from scripts.daio_closed_loop.handoff_contract import (
    BackendIdentity, ExecutionOutcome, Outcome, TestStatus, Reconstruction,
    ReconstructionAck, QuiescenceReceipt, PublicationToken, SafetyError, StaleExecution, digest,
)
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore


A = BackendIdentity('antigravity_cli', 'AntigravityCLIAdapter', 'phase2-fake', 'CLI')
B = BackendIdentity('codex_cli', 'CodexCLIAdapter', 'phase2-fake', 'CLI')


def rows(store, sql, args=()):
    conn = store._get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


class FakeLifecycle:
    """No subprocess or workspace access; verifies lifecycle of owned fake calls."""
    def __init__(self):
        self.active = set()
        self.terminated = set()
        self.resumed = []

    def start(self, token):
        assert not self.active, 'Concurrent backend authority'
        self.active.add(token.execution_attempt_id)

    def reconstruct(self, serialized_packet):
        # Replacement receives only a serialized durable handoff, no A context.
        packet = json.loads(serialized_packet)
        assert packet['contract_version'] == 'daio-handoff/v1'
        manifest = packet['manifest']
        assert manifest['next_step'] not in manifest['completed_steps']
        return ReconstructionAck(PublicationToken(**packet['token']), packet['checkpoint_id'],
                                 packet['checkpoint_sha256'], digest(manifest))

    def finish(self, token):
        self.active.remove(token.execution_attempt_id)
        self.terminated.add(token.execution_attempt_id)

    def verify(self, attempt):
        return QuiescenceReceipt(attempt, 'TERMINATED' if attempt in self.terminated else 'UNKNOWN',
                                 'fake-isolation-' + attempt, 'ISOLATION_REVOKED')

    def propose(self, token, handoff):
        assert token.execution_attempt_id in self.active
        step = handoff['manifest']['next_step']
        assert step not in handoff['manifest']['completed_steps']
        self.resumed.append(step)
        return {'step': step, 'proposal': 'disposable arithmetic: 2 + 2 = 4'}


def fixture_state(root):
    repo = root / 'workspace'
    repo.mkdir()
    (repo / 'task.txt').write_text('Disposable proposal task: explain 2 + 2.\n')
    for args in [('init', '-q'), ('add', 'task.txt'),
                 ('-c', 'user.name=C1.4 Fixture', '-c', 'user.email=fixture@invalid',
                  '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Disposable baseline')]:
        subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)
    def observe():
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
        # Explicit safe-file allowlist; no credential or environment discovery.
        workspace_hash = hashlib.sha256((repo / 'task.txt').read_bytes()).hexdigest()
        return Reconstruction('c14-disposable-repo', head, workspace_hash,
                              digest({'manual': True, 'backends': [A.backend_id, B.backend_id]}),
                              digest(['proposal-only']), digest(['C1.3-untouched']),
                              digest(['disposable-baseline']), ('prepare-fixture',), 'propose-arithmetic')
    store = SqliteDAIOWorkStore(str(root / 'disposable.db'))
    work = DAIOWorkItem(work_id='c1.4-phase2-disposable-001', project_root=str(repo),
                        change_id='c1.4-phase2-fixture', assigned_role=DAIORole.ENGINEERING_EXECUTION,
                        current_gate=DAIOGate.ENGINEERING_TASK, attempt_count=1, max_attempts=3)
    store.save_work_item(work)
    ctl = DurableHandoff(store)
    token = ctl.enroll(work.work_id, observe(), (A.backend_id, B.backend_id))
    return store, ctl, token, observe, FakeLifecycle()


def acknowledged(ctl, token, observe):
    packet = ctl.handoff(token)
    ack = ReconstructionAck(token, packet['checkpoint_id'], packet['checkpoint_sha256'], digest(packet['manifest']))
    return ctl.acknowledge(ack, observe), packet


def test_disposable_manual_handoff_to_completion(tmp_path):
    store, ctl, token, observe, lifecycle = fixture_state(tmp_path)
    initial_budget = store.load_work_item(token.work_id).attempt_count
    token = ctl.authorize_backend(token, A, 'manual-approval-A')
    token = ctl.begin_attempt(token, 'fake-worker-A')
    token, _ = acknowledged(ctl, token, observe)
    attempt_a = ctl.start_execution(token, observe)
    lifecycle.start(attempt_a)
    interrupted = ctl.publish_outcome(attempt_a, ExecutionOutcome(Outcome.BACKEND_UNAVAILABLE))
    after_a = store.load_work_item(token.work_id)
    assert after_a.status == DAIOStatus.WAITING_FOR_EXECUTION_CAPACITY
    assert after_a.attempt_count == initial_budget
    first = rows(store, 'SELECT * FROM daio_backend_attempts')[0]
    assert first['tests'] == 'NOT_RUN' and first['outcome'] == 'BACKEND_UNAVAILABLE'

    # A: uncertain termination blocks quiescence, checkpoint AND replacement.
    for operation in [lambda: ctl.confirm_quiescence(interrupted, lifecycle.verify),
                      lambda: ctl.publish_checkpoint(interrupted, observe),
                      lambda: ctl.authorize_backend(interrupted, B, 'premature-B')]:
        with pytest.raises(SafetyError):
            operation()
    assert ctl.token(token.work_id) == interrupted
    lifecycle.finish(attempt_a)
    quiescent = ctl.confirm_quiescence(interrupted, lifecycle.verify)
    # Old authority cannot publish even before B exists.
    with pytest.raises(StaleExecution):
        ctl.publish_outcome(attempt_a, ExecutionOutcome(Outcome.SUCCESS), 'a' * 64)
    checkpoint_token, checkpoint_id = ctl.publish_checkpoint(quiescent, observe)
    checkpoint = rows(store, 'SELECT * FROM daio_checkpoints WHERE checkpoint_id=?', (checkpoint_id,))[0]
    assert digest(json.loads(checkpoint['payload'])) == checkpoint['sha256']

    # Reconstruct controller from durable state, with no prior in-memory tokens.
    store = SqliteDAIOWorkStore(store.db_path)
    ctl = DurableHandoff(store)
    token = ctl.token(checkpoint_token.work_id)
    token = ctl.authorize_backend(token, B, 'manual-approval-B')
    token = ctl.begin_attempt(token, 'fake-worker-B')
    assert token.execution_attempt_id != attempt_a.execution_attempt_id
    assert token.fencing_token > attempt_a.fencing_token
    packet = ctl.handoff(token)
    assert packet['checkpoint_id'] == checkpoint_id
    assert packet['checkpoint_sha256'] == checkpoint['sha256']
    assert packet['token']['work_id'] == token.work_id
    assert packet['token']['execution_attempt_id'] == token.execution_attempt_id
    assert packet['token']['fencing_token'] == token.fencing_token
    ack = lifecycle.reconstruct(json.dumps(packet))
    assert ack.token == token
    with pytest.raises(SafetyError):
        ctl.start_execution(token, observe)
    # B/C/D: stale A, wrong hash and wrong measurement cannot publish authority.
    with pytest.raises(StaleExecution):
        ctl.publish_outcome(attempt_a, ExecutionOutcome(Outcome.SUCCESS), 'a' * 64)
    with pytest.raises(SafetyError):
        ctl.acknowledge(replace(ack, checkpoint_sha256='0' * 64), observe)
    with pytest.raises(SafetyError):
        ctl.acknowledge(ack, lambda: replace(observe(), workspace_sha256='0' * 64))
    for wrong_token in [replace(token, work_id='wrong-work'),
                        replace(token, execution_attempt_id=attempt_a.execution_attempt_id),
                        replace(token, fencing_token=attempt_a.fencing_token)]:
        with pytest.raises(StaleExecution):
            ctl.acknowledge(replace(ack, token=wrong_token), observe)
    assert ctl.token(token.work_id) == token
    token = ctl.acknowledge(ack, observe)
    attempt_b = ctl.start_execution(token, observe)
    lifecycle.start(attempt_b)
    proposal = lifecycle.propose(attempt_b, packet)
    assert lifecycle.resumed == ['propose-arithmetic']
    # Host-owned artifact storage outside the engineering workspace.
    (tmp_path / 'proposal.json').write_text(json.dumps(proposal, sort_keys=True))
    result = ctl.publish_outcome(attempt_b, ExecutionOutcome(Outcome.SUCCESS), digest(proposal))
    with pytest.raises(SafetyError):
        ctl.complete(result, 'review-complete', observe, lifecycle.verify)
    lifecycle.finish(attempt_b)
    final = ctl.complete(result, 'review-complete', observe, lifecycle.verify)
    assert not lifecycle.active
    final_work = store.load_work_item(final.work_id)
    assert final_work.status == DAIOStatus.COMPLETED
    assert final_work.attempt_count == initial_budget
    assert final_work.lease_id is None and final.fencing_token > attempt_b.fencing_token
    with pytest.raises(SafetyError):
        ctl.enroll(final.work_id, observe(), (B.backend_id,))
    with pytest.raises(SafetyError):
        ctl.authorize_backend(final, A, 'replay-denied')
    with pytest.raises(StaleExecution):
        ctl.complete(result, 'duplicate-review', observe, lifecycle.verify)
    assert store.acquire_lease(final.work_id, 'legacy') is None
    assert store.claim_next_available_work_item('legacy') is None
    frozen = DAIOWorkItem(work_id='c14-frozen-negative', project_root=str(tmp_path),
                          change_id='c14-fixture', status=DAIOStatus.FROZEN)
    store.save_work_item(frozen)
    with pytest.raises(SafetyError):
        ctl.enroll(frozen.work_id, observe(), (B.backend_id,))
    assert store.acquire_lease(frozen.work_id, 'legacy') is None
    assert rows(store, 'SELECT * FROM daio_checkpoints WHERE checkpoint_id=?', (checkpoint_id,))[0] == checkpoint
    attempts = rows(store, 'SELECT * FROM daio_backend_attempts ORDER BY fencing_token')
    assert len(attempts) == 2 and attempts[1]['previous_attempt_id'] == attempt_a.execution_attempt_id
    assert attempts[0]['outcome'] == 'BACKEND_UNAVAILABLE' and attempts[0]['tests'] == 'NOT_RUN'
    assert all(a['quiescence'] == 'TERMINATED' for a in attempts)
    assert attempts[1]['reconstruction_sha256'] == ack.manifest_sha256
    events = rows(store, 'SELECT * FROM daio_work_events ORDER BY event_sequence')
    expected = ['ENROLLED', 'BACKEND_AUTHORIZED', 'ATTEMPT_CREATED', 'RECONSTRUCTION_VALIDATED',
                'EXECUTION_STARTED', 'BACKEND_UNAVAILABLE', 'QUIESCENCE_VERIFIED', 'CHECKPOINT_PUBLISHED',
                'BACKEND_AUTHORIZED', 'ATTEMPT_CREATED', 'RECONSTRUCTION_VALIDATED', 'EXECUTION_STARTED',
                'SUCCESS', 'COMPLETED']
    assert [e['event'] for e in events] == expected
    assert [e['event_sequence'] for e in events] == list(range(1, 15))
    assert [e['work_revision'] for e in events] == list(range(1, 15))
    assert [e['fencing_token'] for e in events] == sorted(e['fencing_token'] for e in events)
    report = dict(work_id=final.work_id, attempt_a=attempt_a.execution_attempt_id,
                  backend_a=A.backend_id, capacity_outcome=first['outcome'], tests_after_a=first['tests'],
                  failure_budget_before=initial_budget, failure_budget_after=final_work.attempt_count,
                  max_attempts=final_work.max_attempts, checkpoint_id=checkpoint_id,
                  checkpoint_sha256=checkpoint['sha256'], checkpoint_hash_verified=True,
                  quiescence_a='VERIFIED_FAKE_ISOLATION_REVOKED', authorization_transition=['manual-approval-A','manual-approval-B'],
                  attempt_b=attempt_b.execution_attempt_id, backend_b=B.backend_id,
                  fences=[attempt_a.fencing_token, attempt_b.fencing_token, final.fencing_token],
                  stale_a_rejected=True, reconstruction_ack_verified=True, resume_point=lifecycle.resumed[0],
                  final_status=final_work.status.value, final_updated_at=final_work.updated_at,
                  events=events, attempts=attempts, reconstruction_ack=asdict(ack),
                  checkpoint_payload=json.loads(checkpoint['payload']), proposal=proposal,
                  negative_cases={k: 'PASSED' for k in ['A','B','C','D','E','F']},
                  execution_mode='FAKE_PROPOSAL_ONLY', review_authorization_id='review-complete')
    (tmp_path / 'integration-report.json').write_text(json.dumps(report, indent=2) + '\n')


@pytest.mark.parametrize('status', [DAIOStatus.COMPLETED, DAIOStatus.FROZEN])
def test_negative_e_terminal_work_never_admitted(tmp_path, status):
    store, ctl, token, observe, _ = fixture_state(tmp_path)
    if status == DAIOStatus.FROZEN:
        terminal = ctl.stop(token, 'FROZEN')
        with pytest.raises(SafetyError):
            ctl.authorize_backend(terminal, A, 'forbidden')
    else:
        # Independently constructed terminal fixture, not a mutation of enrolled work.
        item = DAIOWorkItem(work_id='completed-fixture', project_root=str(tmp_path), change_id='c14', status=status)
        store.save_work_item(item)
        token = replace(token, work_id=item.work_id)
    with pytest.raises(SafetyError):
        ctl.enroll(token.work_id, observe(), (A.backend_id,))
    assert store.acquire_lease(token.work_id, 'worker') is None


@pytest.mark.parametrize('failure', ['not-successful', 'wrong-measurement', 'wrong-receipt', 'duplicate-authorization'])
def test_completion_fails_closed(tmp_path, failure):
    store, ctl, token, observe, lifecycle = fixture_state(tmp_path)
    token = ctl.authorize_backend(token, B, 'selection')
    token = ctl.begin_attempt(token, 'worker')
    token, _ = acknowledged(ctl, token, observe)
    token = ctl.start_execution(token, observe)
    lifecycle.start(token)
    lifecycle.finish(token)
    outcome = Outcome.ENGINEERING_FAILURE if failure == 'not-successful' else Outcome.SUCCESS
    token = ctl.publish_outcome(token, ExecutionOutcome(outcome), 'a' * 64)
    measurement = (lambda: replace(observe(), workspace_sha256='0' * 64)) if failure == 'wrong-measurement' else observe
    verifier = (lambda attempt: replace(lifecycle.verify(attempt), execution_attempt_id='wrong-attempt')) if failure == 'wrong-receipt' else lifecycle.verify
    approval = 'selection' if failure == 'duplicate-authorization' else 'completion'
    import sqlite3
    with pytest.raises((SafetyError, sqlite3.IntegrityError)):
        ctl.complete(token, approval, measurement, verifier)
    assert ctl.token(token.work_id) == token
    assert store.load_work_item(token.work_id).status == DAIOStatus.AWAITING_REVIEW
