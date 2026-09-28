"""Phase 3B3: real host crashes/locks, inert proposals, disposable Git and SQLite."""
from dataclasses import replace
import json
import multiprocessing
import os
import sqlite3
import subprocess

import pytest

from scripts.daio_closed_loop.handoff import DurableHandoff
from scripts.daio_closed_loop.handoff_contract import (
    BackendIdentity, Reconstruction, ReconstructionAck, SafetyError, digest,
)
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIORole, DAIOGate
from scripts.daio_closed_loop.trusted_writer import TrustedWriter, VERSION, WriterBusy, sha
from scripts.daio_closed_loop.unified_handoff import UnifiedHandoff

A = BackendIdentity('antigravity_cli', 'AntigravityCLIAdapter', 'inert-3b3', 'CLI')
B = BackendIdentity('codex_cli', 'CodexCLIAdapter', 'inert-3b3', 'CLI')
MP = multiprocessing.get_context('fork')


def git(repo, *args):
    return subprocess.check_output(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
        '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid',
        '-C', str(repo), *args], stderr=subprocess.DEVNULL)


def rows(ctl, sql, args=()):
    conn = sqlite3.connect(ctl.writer.db); conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def observe(ctl, steps=(), next_step='step-A'):
    return Reconstruction('disposable-3b3', git(ctl.writer.repo, 'rev-parse', 'HEAD').decode().strip(),
        digest(ctl.writer._tree()), digest(['manual', A.backend_id, B.backend_id]),
        digest(['a.txt', 'b.txt']), digest(['frozen.txt']), digest(['fixture']), steps, next_step)


@pytest.fixture
def fixture(tmp_path):
    repo = tmp_path/'repo'; repo.mkdir()
    for path in ('a.txt', 'b.txt', 'frozen.txt'):
        (repo/path).write_text('before '+path+'\n')
    git(repo, 'init', '-q'); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'Disposable baseline')
    ctl = UnifiedHandoff(repo, tmp_path/'state')
    ctl.store.save_work_item(DAIOWorkItem(work_id='W-3b3', project_root=str(repo), change_id='disposable',
        assigned_role=DAIORole.ENGINEERING_EXECUTION, current_gate=DAIOGate.ENGINEERING_TASK))
    token = ctl.enroll('W-3b3', observe(ctl), (A.backend_id, B.backend_id),
                       allowed=['a.txt', 'b.txt'], frozen=['frozen.txt'])
    return ctl, token


def restart(ctl):
    return UnifiedHandoff(ctl.writer.repo, ctl.writer.control)


def start(ctl, token, backend=A):
    token = ctl.authorize_backend(token, backend, 'select-'+backend.backend_id)
    token = ctl.begin_attempt(token, 'worker-'+backend.backend_id)
    packet = ctl.handoff(token)
    ack = ReconstructionAck(token, packet['checkpoint_id'], packet['checkpoint_sha256'], digest(packet['manifest']))
    measurement = lambda: Reconstruction(**packet['manifest'])
    token = ctl.acknowledge(ack, measurement)
    return ctl.start_execution(token, measurement)


def seal(ctl, token, paths=('a.txt',), label='accepted'):
    payload = {'version': VERSION, 'changes': [{'path': p, 'expected_sha256': sha((ctl.writer.repo/p).read_bytes()),
                                              'content': label+' '+p+'\n'} for p in paths]}
    return ctl.writer.ingest(token, json.dumps(payload).encode())


def handoff(ctl, token, advanced=True):
    token = ctl.revoke(token, 'revoke-A')
    token, cp = ctl.publish_checkpoint(token, lambda: observe(ctl, ('step-A',) if advanced else (),
                                                             'step-B' if advanced else 'step-A'))
    return start(ctl, token, B), cp


def crash_apply(repo, state, token, artifact, digest_, stage):
    ctl = UnifiedHandoff(repo, state)
    ctl.writer.apply(token, artifact, digest_, lambda s: os._exit(73) if s == stage else None)


