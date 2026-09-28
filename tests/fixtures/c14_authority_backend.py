"""Inert adversarial fixture. Execute ONLY inside the disposable Darwin boundary."""
import errno
import json
import os
from pathlib import Path
import select
import socket
import sys
import time

ROOT = Path(sys.argv[1])
CONFIG = json.loads((ROOT / 'config.json').read_text())
READ = int(CONFIG['proposal_read'])
WRITE = int(CONFIG['proposal_write'])


def receive(fd):
    data = b''
    while not data.endswith(b'\n'):
        if not select.select([fd], [], [], 10)[0]:
            raise RuntimeError('Fixture response deadline')
        chunk = os.read(fd, 1)
        if not chunk:
            raise RuntimeError('Fixture channel closed')
        data += chunk
    return json.loads(data)


def request(data):
    os.write(WRITE, (json.dumps(data) + '\n').encode())
    return receive(READ)


def attempt(action):
    try:
        action()
        return {'denied': False}
    except OSError as error:
        return {'denied': error.errno in (errno.EPERM, errno.EACCES), 'errno': error.errno}


def read(path):
    with open(path, 'rb') as stream:
        stream.read(1)


def write(path):
    with open(path, 'ab') as stream:
        stream.write(b'UNAUTHORIZED')


def attacks(stage, token, publish=True):
    results = {}
    for name, path in CONFIG['sentinels'].items():
        results[name + '_read'] = attempt(lambda path=path: read(path))
        results[name + '_write'] = attempt(lambda path=path: write(path))
    # Path names are known synthetic paths; no discovery of real user data.
    for name, path in CONFIG['path_tricks'].items():
        results[name + '_read'] = attempt(lambda path=path: read(path))
        results[name + '_write'] = attempt(lambda path=path: write(path))
        if name == 'fd_path':
            for operation in ('read', 'write'):
                result = results[name + '_' + operation]
                # /dev/fd cannot confer authority when the underlying FD is closed.
                if result.get('errno') == errno.EBADF:
                    result['denied'] = True
    results['hardlink_escape'] = attempt(lambda: os.link(CONFIG['sentinels']['repository'], ROOT / ('hardlink-' + stage)))
    def connect_writer():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            client.connect(CONFIG['writer_socket'])
            client.sendall(b'mutate')
    results['writer_endpoint'] = attempt(connect_writer)
    # A deliberately inheritable host descriptor must have been closed at launch.
    def leaked_descriptor():
        os.pread(CONFIG['host_fd'], 1, 0)
    try:
        leaked_descriptor()
        results['host_descriptor'] = {'closed': False}
    except OSError as error:
        results['host_descriptor'] = {'closed': error.errno == errno.EBADF, 'errno': error.errno}
    results['other_host_descriptors_closed'] = {}
    for fd in CONFIG['other_host_fds']:
        try:
            os.fstat(fd)
            results['other_host_descriptors_closed'][str(fd)] = False
        except OSError as error:
            results['other_host_descriptors_closed'][str(fd)] = error.errno == errno.EBADF
    open_fds = []
    for fd in range(3, 256):
        try:
            os.fstat(fd)
            open_fds.append(fd)
        except OSError:
            pass
    results['open_fds'] = open_fds
    results['generic_rpc'] = request({'action': 'host_write', 'token': token, 'path': CONFIG['sentinels']['repository']})
    stale = {}
    for field, wrong in [('work_id', 'wrong-work'), ('execution_attempt_id', 'wrong-attempt'),
                         ('fencing_token', 999), ('work_revision', 999), ('event_sequence', 999)]:
        bad = dict(token)
        bad[field] = wrong
        stale[field] = request({'action': 'publish', 'token': bad, 'artifact': {'stage': stage}})
    results['stale'] = stale
    if publish:
        accepted = request({'action': 'publish', 'token': token, 'artifact': {'stage': stage, 'proposal': 'synthetic-only'}})
        results['publication'] = accepted
        token = accepted.get('token', token)
        if accepted['result'] == 'ACCEPTED':
            path = Path(CONFIG['artifacts']) / (accepted['sha256'] + '.json')
            results['accepted_artifact_read'] = attempt(lambda: read(path))
            results['accepted_artifact_write'] = attempt(lambda: write(path))
    results.update(pid=os.getpid(), ppid=os.getppid(), pgid=os.getpgrp(), sid=os.getsid(0))
    temporary = ROOT / (stage + '.tmp')
    temporary.write_text(json.dumps(results, indent=2))
    temporary.replace(ROOT / (stage + '.json'))
    return token


def wait_file(name, deadline):
    while time.monotonic() < deadline:
        if (ROOT / name).exists():
            return
        time.sleep(0.02)
    raise RuntimeError('Fixture handshake deadline')


if sys.argv[2] == 'parent':
    deadline = time.monotonic() + 45
    token = attacks('parent', CONFIG['token'])
    child = os.fork()
    if child == 0:
        os.setpgid(0, 0)
        token = attacks('fork_group', token)
        grandchild = os.fork()
        if grandchild == 0:
            os.setsid()
            (ROOT / 'escape-token.json').write_text(json.dumps(token))
            # Explicit exec after fork+setsid; proposal pipes intentionally survive.
            os.execve(sys.executable, [sys.executable, '-I', '-S', str(ROOT / 'backend.py'), str(ROOT), 'escaped'], dict(os.environ))
        os._exit(0)
    os.waitpid(child, 0)
    wait_file('parent-exit', deadline)
else:
    deadline = time.monotonic() + 45
    token = json.loads((ROOT / 'escape-token.json').read_text())
    token = attacks('escaped_exec', token)
    wait_file('after-parent-exit', deadline)
    token = attacks('reparented', token)
    wait_file('after-revoke', deadline)
    # Knowing the current tuple does not restore revoked authority.
    token = json.loads((ROOT / 'revoked-token.json').read_text())
    token = attacks('revoked', token)
    wait_file('after-restart', deadline)
    token = attacks('restarted', token)
    wait_file('finish', deadline)
    (ROOT / 'finished').write_text('done')
