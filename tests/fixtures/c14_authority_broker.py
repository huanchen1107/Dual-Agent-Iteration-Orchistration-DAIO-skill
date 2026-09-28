"""Trusted fixture broker, never loaded from backend-controlled storage.

This is an inert admission experiment, NOT a production Route-B implementation.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import sqlite3
import sys

DB, ARTIFACTS = sys.argv[1:3]
REQUEST_R, RESPONSE_W, CONTROL_R, CONTROL_W = map(int, sys.argv[3:])
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row


def receive(fd):
    data = b''
    while not data.endswith(b'\n'):
        chunk = os.read(fd, 1)
        if not chunk:
            return None
        data += chunk
        if len(data) > 4096:
            raise RuntimeError('Fixture protocol limit')
    return json.loads(data)


def send(fd, value):
    os.write(fd, (json.dumps(value, sort_keys=True) + '\n').encode())


def state():
    return dict(conn.execute('SELECT * FROM authority').fetchone())


def token(row):
    return {key: row[key] for key in ['work_id', 'execution_attempt_id', 'fencing_token', 'work_revision', 'event_sequence']}


send(CONTROL_W, {'ready': True, 'pid': os.getpid(), 'state': state()})
while True:
    ready, _, _ = select.select([CONTROL_R, REQUEST_R], [], [], 10)
    # Revocation control takes precedence if both channels are ready.
    for fd in sorted(ready, key=lambda x: x != CONTROL_R):
        message = receive(fd)
        if message is None:
            sys.exit(0)
        if fd == CONTROL_R:
            if message['action'] == 'shutdown':
                send(CONTROL_W, {'stopped': True})
                sys.exit(0)
            if message['action'] == 'revoke':
                conn.execute('BEGIN IMMEDIATE')
                conn.execute("UPDATE authority SET authority_state='REVOKED',work_revision=work_revision+1,event_sequence=event_sequence+1")
                row = state()
                conn.execute('INSERT INTO events VALUES(?,?)', (row['event_sequence'], 'REVOKED'))
                conn.commit()
                send(CONTROL_W, {'revoked': True, 'state': row})
                continue
            raise RuntimeError('Unknown trusted fixture control')
        if message.get('action') != 'publish':
            send(RESPONSE_W, {'result': 'FORBIDDEN_OPERATION'})
            continue
        conn.execute('BEGIN IMMEDIATE')
        row = state()
        if row['authority_state'] != 'AUTHORIZED':
            conn.rollback()
            send(RESPONSE_W, {'result': 'REVOKED'})
            continue
        if message.get('token') != token(row):
            conn.rollback()
            send(RESPONSE_W, {'result': 'STALE'})
            continue
        # Copy bytes into host-owned storage; backend never gets a writable handle.
        artifact = json.dumps(message['artifact'], sort_keys=True, separators=(',', ':')).encode()
        sha = hashlib.sha256(artifact).hexdigest()
        path = Path(ARTIFACTS) / (sha + '.json')
        with path.open('xb') as stream:
            stream.write(artifact)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o400)
        conn.execute('INSERT INTO proposals VALUES(?,?)', (sha, row['execution_attempt_id']))
        conn.execute('UPDATE authority SET work_revision=work_revision+1,event_sequence=event_sequence+1')
        new = state()
        conn.execute('INSERT INTO events VALUES(?,?)', (new['event_sequence'], 'PROPOSAL'))
        conn.commit()
        send(RESPONSE_W, {'result': 'ACCEPTED', 'sha256': sha, 'token': token(new)})