def killed_apply(ctl, sealed, stage):
    child = MP.Process(target=crash_apply, args=(ctl.writer.repo, ctl.writer.control, *sealed, stage))
    child.start(); child.join(15)
    if child.is_alive():
        child.kill(); child.join(); pytest.fail('Inert child exceeded test bound')
    assert child.exitcode == 73
    return restart(ctl)


def assert_monotonic(ctl):
    events = rows(ctl, 'SELECT * FROM daio_work_events ORDER BY event_sequence')
    assert [e['event_sequence'] for e in events] == list(range(1, len(events)+1))
    assert [e['work_revision'] for e in events] == list(range(1, len(events)+1))
    assert [e['fencing_token'] for e in events] == sorted(e['fencing_token'] for e in events)
    assert not rows(ctl, "SELECT * FROM sqlite_master WHERE type='table' AND name IN ('work','events')")
    return events


def test_end_to_end_single_controller_authority(fixture, tmp_path):
    ctl, token = fixture
    head = git(ctl.writer.repo, 'rev-parse', 'HEAD')
    a = start(ctl, token)
    sealed_a = seal(ctl, a)
    applied_a = ctl.writer.apply(*sealed_a)
    assert applied_a == ctl.token(a.work_id)
    b, cp = handoff(ctl, applied_a)
    assert a.work_id == b.work_id and a.execution_attempt_id != b.execution_attempt_id
    assert b.fencing_token > a.fencing_token
    with pytest.raises(SafetyError): ctl.writer.apply(*sealed_a)
    sealed_b = seal(ctl, b, ('b.txt',), 'B')
    final = ctl.complete(ctl.writer.apply(*sealed_b), 'manual-complete')
    assert ctl.store.load_work_item(final.work_id).status.value == 'COMPLETED'
    assert git(ctl.writer.repo, 'rev-parse', 'HEAD') == head
    assert [j['state'] for j in ctl.writer.journals()] == ['COMMITTED', 'COMMITTED']
    attempts = rows(ctl, 'SELECT * FROM daio_backend_attempts ORDER BY fencing_token')
    assert attempts[1]['previous_attempt_id'] == a.execution_attempt_id
    assert all(r['quiescence'] == 'UNKNOWN' and r['tests'] == 'NOT_RUN' for r in attempts)
    assert all(r['reconstruction_sha256'] for r in attempts)
    control = rows(ctl, 'SELECT * FROM daio_backend_control')[0]
    assert control['authority'] == 'REVOKED' and control['quiescence'] == 'UNKNOWN'
    checkpoint = rows(ctl, 'SELECT * FROM daio_checkpoints WHERE checkpoint_id=?', (cp,))[0]
    assert digest(json.loads(checkpoint['payload'])) == checkpoint['sha256']
    events = assert_monotonic(ctl)
    assert [e['event'] for e in events] == [
        'ENROLLED','BACKEND_AUTHORIZED','ATTEMPT_CREATED','RECONSTRUCTION_VALIDATED','EXECUTION_STARTED',
        'ARTIFACT_SEALED','APPLY_COMMITTED','AUTHORITY_REVOKED','CHECKPOINT_PUBLISHED',
        'BACKEND_AUTHORIZED','ATTEMPT_CREATED','RECONSTRUCTION_VALIDATED','EXECUTION_STARTED',
        'ARTIFACT_SEALED','APPLY_COMMITTED','COMPLETED']
    with pytest.raises(SafetyError): ctl.authorize_backend(final, A, 'replay')
    (tmp_path/'unified-report.json').write_text(json.dumps(dict(work_id=final.work_id, attempts=attempts,
        events=events, checkpoint=checkpoint, journals=ctl.writer.journals(), git_head_unchanged=True,
        authority='REVOKED', lifecycle='UNKNOWN', status='COMPLETED'), indent=2)+'\n')


def test_revoke_first_invalidates_sealed_artifact(fixture):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token))
    revoked = ctl.revoke(sealed[0], 'revoke-first')
    ctl = restart(ctl)
    with pytest.raises(SafetyError): ctl.writer.apply(*sealed)
    assert ctl.token(token.work_id) == revoked
    assert not ctl.writer.journals()
    assert (ctl.writer.repo/'a.txt').read_text() == 'before a.txt\n'


