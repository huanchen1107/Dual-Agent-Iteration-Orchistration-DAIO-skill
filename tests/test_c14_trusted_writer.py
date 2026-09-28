"""Disposable Git/SQLite trusted apply acceptance, never executes candidate code."""
from dataclasses import replace
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest

from scripts.daio_closed_loop.trusted_writer import TrustedWriter, WriterBusy, VERSION, sha
from scripts.daio_closed_loop.handoff_contract import SafetyError, StaleExecution


def git(repo,*args):
    return subprocess.check_output(['/usr/bin/git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',
                                    '-c','user.name=Fixture','-c','user.email=fixture@invalid','-C',str(repo),*args],stderr=subprocess.DEVNULL)


@pytest.fixture
def fixture(tmp_path):
    repo=tmp_path/'repo'; repo.mkdir()
    git(repo,'init','-q')
    (repo/'src').mkdir()
    (repo/'src/a.txt').write_text('before A\n')
    (repo/'src/b.txt').write_text('before B\n')
    (repo/'frozen.txt').write_text('frozen\n')
    git(repo,'add','.'); git(repo,'commit','-qm','baseline')
    writer=TrustedWriter(repo.resolve(),(tmp_path/'state').resolve())
    token=writer.register('work-3b2','attempt-A','approval-A',['src/a.txt','src/b.txt','frozen.txt'],['frozen.txt'])
    return writer,token,tmp_path


def proposal(writer,paths=('src/a.txt',)):
    return json.dumps({'version':VERSION,'changes':[{'path':p,'expected_sha256':sha((writer.repo/p).read_bytes()),
                         'content':'accepted '+p+'\n'} for p in paths]}).encode()


def seal(fixture,paths=('src/a.txt',)):
    writer,token,_=fixture
    return writer.ingest(token,proposal(writer,paths))


def test_normal_apply_and_backend_path_toctou(fixture):
    writer,token,root=fixture
    backend=root/'backend-proposal.json'
    backend.write_bytes(proposal(writer))
    accepted=backend.read_bytes()
    token,artifact,digest=writer.ingest(token,accepted)
    backend.write_text('{"command":"do not execute"}')
    before_head=git(writer.repo,'rev-parse','HEAD')
    final=writer.apply(token,artifact,digest)
    assert (writer.repo/'src/a.txt').read_text()=='accepted src/a.txt\n'
    assert (writer.repo/'src/b.txt').read_text()=='before B\n'
    assert (writer.repo/'frozen.txt').read_text()=='frozen\n'
    assert git(writer.repo,'rev-parse','HEAD')==before_head  # COMMITTED is journal, not Git commit.
    assert writer.journals()[0]['state']=='COMMITTED'
    assert final.work_revision==token.work_revision+1
    with pytest.raises(SafetyError): writer.apply(final,artifact,digest)
    conn=sqlite3.connect(writer.db)
    phases=[r[0] for r in conn.execute('SELECT state FROM journal_events ORDER BY id')]
    assert phases==['PREPARED','APPLYING','APPLIED','COMMITTED']
    with pytest.raises(sqlite3.IntegrityError): conn.execute('UPDATE artifacts SET payload=?',(b'corrupt',))
    with pytest.raises(sqlite3.IntegrityError): conn.execute("UPDATE applies SET state='APPLYING'")
    conn.close()
    (root/'report.json').write_text(json.dumps({'result':'COMMITTED','artifact_id':artifact,'artifact_sha256':digest,
        'work_id':token.work_id,'attempt':token.execution_attempt_id,'fence':token.fencing_token,
        'journal_phases':phases,'baseline_head':before_head.decode().strip(),'final_revision':final.work_revision,
        'backend_path_mutation_ignored':True,'head_unchanged':True,'tests_executed_by_writer':False},indent=2))


def test_hash_mismatch(fixture):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    with pytest.raises(SafetyError): writer.apply(token,artifact,'0'*64)
    assert not writer.journals()
    assert (writer.repo/'src/a.txt').read_text()=='before A\n'


@pytest.mark.parametrize('field,value',[('work_id','wrong'),('execution_attempt_id','old'),('fencing_token',99),
                                       ('work_revision',99),('event_sequence',99)])
def test_wrong_publication_identity(fixture,field,value):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    with pytest.raises(StaleExecution): writer.apply(replace(token,**{field:value}),artifact,digest)
    assert not writer.journals()


@pytest.mark.parametrize('action',['REVOKE','REPLACE','COMPLETE'])
def test_old_artifact_after_authority_transition(fixture,action):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    current=writer.authority_transition(token,action,'approval-transition','attempt-B' if action=='REPLACE' else None)
    with pytest.raises(SafetyError): writer.apply(token,artifact,digest)
    with pytest.raises(SafetyError): writer.apply(current,artifact,digest)
    assert (writer.repo/'src/a.txt').read_text()=='before A\n'


