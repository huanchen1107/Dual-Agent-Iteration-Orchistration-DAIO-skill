"""C1.4 focused acceptance on disposable SQLite databases; no live providers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3

import pytest

from scripts.daio_closed_loop.handoff import DurableHandoff
from scripts.daio_closed_loop.handoff_contract import (
    BackendIdentity, ExecutionOutcome, Outcome, Reconstruction, ReconstructionAck,
    SafetyError, StaleExecution, TestStatus, QuiescenceReceipt, digest,
)
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole, ArchitectDecision
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor, ExecutionResult
from scripts.daio_closed_loop.adapters.agent_contract import AgentTaskProposal
from scripts.daio_closed_loop.adapters.backend_outcomes import classify_failure


AGY = BackendIdentity('antigravity_cli', 'AntigravityCLIAdapter', '1', 'CLI')
CODEX = BackendIdentity('codex_cli', 'CodexCLIAdapter', '1', 'CLI')


def test_execution_result_preserves_legacy_positional_arguments():
    result = ExecutionResult(True, True, 'base-sha', 'head-sha', 'commit-sha')
    assert (result.base_sha, result.head_sha, result.commit_sha) == ('base-sha', 'head-sha', 'commit-sha')
    assert result.outcome == Outcome.UNKNOWN_FAILURE
    assert result.test_status == TestStatus.NOT_RUN


def manifest():
    return Reconstruction('repo-test', 'a' * 40, *(['b' * 64] * 5), ('contract-approved',), 'propose')


def work(work_id='work-test', **kwargs):
    fields = dict(work_id=work_id, project_root='/unused', change_id='c1.4-fixture',
                  current_gate=DAIOGate.ENGINEERING_TASK, assigned_role=DAIORole.ENGINEERING_EXECUTION)
    fields.update(kwargs)
    return DAIOWorkItem(**fields)


@pytest.fixture
def setup(tmp_path):
    store = SqliteDAIOWorkStore(str(tmp_path / 'state.db'))
    store.save_work_item(work())
    ctl = DurableHandoff(store)
    token = ctl.enroll('work-test', manifest(), ('antigravity_cli', 'codex_cli', 'codex_ide_manual'))
    return store, ctl, token


def prepare(ctl, token, backend=AGY, authorization='approval-1'):
    token = ctl.authorize_backend(token, backend, authorization)
    token = ctl.begin_attempt(token, 'worker-test')
    handoff = ctl.handoff(token)
    ack = ReconstructionAck(token, handoff['checkpoint_id'], handoff['checkpoint_sha256'], digest(handoff['manifest']))
    token = ctl.acknowledge(ack, manifest)
    return ctl.start_execution(token, manifest)


def interrupt(ctl, token):
    return ctl.publish_outcome(token, ExecutionOutcome(Outcome.QUOTA_EXHAUSTED))


def checkpoint(ctl, token):
    token = ctl.confirm_quiescence(token, lambda attempt: QuiescenceReceipt(attempt, 'TERMINATED', 'wait-receipt-1', 'VERIFIED_NOT_STARTED'))
    return ctl.publish_checkpoint(token, manifest)[0]


def query(store, sql, args=()):
    conn = store._get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        if not store._shared_conn:
            conn.close()


def test_durable_same_work_manual_handoff_restart_and_provenance(setup):
    store, ctl, initial = setup
    first = prepare(ctl, initial)
    interrupted = interrupt(ctl, first)
    assert store.load_work_item(first.work_id).attempt_count == 0
    assert store.load_work_item(first.work_id).status == DAIOStatus.WAITING_FOR_EXECUTION_CAPACITY
    cp = checkpoint(ctl, interrupted)
    # Restart the controller/store; no in-memory session is required.
    reopened = SqliteDAIOWorkStore(store.db_path)
    ctl = DurableHandoff(reopened)
    assert ctl.token(cp.work_id) == cp
    second = prepare(ctl, cp, CODEX, 'approval-2')
    assert second.work_id == first.work_id
    assert second.execution_attempt_id != first.execution_attempt_id
    assert second.fencing_token > first.fencing_token
    final = ctl.publish_outcome(second, ExecutionOutcome(Outcome.SUCCESS), result_sha256='c' * 64)
    attempts = query(store, 'SELECT * FROM daio_backend_attempts ORDER BY fencing_token')
    assert [json.loads(a['backend'])['backend_id'] for a in attempts] == ['antigravity_cli', 'codex_cli']
    assert attempts[0]['outcome'] == 'QUOTA_EXHAUSTED' and attempts[0]['tests'] == 'NOT_RUN'
    assert attempts[1]['previous_attempt_id'] == first.execution_attempt_id
    assert attempts[1]['reconstruction_sha256'] == digest(manifest().manifest())
    events = query(store, 'SELECT * FROM daio_work_events ORDER BY event_sequence')
    assert [e['event_sequence'] for e in events] == list(range(1, final.event_sequence + 1))
    assert [e['work_revision'] for e in events] == list(range(1, final.work_revision + 1))
    assert store.load_work_item(first.work_id).attempt_count == 0


@pytest.mark.parametrize('status', [DAIOStatus.COMPLETED, DAIOStatus.FROZEN, DAIOStatus.SUPERSEDED,
                                   DAIOStatus.STOP, DAIOStatus.HUMAN_GATE_REQUIRED])
def test_terminal_denied_at_all_legacy_execution_entries(tmp_path, status):
    store = SqliteDAIOWorkStore(str(tmp_path / 'db'))
    item = work(status=status)
    store.save_work_item(item)
    assert store.acquire_lease(item.work_id, 'worker') is None
    assert store.claim_next_available_work_item('worker') is None
    executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path))
    with pytest.raises(SafetyError):
        asyncio.run(executor.execute_task_async(item))
    with pytest.raises(SafetyError):
        executor.execute_task(item)
    with pytest.raises(SafetyError):
        asyncio.run(DAIOClosedLoopOrchestrator(store=store).run_autonomous_loop(item.work_id))
    assert store.load_work_item(item.work_id).status == status
    with pytest.raises(SafetyError):
        DurableHandoff(store).enroll(item.work_id, manifest(), ('codex_cli',))


@pytest.mark.parametrize('kwargs', [dict(metadata={'frozen': True}), dict(metadata={'superseded_by': 'new-work'}),
                                    dict(last_decision='STOP'), dict(current_gate=DAIOGate.HUMAN_GATE)])
def test_explicit_terminal_markers_not_just_status(tmp_path, kwargs):
    store = SqliteDAIOWorkStore(str(tmp_path / 'db'))
    store.save_work_item(work(**kwargs))
    assert store.claim_next_available_work_item('worker') is None
    assert store.acquire_lease('work-test', 'worker') is None
    with pytest.raises(SafetyError):
        asyncio.run(DAIOClosedLoopOrchestrator(store=store).run_autonomous_loop('work-test'))


@pytest.mark.skip(reason="Phase 4E integrates C1.4 into orchestrator/store, lifting restrictions")
def test_enrolled_work_cannot_escape_through_legacy_apis(setup):
    store, ctl, token = setup
    item = store.load_work_item(token.work_id)
    assert store.claim_next_available_work_item('legacy') is None
    assert store.acquire_lease(token.work_id, 'legacy') is None
    with pytest.raises(SafetyError):
        store.save_work_item(item)
    with pytest.raises(SafetyError):
        store.save_work_item(work())  # a stale caller cannot omit the contract marker
    with pytest.raises(SafetyError):
        asyncio.run(DAIOClosedLoopOrchestrator(store=store).run_autonomous_loop(token.work_id))
    with pytest.raises(SafetyError):
        asyncio.run(SubprocessWorkspaceExecutor().execute_task_async(item))
    result = store.apply_decision_transition_atomically(token.work_id, ArchitectDecision('REVISE', 'c1.4-fixture'))
    assert result[1] == 'REJECTED_FENCED_WORK'
    with pytest.raises(SafetyError):
        store.record_turn_history('turn', token.work_id, 'ENGINEERING_EXECUTION', 'bad', 'a'*40, 'SUCCESS', {})
    assert ctl.token(token.work_id) == token


def test_old_attempt_late_result_and_checkpoint_rejected(setup):
    store, ctl, token = setup
    first = prepare(ctl, token)
    cp = checkpoint(ctl, interrupt(ctl, first))
    second = prepare(ctl, cp, CODEX, 'approval-2')
    for stale in [first, cp, replace(second, fencing_token=0), replace(second, execution_attempt_id=first.execution_attempt_id)]:
        with pytest.raises(StaleExecution):
            ctl.publish_outcome(stale, ExecutionOutcome(Outcome.SUCCESS), 'c'*64)
    assert ctl.token(second.work_id) == second


def test_unknown_quiescence_blocks_checkpoint_and_replacement(setup):
    _, ctl, token = setup
    token = interrupt(ctl, prepare(ctl, token))
    with pytest.raises(SafetyError, match='UNKNOWN'):
        ctl.confirm_quiescence(token, lambda attempt: QuiescenceReceipt(attempt, 'UNKNOWN', 'receipt', 'PROCESS_GROUP_EXITED'))
    with pytest.raises(SafetyError):
        ctl.publish_checkpoint(token, manifest)
    with pytest.raises(SafetyError):
        ctl.authorize_backend(token, CODEX, 'approval-2')
    assert ctl.token(token.work_id) == token


def test_checkpoint_is_immutable_and_atomic_on_event_failure(setup):
    store, ctl, token = setup
    token = ctl.confirm_quiescence(interrupt(ctl, prepare(ctl, token)), lambda attempt: QuiescenceReceipt(attempt, 'TERMINATED', 'receipt', 'VERIFIED_NOT_STARTED'))
    before = query(store, 'SELECT * FROM daio_checkpoints')
    conn = store._get_connection()
    conn.execute("CREATE TRIGGER fail_publish BEFORE INSERT ON daio_work_events WHEN NEW.event='CHECKPOINT_PUBLISHED' BEGIN SELECT RAISE(ABORT,'fault'); END")
    conn.close()
    with pytest.raises(sqlite3.IntegrityError):
        ctl.publish_checkpoint(token, manifest)
    assert query(store, 'SELECT * FROM daio_checkpoints') == before
    assert ctl.token(token.work_id) == token
    conn = store._get_connection()
    conn.execute('DROP TRIGGER fail_publish')
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        conn.execute("UPDATE daio_checkpoints SET payload='{}'")
    conn.rollback()
    conn.close()
    ctl.publish_checkpoint(token, manifest)


@pytest.mark.parametrize('field', ['head_sha', 'workspace_sha256', 'policy_sha256', 'scope_sha256', 'frozen_sha256', 'evidence_sha256'])
def test_reconstruction_independently_measured_not_agent_assertion(setup, field):
    _, ctl, token = setup
    token = ctl.begin_attempt(ctl.authorize_backend(token, AGY, 'approval'), 'worker')
    handoff = ctl.handoff(token)
    ack = ReconstructionAck(token, handoff['checkpoint_id'], handoff['checkpoint_sha256'], digest(handoff['manifest']))
    wrong = replace(manifest(), **{field: 'd' * (40 if field == 'head_sha' else 64)})
    with pytest.raises(SafetyError, match='mismatch'):
        ctl.acknowledge(ack, lambda: wrong)
    with pytest.raises(SafetyError):
        ctl.start_execution(token, manifest)
    assert ctl.token(token.work_id) == token


def test_wrong_ack_and_workspace_change_after_ack_fail_closed(setup):
    _, ctl, token = setup
    token = ctl.begin_attempt(ctl.authorize_backend(token, AGY, 'approval'), 'worker')
    h = ctl.handoff(token)
    ack = ReconstructionAck(token, h['checkpoint_id'], '0'*64, digest(h['manifest']))
    with pytest.raises(SafetyError):
        ctl.acknowledge(ack, manifest)
    token = ctl.acknowledge(replace(ack, checkpoint_sha256=h['checkpoint_sha256']), manifest)
    with pytest.raises(SafetyError):
        ctl.start_execution(token, lambda: replace(manifest(), workspace_sha256='d'*64))


@pytest.mark.parametrize('outcome', [Outcome.BACKEND_UNAVAILABLE, Outcome.QUOTA_EXHAUSTED, Outcome.AUTHENTICATION_REQUIRED])
def test_capacity_never_test_failure(setup, outcome):
    store, ctl, token = setup
    token = prepare(ctl, token)
    with pytest.raises(SafetyError):
        ctl.publish_outcome(token, ExecutionOutcome(outcome, TestStatus.FAILED))
    ctl.publish_outcome(token, ExecutionOutcome(outcome))
    assert store.load_work_item(token.work_id).attempt_count == 0
    row = query(store, 'SELECT outcome,tests FROM daio_backend_attempts')[0]
    assert row == {'outcome': outcome.value, 'tests': 'NOT_RUN'}


def test_competing_controllers_only_one_publication_wins(setup):
    store, ctl, token = setup
    def authorize(n):
        local = DurableHandoff(SqliteDAIOWorkStore(store.db_path))
        try:
            return local.authorize_backend(token, AGY, 'approval-' + str(n))
        except StaleExecution:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(authorize, [1, 2]))
    assert sum(r is not None for r in results) == 1
    assert len(query(store, 'SELECT * FROM daio_backend_authorizations')) == 1


def test_policy_and_distinct_manual_ide_backend(setup):
    _, ctl, token = setup
    with pytest.raises(SafetyError):
        ctl.authorize_backend(token, replace(CODEX, backend_id='codex_ide_manual'), 'approval')
    manual = BackendIdentity('codex_ide_manual', 'CodexIDEManual', '1', 'MANUAL')
    token = ctl.authorize_backend(token, manual, 'manual-approval')
    with pytest.raises(SafetyError, match='not automatable'):
        ctl.begin_attempt(token, 'worker')


def test_no_automatic_selection_or_replayed_authorization(setup):
    _, ctl, token = setup
    with pytest.raises(SafetyError):
        ctl.begin_attempt(token, 'worker')
    cp = checkpoint(ctl, interrupt(ctl, prepare(ctl, token)))
    with pytest.raises(sqlite3.IntegrityError):
        ctl.authorize_backend(cp, CODEX, 'approval-1')
    assert ctl.token(cp.work_id) == cp


@pytest.mark.parametrize('status', ['STOP', 'FROZEN', 'SUPERSEDED', 'HUMAN_GATE_REQUIRED'])
def test_policy_revocation_fences_inflight_attempt(setup, status):
    _, ctl, token = setup
    token = prepare(ctl, token)
    stopped = ctl.stop(token, status)
    assert stopped.fencing_token == token.fencing_token + 1
    with pytest.raises(StaleExecution):
        ctl.publish_outcome(token, ExecutionOutcome(Outcome.SUCCESS), 'c'*64)
    with pytest.raises(SafetyError):
        ctl.authorize_backend(stopped, CODEX, 'approval-2')


def test_machine_codes_only_and_no_secret_error_echo():
    assert classify_failure({'error': {'code': 'QUOTA_EXHAUSTED', 'message': 'secret-fixture'}}) == Outcome.QUOTA_EXHAUSTED
    assert classify_failure('429 secret-fixture quota exhausted') == Outcome.UNKNOWN_FAILURE
    assert classify_failure({'error_code': 'RESOURCE_EXHAUSTED'}) == Outcome.UNKNOWN_FAILURE


def test_completed_steps_cannot_be_replayed():
    with pytest.raises(SafetyError):
        replace(manifest(), next_step='contract-approved').validate()


def test_expired_lease_cannot_publish_or_renew(setup):
    store, ctl, token = setup
    token = prepare(ctl, token)
    # Test-only fault injection into the disposable database.
    conn = store._get_connection()
    conn.execute("UPDATE daio_work_items SET lease_expires_at='2000-01-01T00:00:00+00:00'")
    conn.commit(); conn.close()
    with pytest.raises(StaleExecution):
        ctl.publish_outcome(token, ExecutionOutcome(Outcome.SUCCESS), 'c'*64)
    with pytest.raises(StaleExecution):
        ctl.renew(token)


def test_legacy_executor_capacity_result_does_not_run_tests(tmp_path):
    class Unavailable:
        async def propose_task_solution(self, request):
            return AgentTaskProposal(request.work_id, False, outcome=Outcome.QUOTA_EXHAUSTED)
    executor = SubprocessWorkspaceExecutor(str(tmp_path), Unavailable())
    executor.get_current_head = lambda: 'a'*40
    executor.capture_workspace_snapshot = lambda: {}
    executor.run_cmd = lambda _: pytest.fail('Tests/commands must not run after capacity failure')
    item = work(project_root=str(tmp_path), requested_action='propose a change')
    result = asyncio.run(executor.execute_task_async(item))
    assert result.outcome == Outcome.QUOTA_EXHAUSTED and result.test_status == TestStatus.NOT_RUN


def test_orchestrator_preserves_capacity_and_test_budget(tmp_path):
    class Unavailable:
        async def execute_task_async(self, **kwargs):
            return ExecutionResult(False, False, outcome=Outcome.AUTHENTICATION_REQUIRED)
    store = SqliteDAIOWorkStore(str(tmp_path/'db'))
    store.save_work_item(work())
    result = asyncio.run(DAIOClosedLoopOrchestrator(store=store, executor=Unavailable()).run_autonomous_loop('work-test'))
    assert result.status == DAIOStatus.WAITING_FOR_EXECUTION_CAPACITY
    assert result.attempt_count == 0
    assert result.metadata['test_status'] == 'NOT_RUN'


def test_process_termination_verifier_requires_reaped_owned_group():
    import os
    import subprocess
    import sys
    from scripts.daio_closed_loop.quiescence import verify_process_group_exit
    if os.name != 'posix':
        pytest.skip('POSIX process group contract')
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    try:
        assert verify_process_group_exit('attempt-test', proc, 'receipt').state == 'UNKNOWN'
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    receipt = verify_process_group_exit('attempt-test', proc, 'receipt')
    receipt.validate('attempt-test')
    with pytest.raises(SafetyError):
        receipt.validate('attempt-other')


def test_wrong_quiescence_attempt_rejected(setup):
    _, ctl, token = setup
    token = interrupt(ctl, prepare(ctl, token))
    with pytest.raises(SafetyError):
        ctl.confirm_quiescence(token, lambda _: QuiescenceReceipt('wrong-attempt', 'TERMINATED', 'receipt', 'PROCESS_GROUP_EXITED'))


def test_workspace_change_after_interruption_requires_reconciliation(setup):
    _, ctl, token = setup
    token = ctl.confirm_quiescence(interrupt(ctl, prepare(ctl, token)),
                                   lambda a: QuiescenceReceipt(a, 'TERMINATED', 'receipt', 'VERIFIED_NOT_STARTED'))
    with pytest.raises(SafetyError, match='reconcile'):
        ctl.publish_checkpoint(token, lambda: replace(manifest(), workspace_sha256='e'*64))
    assert ctl.token(token.work_id) == token


def test_backend_outside_policy_denied(tmp_path):
    store = SqliteDAIOWorkStore(str(tmp_path/'db'))
    store.save_work_item(work())
    ctl = DurableHandoff(store)
    token = ctl.enroll('work-test', manifest(), ('antigravity_cli',))
    with pytest.raises(SafetyError, match='not authorized'):
        ctl.authorize_backend(token, CODEX, 'approval')


@pytest.mark.parametrize('outcome', [Outcome.ENGINEERING_FAILURE, Outcome.UNKNOWN_FAILURE])
def test_non_test_failures_do_not_consume_test_budget(tmp_path, outcome):
    class Failed:
        async def execute_task_async(self, **kwargs):
            return ExecutionResult(False, False, outcome=outcome)
    store = SqliteDAIOWorkStore(str(tmp_path/'db'))
    store.save_work_item(work())
    result = asyncio.run(DAIOClosedLoopOrchestrator(store=store, executor=Failed()).run_autonomous_loop('work-test'))
    assert result.status == DAIOStatus.BLOCKED and result.attempt_count == 0
    assert result.metadata['execution_outcome'] == outcome.value


def test_additive_migration_preserves_legacy_frozen_work(tmp_path):
    path = str(tmp_path/'old.db')
    seed = SqliteDAIOWorkStore(path)
    seed.save_work_item(work(status=DAIOStatus.COMPLETED, last_decision='APPROVE', metadata={'frozen': True}))
    conn = sqlite3.connect(path)
    # Model the pre-C1.4 schema in a disposable fixture, never production SQLite.
    cols = [r for r in conn.execute('PRAGMA table_info(daio_work_items)')
            if r[1] not in {'work_revision','event_sequence','fencing_token','handoff_contract'}]
    definition = ','.join(r[1]+' '+r[2]+(' PRIMARY KEY' if r[5] else '') for r in cols)
    names = ','.join(r[1] for r in cols)
    conn.execute('CREATE TABLE old_work('+definition+')')
    conn.execute('INSERT INTO old_work SELECT '+names+' FROM daio_work_items')
    conn.execute('DROP TABLE daio_work_items')
    conn.execute('ALTER TABLE old_work RENAME TO daio_work_items')
    before = conn.execute('SELECT '+names+' FROM daio_work_items').fetchone()
    conn.commit(); conn.close()
    upgraded = SqliteDAIOWorkStore(path)
    conn = sqlite3.connect(path)
    assert conn.execute('SELECT '+names+' FROM daio_work_items').fetchone() == before
    conn.close()
    loaded = upgraded.load_work_item('work-test')
    assert loaded.work_revision == loaded.event_sequence == loaded.fencing_token == 0
    assert loaded.handoff_contract is None
    assert upgraded.claim_next_available_work_item('worker') is None


@pytest.mark.parametrize('adapter_name', ['antigravity_cli_agent', 'codex_cli_agent'])
def test_cli_capacity_normalization_omits_raw_provider_secrets(adapter_name):
    from importlib import import_module
    from unittest.mock import AsyncMock, patch
    from scripts.daio_closed_loop.adapters.agent_contract import AgentTaskRequest
    module = import_module('scripts.daio_closed_loop.adapters.'+adapter_name)
    adapter_class = module.AntigravityCLIAdapter if adapter_name.startswith('antigravity') else module.CodexCLIAdapter
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (b'{"error":{"code":"QUOTA_EXHAUSTED","message":"secret-fixture"}}', b'secret-fixture')
    async def run():
        with patch('asyncio.create_subprocess_exec', return_value=proc):
            return await adapter_class(cli_path='/fake/provider').propose_task_solution(
                AgentTaskRequest('work-test','c1.4','propose','/unused'))
    proposal = asyncio.run(run())
    assert proposal.outcome == Outcome.QUOTA_EXHAUSTED
    assert not proposal.raw_response and 'secret-fixture' not in proposal.error_message