@pytest.mark.parametrize('stage', ['PREPARED', 'APPLYING', 'FILE_0', 'FILE_1', 'APPLIED', 'COMMITTED'])
def test_real_crash_restart_pending_blocks_all_transitions(fixture, stage):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token), ('a.txt', 'b.txt'))
    ctl = killed_apply(ctl, sealed, stage)
    current = ctl.token(token.work_id)
    if stage == 'COMMITTED':
        assert current.work_revision == sealed[0].work_revision+1
        ctl.complete(current, 'after-crash-complete')
        return
    assert current == sealed[0]
    for operation in [lambda: ctl.revoke(current, 'blocked-revoke'),
                      lambda: ctl.authorize_backend(current, B, 'blocked-B'),
                      lambda: ctl.begin_attempt(current, 'blocked-worker'),
                      lambda: ctl.complete(current, 'blocked-complete'),
                      lambda: ctl.stop(current),
                      lambda: seal(ctl, current),
                      lambda: ctl.renew(current)]:
        with pytest.raises(SafetyError, match='RECONCILIATION_REQUIRED'): operation()
    journal = ctl.writer.journals()[0]
    result = ctl.writer.reconcile(journal['apply_id'])
    if stage in ('FILE_1', 'APPLIED'):
        assert result == 'COMMITTED'
    else:
        assert result == 'RECONCILIATION_REQUIRED'
        ctl.writer.resolve_forward(journal['apply_id'], 'approve-roll-forward')
    assert all(j['state']=='COMMITTED' for j in ctl.writer.journals())
    ctl.complete(ctl.token(current.work_id), 'resolved-complete')
    assert_monotonic(ctl)


@pytest.mark.parametrize('drift', ['bytes', 'extra', 'mode', 'index', 'head', 'staging'])
def test_unresolvable_partial_apply_stays_blocked(fixture, drift):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token), ('a.txt', 'b.txt'))
    ctl = killed_apply(ctl, sealed, 'STAGED_0' if drift == 'staging' else 'FILE_0')
    repo = ctl.writer.repo
    if drift == 'bytes': (repo/'b.txt').write_text('unexplained')
    elif drift == 'extra': (repo/'extra.txt').write_text('unexplained')
    elif drift == 'mode': (repo/'b.txt').chmod(0o755)
    elif drift == 'index': git(repo, 'add', 'a.txt')
    elif drift == 'head': git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'external-drift')
    journal = ctl.writer.journals()[0]
    observed = ctl.writer._tree()
    assert ctl.writer.reconcile(journal['apply_id']) == 'RECONCILIATION_REQUIRED'
    with pytest.raises(SafetyError, match='BLOCKED'): ctl.writer.resolve_forward(journal['apply_id'], 'no-speculation')
    with pytest.raises(SafetyError): ctl.revoke(sealed[0], 'unsafe-revoke')
    with pytest.raises(SafetyError): ctl.complete(sealed[0], 'unsafe-complete')
    assert ctl.writer._tree() == observed
    assert ctl.writer.journals()[0]['state'] == 'RECONCILIATION_REQUIRED'


def hold_apply(repo, state, sealed, admitted, release):
    ctl = UnifiedHandoff(repo, state)
    def hook(stage):
        if stage == 'PREPARED':
            admitted.set()
            if not release.wait(10): raise RuntimeError('Test barrier timeout')
    ctl.writer.apply(*sealed, crash_hook=hook)