@pytest.mark.parametrize('drift',['head','dirty','untracked','staged','mode','identity'])
def test_baseline_drift(fixture,drift):
    writer,_,root=fixture; token,artifact,digest=seal(fixture)
    if drift=='head': git(writer.repo,'commit','--allow-empty','-qm','head moved')
    if drift=='dirty': (writer.repo/'src/b.txt').write_text('human change')
    if drift=='untracked': (writer.repo/'new.txt').write_text('new')
    if drift=='staged':
        (writer.repo/'src/b.txt').write_text('staged'); git(writer.repo,'add','src/b.txt')
        (writer.repo/'src/b.txt').write_text('before B\n')
    if drift=='mode': (writer.repo/'src/b.txt').chmod(0o755)
    if drift=='identity':
        writer.repo.rename(root/'oldrepo')
        import shutil
        shutil.copytree(root/'oldrepo',writer.repo)
    with pytest.raises(SafetyError): writer.apply(token,artifact,digest)
    assert not writer.journals()


def test_frozen_path_current_authority(fixture):
    writer,_,_=fixture; token,artifact,digest=seal(fixture,('frozen.txt',))
    with pytest.raises(SafetyError): writer.apply(token,artifact,digest)
    assert (writer.repo/'frozen.txt').read_text()=='frozen\n'


@pytest.mark.parametrize('path',['/tmp/out','../out','src/../../out','.git/config','_daio/state.db',
                                'credentials/key','src/.env','src//a.txt','src/./a.txt','src\\a.txt'])
def test_forbidden_path(fixture,path):
    writer,token,_=fixture
    payload=json.dumps({'version':VERSION,'changes':[{'path':path,'expected_sha256':'a'*64,'content':'bad'}]}).encode()
    with pytest.raises(SafetyError): writer.ingest(token,payload)


@pytest.mark.parametrize('escape',['symlink-file','symlink-dir','hardlink'])
def test_link_escape(fixture,escape):
    writer,_,root=fixture; token,artifact,digest=seal(fixture)
    outside=root/'outside'; outside.write_text('outside sentinel')
    if escape=='symlink-file':
        (writer.repo/'src/a.txt').unlink(); (writer.repo/'src/a.txt').symlink_to(outside)
    elif escape=='symlink-dir':
        (writer.repo/'src').rename(root/'oldsrc'); (writer.repo/'src').symlink_to(root/'oldsrc')
    else:
        (writer.repo/'src/a.txt').unlink(); os.link(outside,writer.repo/'src/a.txt')
    with pytest.raises((OSError,SafetyError)): writer.apply(token,artifact,digest)
    assert outside.read_text()=='outside sentinel'


def crashing_apply(repo,control,token,artifact,digest,stage):
    writer=TrustedWriter(repo,control)
    def crash(point):
        if point==stage: os._exit(73)
    writer.apply(token,artifact,digest,crash)


@pytest.mark.parametrize('stage,expected',[('PREPARED','RECONCILIATION_REQUIRED'),('APPLYING','RECONCILIATION_REQUIRED'),
                                         ('STAGED_0','RECONCILIATION_REQUIRED'),
                                         ('FILE_0','RECONCILIATION_REQUIRED'),('FILE_1','COMMITTED'),
                                         ('APPLIED','COMMITTED'),('COMMITTED','COMMITTED')])
def test_real_process_crash_restart(fixture,stage,expected):
    writer,_,_=fixture; token,artifact,digest=seal(fixture,('src/a.txt','src/b.txt'))
    ctx=multiprocessing.get_context('fork')
    proc=ctx.Process(target=crashing_apply,args=(writer.repo,writer.control,token,artifact,digest,stage))
    proc.start(); proc.join(10); assert proc.exitcode==73
    restarted=TrustedWriter(writer.repo,writer.control)
    journal=restarted.journals()[0]
    if stage!='COMMITTED':
        for action in ['REVOKE','REPLACE','COMPLETE']:
            with pytest.raises(SafetyError): restarted.authority_transition(token,action,'blocked-'+action,'attempt-B')
    bytes_before={p:(writer.repo/p).read_bytes() for p in ['src/a.txt','src/b.txt']}
    assert restarted.reconcile(journal['apply_id'])==expected
    if stage!='COMMITTED':
        conn=sqlite3.connect(writer.db)
        observation=conn.execute('SELECT classification FROM reconciliation_observations ORDER BY id DESC').fetchone()[0]
        conn.close()
        assert observation=={'PREPARED':'NOT_APPLIED','APPLYING':'NOT_APPLIED','STAGED_0':'STAGING_REMAINS',
                             'FILE_0':'PARTIALLY_APPLIED','FILE_1':'FULLY_APPLIED','APPLIED':'FULLY_APPLIED'}[stage]
    assert {p:(writer.repo/p).read_bytes() for p in bytes_before}==bytes_before  # No replay.
    if expected=='RECONCILIATION_REQUIRED':
        with pytest.raises(SafetyError): restarted.apply(token,artifact,digest)
        with pytest.raises(SafetyError): restarted.authority_transition(token,'REVOKE','still-blocked')
    else:
        assert (writer.repo/'src/a.txt').read_text()=='accepted src/a.txt\n'
        current=restarted.token(token.work_id)
        restarted.authority_transition(current,'REVOKE','after-reconcile')


