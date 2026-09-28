"""Darwin-only disposable Route-B feasibility; no provider or production state."""
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import pytest

FIXTURES = Path(__file__).parent / 'fixtures'
PYTHON = Path('/Library/Developer/CommandLineTools/usr/bin/python3').resolve()


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Authority experiment handshake timed out')


def receive(fd):
    result = b''
    deadline = time.monotonic() + 10
    while not result.endswith(b'\n'):
        assert select.select([fd], [], [], max(0, deadline-time.monotonic()))[0], 'Controller response timeout'
        chunk = os.read(fd, 1)
        assert chunk, 'Controller channel closed'
        result += chunk
    return json.loads(result)


def send(fd, value):
    os.write(fd, (json.dumps(value) + '\n').encode())


def process_identity(pid):
    return subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,pgid=,lstart=,stat='],
                          capture_output=True, text=True, check=False).stdout.strip()


def profile_for(scratch):
    read_paths = ['/', '/Library', '/Library/Developer', '/dev/null', '/dev/random', '/dev/urandom']
    # Runtime ancestor directory reads; no recursive access to their children.
    read_paths += [str(p) for p in scratch.parents]
    rules = ' '.join('(literal ' + json.dumps(p) + ')' for p in sorted(set(read_paths)))
    rules += ' '.join('(subpath ' + json.dumps(p) + ')' for p in
                      ['/System', '/usr', '/bin', '/Library/Developer/CommandLineTools', str(scratch)])
    return ('(version 1)(deny default)\n(allow process-exec process-fork)\n'
            '(allow sysctl-read)\n(allow file-read* ' + rules + ')\n'
            '(allow file-write* (subpath ' + json.dumps(str(scratch)) + ') (literal "/dev/null"))\n')


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin native authority feasibility gate')
def test_native_authority_survives_descendant_escape_and_controller_restart(tmp_path):
    root = tmp_path.resolve()
    authority = root / 'authoritative'
    scratch = root / 'scratch'
    authority.mkdir(); scratch.mkdir()
    (scratch / 'home').mkdir(); (scratch / 'tmp').mkdir()
    artifacts = authority / 'artifacts'; artifacts.mkdir()
    sentinels = {}
    for name, relative in [('repository','repo/file.txt'), ('git','repo/.git/config'),
                           ('control','control/state.txt'), ('freeze','control/freeze.json'),
                           ('acceptance','control/acceptance.json'), ('authorization','control/authorization.json'),
                           ('credential','synthetic-home/credential.txt'), ('session','synthetic-home/session.txt'),
                           ('writer_control','writer-control.txt'), ('artifact','artifacts/sealed-fixture.json')]:
        path = authority / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('SYNTHETIC-' + name + '-' + os.urandom(8).hex())
        sentinels[name] = str(path)
    before = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name,path in sentinels.items()}
    db = authority / 'control' / 'authority.db'
    conn = sqlite3.connect(db)
    conn.executescript('''CREATE TABLE authority(work_id TEXT,execution_attempt_id TEXT,fencing_token INTEGER,
        work_revision INTEGER,event_sequence INTEGER,authority_state TEXT);
        INSERT INTO authority VALUES('c14-3b1-inert','attempt-inert-A',1,0,0,'AUTHORIZED');
        CREATE TABLE events(sequence INTEGER PRIMARY KEY,event TEXT);
        CREATE TABLE proposals(sha TEXT PRIMARY KEY,attempt TEXT);''')
    conn.commit(); conn.close()
    sentinels['sqlite'] = str(db)
    (scratch / 'snapshot.txt').write_text('Allowlisted inert snapshot, no real project data.\n')
    (scratch / 'symlink-to-authority').symlink_to(sentinels['repository'])
    shutil.copyfile(FIXTURES / 'c14_authority_backend.py', scratch / 'backend.py')
    profile = profile_for(scratch)
    profile_path = authority / 'boundary.sb'; profile_path.write_text(profile)
    # Use a short-path tmpdir under /tmp for the AF_UNIX socket to stay within
    # macOS's 104-character path limit, regardless of where the repo is checked out.
    _sock_tmp = tempfile.mkdtemp(prefix='c14auth')
    sock_path = os.path.join(_sock_tmp, 'w.sock')
    assert len(sock_path) <= 104, f'AF_UNIX path still too long: {len(sock_path)} chars'
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path); server.listen(1)
    req_r, req_w = os.pipe()
    res_r, res_w = os.pipe()
    ctl_r, ctl_w = os.pipe()
    ack_r, ack_w = os.pipe()
    host_fd = os.open(sentinels['repository'], os.O_RDWR)
    os.set_inheritable(host_fd, True)  # Deliberate launch-cleanup challenge.
    os.set_inheritable(server.fileno(), True)
    os.set_inheritable(ctl_w, True)
    for fd in (req_w, res_r):
        os.set_inheritable(fd, True)
    config = dict(sentinels=sentinels, writer_socket=sock_path,
                  proposal_read=res_r, proposal_write=req_w, host_fd=host_fd,
                  other_host_fds=[server.fileno(),ctl_w], artifacts=str(artifacts),
                  path_tricks={'symlink':str(scratch / 'symlink-to-authority'),
                               'dotdot':str(scratch / '..' / 'authoritative' / 'repo' / 'file.txt'),
                               'fd_path':'/dev/fd/' + str(host_fd)},
                  token=dict(work_id='c14-3b1-inert',execution_attempt_id='attempt-inert-A',
                             fencing_token=1,work_revision=0,event_sequence=0))
    (scratch / 'config.json').write_text(json.dumps(config))
    env = {'PATH':'/usr/bin:/bin','HOME':str(scratch / 'home'),'TMPDIR':str(scratch / 'tmp')}
    brokers = []
    def start_broker():
        p = subprocess.Popen([str(PYTHON), '-I', '-S', str(FIXTURES / 'c14_authority_broker.py'),
                              str(db),str(artifacts),str(req_r),str(res_w),str(ctl_r),str(ack_w)],
                             pass_fds=(req_r,res_w,ctl_r,ack_w), close_fds=True,env=env,
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        brokers.append(p)
        ready = receive(ack_r)
        assert ready['ready']
        return p, ready
    parent = None
    descendant_pid = None
    reports = {}
    def load(stage):
        path = scratch / (stage + '.json')
        wait_for(path.exists)
        report = json.loads(path.read_text())
        reports[stage] = report
        return report
    try:
        broker, first_ready = start_broker()
        # Launch evidence remains with this trusted custodian while controller restarts.
        (authority / 'launch-evidence.json').write_text(json.dumps(dict(
            policy_sha256=hashlib.sha256(profile.encode()).hexdigest(), backend_sha256=hashlib.sha256((scratch/'backend.py').read_bytes()).hexdigest(),
            descriptor_allowlist=[req_w,res_r], work_id='c14-3b1-inert',attempt='attempt-inert-A')))
        with (scratch / 'backend.stderr').open('wb') as stderr:
            parent = subprocess.Popen(['/usr/bin/arch','-arm64','/usr/bin/sandbox-exec','-f',str(profile_path),str(PYTHON),'-I','-S',
                                       str(scratch/'backend.py'),str(scratch),'parent'], cwd=scratch,env=env,
                                      pass_fds=(req_w,res_r), close_fds=True,start_new_session=True,
                                      stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=stderr)
        load('parent'); load('fork_group')
        escaped = load('escaped_exec')
        descendant_pid = escaped['pid']
        assert escaped['sid'] == escaped['pid'] == escaped['pgid']
        assert descendant_pid != parent.pid
        (scratch / 'parent-exit').touch()
        assert parent.wait(timeout=5) == 0
        wait_for(lambda: process_identity(descendant_pid).split()[1:2] == ['1'])
        (scratch / 'after-parent-exit').touch()
        reparented = load('reparented')
        assert reparented['ppid'] == 1
        assert reparented['publication']['result'] == 'ACCEPTED'
        send(ctl_w, {'action':'revoke'})
        revoked = receive(ack_r)
        assert revoked['state']['authority_state'] == 'REVOKED'
        (scratch/'revoked-token.json').write_text(json.dumps({key:revoked['state'][key] for key in config['token']}))
        (scratch / 'after-revoke').touch()
        load('revoked')
        alive_before_restart = process_identity(descendant_pid)
        assert alive_before_restart and not (scratch/'finished').exists()
        send(ctl_w, {'action':'shutdown'})
        assert receive(ack_r)['stopped']
        assert broker.wait(timeout=5) == 0
        broker, second_ready = start_broker()
        assert first_ready['pid'] != second_ready['pid']
        assert second_ready['state'] == revoked['state']
        assert profile_path.read_text() == profile
        (scratch / 'after-restart').touch()
        restarted = load('restarted')
        alive_after_restart = process_identity(descendant_pid)
        assert alive_after_restart and restarted['pid'] == descendant_pid and restarted['ppid'] == 1
        for stage, report in reports.items():
            for key, result in report.items():
                if isinstance(result,dict) and 'denied' in result:
                    assert result['denied'], (stage,key,result)
            assert report['host_descriptor']['closed'], (stage,'descriptor leak')
            assert all(report['other_host_descriptors_closed'].values()), (stage,'host endpoint leak')
            assert sorted(report['open_fds']) == sorted([req_w,res_r]), (stage,report['open_fds'])
            assert report['generic_rpc']['result'] == 'FORBIDDEN_OPERATION'
            expected = 'REVOKED' if stage in ('revoked','restarted') else 'STALE'
            assert all(r['result'] == expected for r in report['stale'].values())
            assert report['publication']['result'] == ('REVOKED' if stage in ('revoked','restarted') else 'ACCEPTED')
        for name, sha in before.items():
            assert hashlib.sha256(Path(sentinels[name]).read_bytes()).hexdigest() == sha
        conn = sqlite3.connect(db)
        events = conn.execute('SELECT * FROM events ORDER BY sequence').fetchall()
        proposals = conn.execute('SELECT * FROM proposals').fetchall()
        final_state = conn.execute('SELECT * FROM authority').fetchone()
        conn.close()
        assert events == [(1,'PROPOSAL'),(2,'PROPOSAL'),(3,'PROPOSAL'),(4,'PROPOSAL'),(5,'REVOKED')]
        assert len(proposals) == 4 and final_state[-1] == 'REVOKED'
        for sha, _ in proposals:
            path = artifacts / (sha+'.json')
            assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
            assert path.stat().st_mode & 0o222 == 0
        evidence = dict(result='PASS_DISPOSABLE_AUTHORITY_GATE', platform=sys.platform,
                        mechanism='whole-process sandbox-exec deny-default Seatbelt profile',
                        profile=profile, profile_sha256=hashlib.sha256(profile.encode()).hexdigest(),
                        sentinel_sha256_before=before, sentinel_hashes_unchanged=True,
                        phases=reports, alive_before_restart=alive_before_restart,alive_after_restart=alive_after_restart,
                        controller_pids=[first_ready['pid'],second_ready['pid']],
                        controller_restart='New broker process reopened durable REVOKED state; retained trusted launch custodian; live descendant attacks rechecked',
                        lifecycle='ALIVE',authority='REVOKED',verified_quiescence=False,
                        events=events,accepted_proposals=len(proposals),
                        descriptors_closed=['authoritative file','trusted writer socket','controller command pipe'],
                        current_tuple_rejected_after_revocation=True,
                        scope='Disposable native boundary feasibility, not production Route-B or live CLI acceptance')
        (root/'authority-report.json').write_text(json.dumps(evidence,indent=2)+'\n')
    finally:
        for name in ['parent-exit','after-parent-exit','after-revoke','after-restart','finish']:
            (scratch/name).touch()
        # Keep broker alive during orderly fixture cleanup so no child blocks on response.
        if parent is not None:
            try:
                parent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                parent.terminate(); parent.wait(timeout=5)
        if descendant_pid is not None:
            wait_for(lambda: (scratch/'finished').exists(), seconds=10)
            wait_for(lambda: not process_identity(descendant_pid), seconds=10)
        for p in brokers:
            if p.poll() is None:
                send(ctl_w, {'action':'shutdown'})
                receive(ack_r)
                p.wait(timeout=5)
        server.close()
        shutil.rmtree(_sock_tmp, ignore_errors=True)
        for fd in (req_r,req_w,res_r,res_w,ctl_r,ctl_w,ack_r,ack_w,host_fd):
            os.close(fd)
    evidence['cleanup'] = 'Parent reaped; escaped descendant finished and PID absent; both controller processes exited'
    (root/'authority-report.json').write_text(json.dumps(evidence,indent=2)+'\n')