def test_apply_first_revocation_and_competing_apply_cannot_acknowledge(fixture):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token))
    admitted, release = MP.Event(), MP.Event()
    child = MP.Process(target=hold_apply, args=(ctl.writer.repo, ctl.writer.control, sealed, admitted, release))
    child.start()
    try:
        assert admitted.wait(10)
        for operation in [lambda: ctl.revoke(sealed[0], 'racing-revoke'),
                          lambda: ctl.authorize_backend(sealed[0], B, 'racing-B'),
                          lambda: ctl.complete(sealed[0], 'racing-complete'),
                          lambda: ctl.writer.apply(*sealed),
                          lambda: ctl.writer.apply(replace(sealed[0], execution_attempt_id='fake-B'), *sealed[1:])]:
            with pytest.raises(WriterBusy): operation()
    finally:
        release.set(); child.join(15)
        if child.is_alive(): child.kill(); child.join()
    assert child.exitcode == 0
    with pytest.raises(SafetyError): ctl.revoke(sealed[0], 'old-token')
    revoked = ctl.revoke(ctl.token(token.work_id), 'known-effect-revoke')
    assert revoked.fencing_token > token.fencing_token
    assert_monotonic(ctl)


def transition_crash(repo, state, token, operation, committed):
    ctl = UnifiedHandoff(repo, state)
    original = ctl._event
    def abort_event(conn, work_id, event):
        result = original(conn, work_id, event)
        if not committed: os._exit(74)
        return result
    ctl._event = abort_event
    if operation == 'revoke': ctl.revoke(token, 'crash-revoke')
    elif operation == 'authorize': ctl.authorize_backend(token, B, 'crash-authorize')
    elif operation == 'seal': seal(ctl, token)
    elif operation == 'begin': ctl.begin_attempt(token, 'crash-begin')
    os._exit(74)


@pytest.mark.parametrize('operation', ['revoke', 'authorize', 'seal', 'begin'])
@pytest.mark.parametrize('committed', [False, True])
def test_controller_transition_crash_atomic_restart(fixture, operation, committed):
    ctl, token = fixture
    if operation in ('revoke', 'seal'):
        token = start(ctl, token)
    else:
        token = ctl.writer.apply(*seal(ctl, start(ctl, token)))
        token = ctl.revoke(token, 'revoke-before-replacement')
        token, _ = ctl.publish_checkpoint(token, lambda: observe(ctl, ('step-A',), 'step-B'))
        if operation == 'begin':
            token = ctl.authorize_backend(token, B, 'select-before-crash')
    child = MP.Process(target=transition_crash, args=(ctl.writer.repo, ctl.writer.control, token, operation, committed))
    child.start(); child.join(15)
    if child.is_alive(): child.kill(); child.join(); pytest.fail('Child timeout')
    assert child.exitcode == 74
    ctl = restart(ctl)
    current = ctl.token(token.work_id)
    assert current.work_revision == token.work_revision + int(committed)
    control = rows(ctl, 'SELECT * FROM daio_backend_control')[0]
    if operation == 'revoke': assert control['authority'] == ('REVOKED' if committed else 'AUTHORIZED')
    if operation == 'authorize': assert control['state'] == ('AUTHORIZED' if committed else 'CHECKPOINTED')
    if operation == 'begin': assert control['state'] == ('RECONSTRUCTION_REQUIRED' if committed else 'AUTHORIZED')
    if operation == 'seal': assert len(rows(ctl, 'SELECT * FROM artifacts')) == int(committed)
    assert_monotonic(ctl)


@pytest.mark.parametrize('drift', ['head', 'index', 'bytes'])
def test_valid_artifact_changed_repository_rejected(fixture, drift):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token))
    (ctl.writer.repo/'a.txt').write_text('external edit')
    if drift == 'index': git(ctl.writer.repo, 'add', '.')
    elif drift == 'head': git(ctl.writer.repo, 'add', '.'); git(ctl.writer.repo, 'commit', '-qm', 'external')
    with pytest.raises(SafetyError): ctl.writer.apply(*sealed)
    assert not ctl.writer.journals()