def hold_apply(repo,control,token,artifact,digest,entered,release):
    writer=TrustedWriter(repo,control)
    def pause(stage):
        if stage=='PREPARED':
            entered.set()
            assert release.wait(10)
    writer.apply(token,artifact,digest,pause)


def test_concurrent_writer_and_apply_wins_revocation_race(fixture):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    ctx=multiprocessing.get_context('fork'); entered=ctx.Event(); release=ctx.Event()
    proc=ctx.Process(target=hold_apply,args=(writer.repo,writer.control,token,artifact,digest,entered,release))
    proc.start()
    try:
        assert entered.wait(10)
        with pytest.raises(WriterBusy): writer.apply(token,artifact,digest)
        with pytest.raises(WriterBusy): writer.authority_transition(token,'REVOKE','racing-revoke')
    finally:
        release.set(); proc.join(10)
    assert proc.exitcode==0
    assert writer.journals()[0]['state']=='COMMITTED'
    with pytest.raises(StaleExecution): writer.authority_transition(token,'REVOKE','stale-revoke')
    writer.authority_transition(writer.token(token.work_id),'REVOKE','reconciled-revoke')


def test_revocation_wins_apply_race(fixture):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    writer.authority_transition(token,'REVOKE','revoke-first')
    ctx=multiprocessing.get_context('fork')
    # Competing late apply is explicitly rejected without filesystem mutation.
    with pytest.raises(StaleExecution): writer.apply(token,artifact,digest)
    assert not writer.journals()


def test_commands_and_candidate_code_never_executed(fixture):
    writer,token,root=fixture
    with pytest.raises(SafetyError): writer.ingest(token,json.dumps({'version':VERSION,'changes':[], 'command':'touch bad'}).encode())
    payload={'version':VERSION,'changes':[{'path':'src/a.txt','expected_sha256':sha((writer.repo/'src/a.txt').read_bytes()),
               'content':'#!/bin/sh\ntouch '+str(root/'MUST_NOT_EXIST')+'\n'}]}
    token,artifact,digest=writer.ingest(token,json.dumps(payload).encode())
    writer.apply(token,artifact,digest)
    assert not (root/'MUST_NOT_EXIST').exists()


def test_second_controller_database_cannot_bypass_journal(fixture):
    writer,_,root=fixture
    with pytest.raises(SafetyError): TrustedWriter(writer.repo,(root/'other-state').resolve())


@pytest.mark.parametrize('drift',['head','index','bytes'])
def test_recovery_rejects_post_crash_drift(fixture,drift):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    ctx=multiprocessing.get_context('fork')
    proc=ctx.Process(target=crashing_apply,args=(writer.repo,writer.control,token,artifact,digest,'APPLIED'))
    proc.start(); proc.join(10); assert proc.exitcode==73
    if drift=='head': git(writer.repo,'commit','--allow-empty','-qm','changed after crash')
    if drift=='index': git(writer.repo,'add','src/a.txt')
    if drift=='bytes': (writer.repo/'src/a.txt').write_text('not the accepted bytes')
    restarted=TrustedWriter(writer.repo,writer.control)
    assert restarted.reconcile(writer.journals()[0]['apply_id'])=='RECONCILIATION_REQUIRED'
    with pytest.raises(SafetyError): restarted.authority_transition(token,'REVOKE','blocked')


def test_sealed_storage_corruption_fails_closed(fixture):
    writer,_,_=fixture; token,artifact,digest=seal(fixture)
    # Trusted test fault injection simulates damaged storage, not a backend capability.
    conn=sqlite3.connect(writer.db)
    conn.execute('DROP TRIGGER immutable_artifact_update')
    conn.execute('UPDATE artifacts SET payload=? WHERE artifact_id=?',(b'{}',artifact))
    conn.commit(); conn.close()
    with pytest.raises(SafetyError): writer.apply(token,artifact,digest)
    assert not writer.journals()


@pytest.mark.parametrize('kind',['scope','file_hash','duplicate','command_field'])
def test_declarative_policy_validation(fixture,kind):
    writer,token,_=fixture
    payload=json.loads(proposal(writer))
    if kind=='scope':
        # Existing tracked file excluded by a separate trusted policy fixture.
        other=writer.register('work-restricted','attempt-R','restricted',['src/b.txt'])
        token=other
    if kind=='file_hash': payload['changes'][0]['expected_sha256']='0'*64
    if kind=='duplicate': payload['changes']*=2
    if kind=='command_field': payload['changes'][0]['command']='never execute'
    with pytest.raises(SafetyError):
        current,artifact,digest=writer.ingest(token,json.dumps(payload).encode())
        writer.apply(current,artifact,digest)
    assert not writer.journals()
