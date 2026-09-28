"""Phase-3 containment gate: characterize escaped descendant, never accept it."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts.daio_closed_loop.quiescence import verify_process_group_exit
from scripts.daio_closed_loop.handoff import DurableHandoff
from scripts.daio_closed_loop.handoff_contract import (
    BackendIdentity, ExecutionOutcome, Outcome, Reconstruction, ReconstructionAck,
    QuiescenceReceipt, SafetyError, digest,
)
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOGate, DAIORole
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Disposable process handshake timed out')


def identity(pid):
    # Only process identity fields for our known disposable PIDs; no command/env.
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'pid=,ppid=,pgid=,lstart=,stat='],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip()


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin Phase-3 containment gate')
def test_escaped_descendant_blocks_phase3_acceptance(tmp_path):
    child_script = tmp_path / 'child.py'
    child_script.write_text('''import json, os, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
(root / "child-ready.json").write_text(json.dumps({"pid": os.getpid(), "pgid": os.getpgrp()}))
deadline = time.monotonic() + 20
while time.monotonic() < deadline and not (root / "child-stop").exists():
    time.sleep(0.02)
(root / "child-finished").write_text("finished")
''')
    parent_script = tmp_path / 'parent.py'
    parent_script.write_text('''import pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
subprocess.Popen([sys.executable, str(root / "child.py"), str(root)],
                 start_new_session=True, stdin=subprocess.DEVNULL,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 15
while time.monotonic() < deadline and not (root / "parent-exit").exists():
    time.sleep(0.02)
''')
    parent = subprocess.Popen([sys.executable, str(parent_script), str(tmp_path)],
                              start_new_session=True, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child = None
    try:
        ready = tmp_path / 'child-ready.json'
        wait_for(lambda: ready.exists() and bool(ready.read_text()))
        child = json.loads(ready.read_text())
        parent_identity = identity(parent.pid)
        child_identity = identity(child['pid'])
        assert child['pgid'] != parent.pid
        assert os.getpgid(child['pid']) == child['pgid']
        (tmp_path / 'parent-exit').touch()
        assert parent.wait(timeout=5) == 0
        with pytest.raises(ProcessLookupError):
            os.killpg(parent.pid, 0)
        # A new session escaped the original group and remains observably alive.
        os.kill(child['pid'], 0)
        escaped_identity = identity(child['pid'])
        assert escaped_identity and not (tmp_path / 'child-finished').exists()
        receipt = verify_process_group_exit('attempt-escape', parent, 'group-only-observation')
        assert receipt.state == 'TERMINATED'  # Characterizes the unsafe existing helper.

        # Do not publish that insufficient receipt. The integration host fails closed.
        store = SqliteDAIOWorkStore(str(tmp_path / 'disposable.db'))
        work = DAIOWorkItem(work_id='c14-phase3-escape-gate', project_root=str(tmp_path),
                            change_id='c14-phase3-fixture', current_gate=DAIOGate.ENGINEERING_TASK,
                            assigned_role=DAIORole.ENGINEERING_EXECUTION)
        store.save_work_item(work)
        ctl = DurableHandoff(store)
        manifest = Reconstruction('inert-fixture', 'a'*40, *(['b'*64]*5), (), 'inert-proposal')
        a = BackendIdentity('antigravity_cli', 'AntigravityCLIAdapter', 'inert-test', 'CLI')
        b = BackendIdentity('codex_cli', 'CodexCLIAdapter', 'inert-test', 'CLI')
        token = ctl.enroll(work.work_id, manifest, (a.backend_id, b.backend_id))
        token = ctl.authorize_backend(token, a, 'manual-inert-A')
        token = ctl.begin_attempt(token, 'inert-controller')
        packet = ctl.handoff(token)
        token = ctl.acknowledge(ReconstructionAck(token, packet['checkpoint_id'], packet['checkpoint_sha256'],
                                                digest(packet['manifest'])), lambda: manifest)
        token = ctl.start_execution(token, lambda: manifest)
        token = ctl.publish_outcome(token, ExecutionOutcome(Outcome.BACKEND_UNAVAILABLE))
        unknown = QuiescenceReceipt(token.execution_attempt_id, 'UNKNOWN', 'escape-observed', 'PROCESS_GROUP_EXITED')
        with pytest.raises(SafetyError):
            ctl.confirm_quiescence(token, lambda attempt: unknown)
        with pytest.raises(SafetyError):
            ctl.authorize_backend(token, b, 'blocked-B')
        assert ctl.token(work.work_id) == token
        report = dict(phase3_result='BLOCKED_CONTAINMENT_GATE', platform=sys.platform,
                      parent_pid=parent.pid, parent_identity=parent_identity,
                      child_pid=child['pid'], child_pgid=child['pgid'], child_identity=child_identity,
                      escaped_identity_after_parent_exit=escaped_identity, parent_returncode=parent.returncode,
                      original_process_group_gone=True, escaped_descendant_alive=True,
                      existing_group_verifier_receipt=receipt.state,
                      accepted_quiescence='UNKNOWN', backend_b_blocked=True,
                      production_verifier_gap='Process-group disappearance does not prove descendant termination',
                      work_id=work.work_id, current_attempt=token.execution_attempt_id,
                      revision=token.work_revision, event_sequence=token.event_sequence,
                      remaining_scenarios='NOT_RUN: stop on containment failure')
    finally:
        (tmp_path / 'child-stop').touch()
        (tmp_path / 'parent-exit').touch()
        parent.wait(timeout=5)
        if child is not None:
            wait_for(lambda: (tmp_path / 'child-finished').exists())
            # Reparented children are reaped by the OS; require disappearance too.
            wait_for(lambda: not identity(child['pid']))
    report['cleanup'] = 'Parent reaped; child completion observed and PID absent'
    (tmp_path / 'escape-report.json').write_text(json.dumps(report, indent=2) + '\n')