def test_legacy_authority_paths_cannot_bypass_unified_state(fixture):
    ctl, token = fixture
    legacy = DurableHandoff(ctl.store)
    for operation in [lambda: legacy.authorize_backend(token, A, 'bypass'), lambda: legacy.stop(token),
                      lambda: ctl.writer.register('x','y','z',['a.txt']),
                      lambda: ctl.writer.authority_transition(token,'REPLACE','bypass','fake-B'),
                      lambda: TrustedWriter(ctl.writer.repo, ctl.writer.control)]:
        with pytest.raises(SafetyError): operation()
    with sqlite3.connect(ctl.writer.db) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO work VALUES('x','a',1,1,1,'AUTHORIZED','UNKNOWN','OPEN','{}','{}')")
    with pytest.raises(TypeError):
        TrustedWriter(ctl.writer.repo, ctl.writer.control, authority_mode=ctl.contract_version)
    assert ctl.store.acquire_lease(token.work_id, 'legacy') is None


def test_reconstruction_and_completion_admission(fixture):
    ctl, token = fixture
    token = ctl.authorize_backend(token, A, 'authorize')
    token = ctl.begin_attempt(token, 'worker')
    with pytest.raises(SafetyError): seal(ctl, token)
    with pytest.raises(SafetyError): ctl.start_execution(token, lambda: observe(ctl))
    packet = ctl.handoff(token)
    ack = ReconstructionAck(token, packet['checkpoint_id'], packet['checkpoint_sha256'], digest(packet['manifest']))
    with pytest.raises(SafetyError): ctl.acknowledge(replace(ack, checkpoint_sha256='0'*64), lambda: observe(ctl))
    token = ctl.acknowledge(ack, lambda: observe(ctl))
    with pytest.raises(SafetyError): seal(ctl, token)
    token = ctl.start_execution(token, lambda: observe(ctl))
    with pytest.raises(SafetyError): ctl.complete(token, 'no-artifact')
    sealed = seal(ctl, token)
    with pytest.raises(SafetyError): ctl.complete(sealed[0], 'not-applied')
    ctl.writer.apply(*sealed)
    current = ctl.token(token.work_id)
    (ctl.writer.repo/'a.txt').write_text('unknown effect')
    with pytest.raises(SafetyError): ctl.complete(current, 'drift')


def test_stale_artifact_cannot_be_rebound_to_current_B(fixture):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token))
    b, _ = handoff(ctl, sealed[0], advanced=False)
    before = ctl.token(token.work_id)
    with pytest.raises(SafetyError): ctl.writer.apply(b, *sealed[1:])
    with pytest.raises(SafetyError): ctl.writer.apply(*sealed)
    assert ctl.token(token.work_id) == before
    assert not ctl.writer.journals()


def test_only_one_work_can_own_repository(fixture):
    ctl, token = fixture
    ctl.store.save_work_item(DAIOWorkItem(work_id='other-work', project_root=str(ctl.writer.repo), change_id='disposable',
        assigned_role=DAIORole.ENGINEERING_EXECUTION, current_gate=DAIOGate.ENGINEERING_TASK))
    other = ctl.enroll('other-work', observe(ctl), (A.backend_id,), allowed=['a.txt','b.txt'], frozen=['frozen.txt'])
    token = ctl.authorize_backend(token, A, 'first-owner')
    with pytest.raises(SafetyError, match='Another work'): ctl.authorize_backend(other, A, 'second-owner')


def test_concurrent_stale_A_and_current_B_apply(fixture):
    ctl, token = fixture
    sealed_a = seal(ctl, start(ctl, token))
    b, _ = handoff(ctl, sealed_a[0], advanced=False)
    sealed_b = seal(ctl, b, ('b.txt',), 'current-B')
    admitted, release = MP.Event(), MP.Event()
    child = MP.Process(target=hold_apply, args=(ctl.writer.repo, ctl.writer.control, sealed_b, admitted, release))
    child.start()
    try:
        assert admitted.wait(10)
        with pytest.raises(WriterBusy): ctl.writer.apply(*sealed_a)
    finally:
        release.set(); child.join(15)
        if child.is_alive(): child.kill(); child.join()
    assert child.exitcode == 0
    with pytest.raises(SafetyError): ctl.writer.apply(*sealed_a)
    assert (ctl.writer.repo/'a.txt').read_text() == 'before a.txt\n'
    assert (ctl.writer.repo/'b.txt').read_text() == 'current-B b.txt\n'
    assert len(ctl.writer.journals()) == 1
    assert_monotonic(ctl)


def resolution_crash(repo, state, apply_id):
    ctl = UnifiedHandoff(repo, state)
    ctl.writer.resolve_forward(apply_id, 'first-resolution',
                              lambda stage: os._exit(75) if stage.startswith('RESOLUTION_FILE_') else None)


def test_resolution_restart_does_not_replay_after_images(fixture):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token), ('a.txt','b.txt'))
    ctl = killed_apply(ctl, sealed, 'PREPARED')
    apply_id = ctl.writer.journals()[0]['apply_id']
    child = MP.Process(target=resolution_crash, args=(ctl.writer.repo, ctl.writer.control, apply_id))
    child.start(); child.join(15)
    if child.is_alive(): child.kill(); child.join(); pytest.fail('Child timeout')
    assert child.exitcode == 75
    ctl = restart(ctl)
    inode = (ctl.writer.repo/'a.txt').stat().st_ino
    ctl.writer.resolve_forward(apply_id, 'second-resolution')
    assert (ctl.writer.repo/'a.txt').stat().st_ino == inode
    assert len(rows(ctl, 'SELECT * FROM resolutions')) == 2
    assert ctl.writer.journals()[0]['state'] == 'COMMITTED'


def test_lease_expiry_blocks_new_admission_but_not_admitted_recovery(fixture):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token), ('a.txt','b.txt'))
    ctl = killed_apply(ctl, sealed, 'FILE_0')
    # Disposable clock fixture: no production DB access.
    with sqlite3.connect(ctl.writer.db) as conn:
        conn.execute("UPDATE daio_work_items SET lease_expires_at='2000-01-01T00:00:00+00:00'")
    ctl.writer.resolve_forward(ctl.writer.journals()[0]['apply_id'], 'expired-lease-recovery')
    current = ctl.token(token.work_id)
    with pytest.raises(SafetyError): seal(ctl, current)
    ctl.revoke(current, 'explicit-expired-revoke')


@pytest.mark.parametrize('status', ['FROZEN','STOP','SUPERSEDED','HUMAN_GATE_REQUIRED'])
def test_terminal_state_rejects_writer_and_replacement(fixture, status):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token))
    stopped = ctl.stop(sealed[0], status)
    with pytest.raises(SafetyError): ctl.writer.apply(*sealed)
    with pytest.raises(SafetyError): ctl.writer.ingest(stopped, b'{}')
    with pytest.raises(SafetyError): ctl.authorize_backend(stopped, B, 'forbidden')
    assert rows(ctl, 'SELECT authority FROM daio_backend_control')[0]['authority'] == 'REVOKED'


@pytest.mark.parametrize('field,value', [('work_id','wrong-work'), ('work_revision',999),
    ('event_sequence',999), ('execution_attempt_id','wrong-attempt'), ('fencing_token',999)])
def test_writer_consumes_exact_controller_token(fixture, field, value):
    ctl, token = fixture
    sealed = seal(ctl, start(ctl, token))
    with pytest.raises(SafetyError): ctl.writer.apply(replace(sealed[0], **{field: value}), *sealed[1:])
    assert ctl.token(token.work_id) == sealed[0]
    assert not ctl.writer.journals()


def test_work_repository_binding_mismatch_rejected_atomically(fixture):
    ctl, _ = fixture
    ctl.store.save_work_item(DAIOWorkItem(work_id='wrong-repo', project_root='/disposable-wrong-repo', change_id='disposable',
        assigned_role=DAIORole.ENGINEERING_EXECUTION, current_gate=DAIOGate.ENGINEERING_TASK))
    with pytest.raises(SafetyError, match='repository binding'):
        ctl.enroll('wrong-repo', observe(ctl), (A.backend_id,), allowed=['a.txt','b.txt'], frozen=['frozen.txt'])
    assert not rows(ctl, "SELECT * FROM daio_backend_control WHERE work_id='wrong-repo'")
    assert not rows(ctl, "SELECT * FROM daio_checkpoints WHERE work_id='wrong-repo'")
