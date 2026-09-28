"""C1.4 disposable trusted apply foundation; no backend launcher or sandbox dependency.

Trusted host API only. An isolation provider must deny backends repository/control
access. Version 1 replaces existing regular files only; it never executes proposals.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import subprocess
import uuid

from .handoff_contract import PublicationToken, SafetyError, StaleExecution, canonical, identifier

VERSION = 'daio-trusted-apply/v1'
PENDING = ('PREPARED', 'APPLYING', 'APPLIED', 'RECONCILIATION_REQUIRED')
MAX_BYTES = 65536
MAX_FILES = 16


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class WriterBusy(SafetyError):
    pass


class TrustedWriter:
    _authority_mode = "standalone"

    def __init__(self, repository, state_dir):
        self.repo = Path(repository).absolute()
        self.control = Path(state_dir).absolute()
        if self.repo.resolve() != self.repo or self.control.resolve() != self.control:
            raise SafetyError('Canonical, non-symlink repository/control paths required')
        self.git = self.repo / '.git'
        if not self.git.is_dir() or self.git.is_symlink():
            raise SafetyError('Standalone Git directory required; linked worktrees unsupported')
        if self.control == self.repo or self.repo in self.control.parents:
            raise SafetyError('Control state must be outside repository')
        self.control.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.control / 'writer.db'
        # Same inode lock even when callers supply different control directories.
        with self._lock():
            binding = self.git / 'daio-trusted-writer-binding.json'
            binding_identity = {'version': VERSION, 'control': str(self.control)}
            if self._authority_mode != 'standalone':
                binding_identity['authority_mode'] = self._authority_mode
            expected = canonical(binding_identity)
            if binding.exists() or binding.is_symlink():
                if binding.is_symlink() or binding.stat().st_nlink != 1 or binding.read_text() != expected:
                    raise SafetyError('Repository already bound to another controller')
            else:
                fd = os.open(binding, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(expected); stream.flush(); os.fsync(stream.fileno())
                fsync_dir(self.git)
            with self._db() as conn:
                self._initialize_authority_schema(conn)
                conn.executescript('''
                CREATE TABLE IF NOT EXISTS artifacts (
                  artifact_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, payload BLOB NOT NULL,
                  sha256 TEXT NOT NULL, token TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS applies (
                  apply_id TEXT PRIMARY KEY, artifact_id TEXT UNIQUE NOT NULL, work_id TEXT NOT NULL,
                  state TEXT NOT NULL, token TEXT NOT NULL, before_image TEXT NOT NULL,
                  after_image TEXT NOT NULL, baseline TEXT NOT NULL);

                CREATE TABLE IF NOT EXISTS journal_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, apply_id TEXT NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reconciliation_observations (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, apply_id TEXT NOT NULL,
                  classification TEXT NOT NULL, observed_sha256 TEXT);
                CREATE TABLE IF NOT EXISTS approvals (approval_id TEXT PRIMARY KEY);
                CREATE TRIGGER IF NOT EXISTS immutable_artifact_update BEFORE UPDATE ON artifacts
                  BEGIN SELECT RAISE(ABORT,'immutable artifact'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_artifact_delete BEFORE DELETE ON artifacts
                  BEGIN SELECT RAISE(ABORT,'immutable artifact'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_apply_identity BEFORE UPDATE OF
                  apply_id,artifact_id,work_id,token,before_image,after_image,baseline ON applies
                  BEGIN SELECT RAISE(ABORT,'immutable apply identity'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_apply_delete BEFORE DELETE ON applies
                  BEGIN SELECT RAISE(ABORT,'immutable apply identity'); END;
                CREATE TRIGGER IF NOT EXISTS terminal_apply BEFORE UPDATE OF state ON applies
                  WHEN OLD.state='COMMITTED' AND NEW.state!='COMMITTED'
                  BEGIN SELECT RAISE(ABORT,'committed journal cannot regress'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_journal_events_update BEFORE UPDATE ON journal_events
                  BEGIN SELECT RAISE(ABORT,'immutable journal event'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_journal_events_delete BEFORE DELETE ON journal_events
                  BEGIN SELECT RAISE(ABORT,'immutable journal event'); END;
                ''')

    def _initialize_authority_schema(self, conn):
        conn.executescript("""
                CREATE TABLE IF NOT EXISTS work (
                  work_id TEXT PRIMARY KEY, attempt TEXT NOT NULL, fence INTEGER NOT NULL,
                  revision INTEGER NOT NULL, sequence INTEGER NOT NULL,
                  authority TEXT NOT NULL, lifecycle TEXT NOT NULL, status TEXT NOT NULL,
                  baseline TEXT NOT NULL, policy TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  work_id TEXT NOT NULL, sequence INTEGER NOT NULL, revision INTEGER NOT NULL,
                  attempt TEXT NOT NULL, fence INTEGER NOT NULL, kind TEXT NOT NULL,
                  PRIMARY KEY(work_id,sequence));
                CREATE TRIGGER IF NOT EXISTS immutable_policy BEFORE UPDATE OF baseline,policy ON work
                  BEGIN SELECT RAISE(ABORT,'immutable baseline policy'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events
                  BEGIN SELECT RAISE(ABORT,'immutable event'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events
                  BEGIN SELECT RAISE(ABORT,'immutable event'); END;
        """)

    @contextmanager
    def _lock(self):
        path = self.git / 'daio-trusted-writer.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_nlink != 1:
                raise SafetyError('Unsafe writer lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WriterBusy('Another trusted writer/authority transition owns repository')
            yield
        finally:
            os.close(fd)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA synchronous=FULL')
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _git(self, *args):
        # Fixed read-only commands only. No shell, filters, hooks, tests or builds.
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.control), 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0',
               'GIT_NO_REPLACE_OBJECTS': '1'}
        return subprocess.check_output(['/usr/bin/git', '--no-optional-locks', '-C', str(self.repo),
                                        *args], env=env, stderr=subprocess.DEVNULL)

    def _identity(self):
        if self.repo.resolve() != self.repo or self.git.is_symlink():
            raise SafetyError('Repository identity changed')
        return {'path': str(self.repo), 'repo': [self.repo.stat().st_dev,self.repo.stat().st_ino],
                'git': [self.git.stat().st_dev,self.git.stat().st_ino]}

    @staticmethod
    def _path(path):
        if not isinstance(path,str) or not path or '\\' in path or '\x00' in path or len(path) > 512:
            raise SafetyError('Invalid path')
        p = PurePosixPath(path)
        if p.is_absolute() or any(x in ('', '.', '..') for x in path.split('/')):
            raise SafetyError('Unsafe path')
        blocked = {'.git', '_daio', '.daio', '.codex', '.gemini', '.ssh', 'secrets', 'credentials',
                   'sessions', 'cookies', 'keychains', 'control', 'auth.json'}
        if any(x.lower() in blocked or x.lower().startswith('.env') for x in p.parts):
            raise SafetyError('Protected control/credential path')
        return path

    @contextmanager
    def _parent(self, path):
        self._path(path)
        parts = path.split('/')
        fd = os.open(self.repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = new
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def _read(self,path):
        with self._parent(path) as (parent,name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd,'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                    raise SafetyError('Only bounded non-hardlinked regular files supported')
                data = stream.read(MAX_BYTES+1)
                if len(data) > MAX_BYTES:
                    raise SafetyError('File too large')
                return {'sha256':sha(data), 'mode':stat.S_IMODE(info.st_mode),
                        'bytes':base64.b64encode(data).decode()}

    def _tree(self):
        found = {}
        for directory, dirs, files in os.walk(self.repo, followlinks=False):
            if Path(directory) == self.repo:
                dirs[:] = [d for d in dirs if d != '.git']
            for d in dirs:
                if (Path(directory)/d).is_symlink():
                    raise SafetyError('Symlink directory in repository')
            for name in files:
                path = (Path(directory)/name).relative_to(self.repo).as_posix()
                found[path] = self._read(path)
                if len(found)>256 or sum(len(x['bytes']) for x in found.values())>3*1024*1024:
                    raise SafetyError('Repository exceeds v1 bounded snapshot size')
        return found

    def _index(self):
        result = {}
        for record in self._git('ls-files','--stage','-z').split(b'\0'):
            if record:
                meta,name = record.split(b'\t',1)
                mode,oid,stage = meta.decode().split()
                if stage != '0':
                    raise SafetyError('Unmerged index')
                result[name.decode()] = [mode,oid]
        return result

    def _baseline(self):
        head = self._git('rev-parse','--verify','HEAD').decode().strip()
        tree = self._tree()
        tracked = {}
        for record in self._git('ls-tree','-rz','--full-tree',head).split(b'\0'):
            if not record:
                continue
            meta, name = record.split(b'\t',1)
            mode, kind, oid = meta.decode().split()
            path = self._path(name.decode('utf-8'))
            if kind != 'blob' or mode not in ('100644','100755'):
                raise SafetyError('Unsupported Git entry')
            contents = self._git('cat-file','blob',oid)
            tracked[path] = sha(contents)
            if path not in tree or tree[path]['sha256'] != tracked[path] or bool(tree[path]['mode'] & 0o111) != (mode=='100755'):
                raise SafetyError('Dirty baseline')
        if set(tree) != set(tracked):
            raise SafetyError('Untracked/missing files block baseline')
        # Compare staged tree without invoking status/diff filters or project hooks.
        index = self._index()
        expected_index = {}
        for record in self._git('ls-tree','-rz',head).split(b'\0'):
            if record:
                meta,name = record.split(b'\t',1)
                mode,_,oid = meta.decode().split(); expected_index[name.decode()] = [mode,oid]
        if index != expected_index:
            raise SafetyError('Staged baseline drift')
        return {'identity':self._identity(),'head':head,'tree':tree,'index':index}

    def _observed_baseline(self):
        return {"identity": self._identity(), "head": self._git("rev-parse", "--verify", "HEAD").decode().strip(),
                "tree": self._tree(), "index": self._index()}

    def _admit(self, conn, token):
        return self._current(conn, token)

    @staticmethod
    def _token(row):
        return PublicationToken(row['work_id'],row['revision'],row['sequence'],row['attempt'],row['fence'])

    def _current(self,conn,token):
        row = conn.execute('SELECT * FROM work WHERE work_id=?',(token.work_id,)).fetchone()
        if not row or self._token(row) != token or row['authority'] != 'AUTHORIZED' or row['status'] != 'OPEN':
            raise StaleExecution('Stale/revoked/terminal writer authority')
        return row

    def _no_pending(self,conn):
        if conn.execute("SELECT 1 FROM applies WHERE state!='COMMITTED'").fetchone():
            raise SafetyError('RECONCILIATION_REQUIRED: authoritative apply outcome unresolved')

    def _event(self,conn,work_id,kind):
        conn.execute('UPDATE work SET revision=revision+1,sequence=sequence+1 WHERE work_id=?',(work_id,))
        row = conn.execute('SELECT * FROM work WHERE work_id=?',(work_id,)).fetchone()
        conn.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(work_id,row['sequence'],row['revision'],row['attempt'],row['fence'],kind))
        return self._token(row)

    def register(self,work_id,attempt,approval_id,allowed,frozen=()):
        for value in (work_id,attempt,approval_id): identifier(value)
        for value in (*allowed,*frozen): self._path(value)
        if not allowed: raise SafetyError('Explicit file allowlist required')
        with self._lock(),self._db() as conn:
            self._no_pending(conn)
            baseline = self._baseline()
            if not set(allowed) <= set(baseline['tree']): raise SafetyError('Existing files only')
            conn.execute('INSERT INTO approvals VALUES(?)',(approval_id,))
            conn.execute('INSERT INTO work VALUES(?,?,1,0,0,?,?,?, ?,?)',
                         (work_id,attempt,'AUTHORIZED','UNKNOWN','OPEN',canonical(baseline),canonical({'allowed':list(allowed),'frozen':list(frozen)})))
            return self._event(conn,work_id,'AUTHORIZED')

    def token(self,work_id):
        with self._db() as conn:
            row=conn.execute('SELECT * FROM work WHERE work_id=?',(work_id,)).fetchone()
            if not row: raise SafetyError('Unknown work')
            return self._token(row)

    def ingest(self,token,proposal_bytes):
        if not isinstance(proposal_bytes,bytes) or len(proposal_bytes)>MAX_BYTES:
            raise SafetyError('Bounded bytes required; backend paths are not accepted')
        payload=json.loads(proposal_bytes)
        if not isinstance(payload,dict) or set(payload)!={'version','changes'} or payload['version']!=VERSION:
            raise SafetyError('Declarative schema mismatch')
        if not isinstance(payload['changes'],list) or not 1<=len(payload['changes'])<=MAX_FILES:
            raise SafetyError('Invalid change count')
        paths=[]
        for edit in payload['changes']:
            if not isinstance(edit,dict) or set(edit)!={'path','expected_sha256','content'} or not isinstance(edit['content'],str):
                raise SafetyError('Only declarative text replacement supported')
            self._path(edit['path']); paths.append(edit['path'])
        if len(paths)!=len(set(paths)): raise SafetyError('Duplicate path')
        sealed=canonical(payload).encode(); digest=sha(sealed)
        with self._lock(),self._db() as conn:
            self._no_pending(conn); self._admit(conn,token)
            next_token=self._event(conn,token.work_id,'ARTIFACT_SEALED')
            artifact_id='artifact-'+uuid.uuid4().hex
            conn.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',(artifact_id,token.work_id,sealed,digest,canonical(asdict(next_token))))
            return next_token,artifact_id,digest

    @staticmethod
    def _sealed(conn,artifact_id,expected_hash,token):
        artifact=conn.execute('SELECT * FROM artifacts WHERE artifact_id=?',(artifact_id,)).fetchone()
        if (not artifact or artifact['work_id']!=token.work_id or artifact['token']!=canonical(asdict(token))
                or artifact['sha256']!=expected_hash or sha(artifact['payload'])!=expected_hash):
            raise SafetyError('Artifact identity/hash/authority mismatch')
        return json.loads(artifact['payload'])

    def _transition(self,apply_id,state):
        with self._db() as conn:
            conn.execute('UPDATE applies SET state=? WHERE apply_id=?',(state,apply_id))
            conn.execute('INSERT INTO journal_events(apply_id,state) VALUES(?,?)',(apply_id,state))

    def _replace(self,path,new,old,apply_id,staged_hook):
        if self._read(path)!=old: raise SafetyError('File changed immediately before replacement')
        with self._parent(path) as (parent,name):
            temporary='.daio-apply-'+apply_id+'-'+uuid.uuid4().hex
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(base64.b64decode(new['bytes'])); os.fchmod(stream.fileno(),new['mode'])
                    stream.flush(); os.fsync(stream.fileno())
                staged_hook()
                os.replace(temporary,name,src_dir_fd=parent,dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try: os.unlink(temporary,dir_fd=parent)
                except FileNotFoundError: pass

    def apply(self,token,artifact_id,expected_hash,crash_hook=lambda stage:None):
        with self._lock():
            with self._db() as conn:
                self._no_pending(conn); row=self._admit(conn,token)
                payload=self._sealed(conn,artifact_id,expected_hash,token)
                baseline=json.loads(row['baseline']); policy=json.loads(row['policy'])
                if self._observed_baseline()!=baseline: raise SafetyError('Repository baseline drift')
                before=baseline['tree']; after=dict(before)
                for edit in payload['changes']:
                    path=self._path(edit['path'])
                    if path not in policy['allowed'] or any(path==f or path.startswith(f+'/') for f in policy['frozen']):
                        raise SafetyError('Outside scope or frozen path')
                    if edit['expected_sha256']!=before[path]['sha256']: raise SafetyError('Expected file baseline mismatch')
                    data=edit['content'].encode()
                    if len(data)>MAX_BYTES: raise SafetyError('Replacement too large')
                    after[path]={'sha256':sha(data),'mode':before[path]['mode'],'bytes':base64.b64encode(data).decode()}
                apply_id='apply-'+uuid.uuid4().hex
                conn.execute('INSERT INTO applies VALUES(?,?,?,?,?,?,?,?)',
                             (apply_id,artifact_id,token.work_id,'PREPARED',canonical(asdict(token)),canonical(before),canonical(after),canonical(baseline)))
                conn.execute('INSERT INTO journal_events(apply_id,state) VALUES(?,?)',(apply_id,'PREPARED'))
            crash_hook('PREPARED')
            self._transition(apply_id,'APPLYING'); crash_hook('APPLYING')
            try:
                # Repeat all admission checks after durable preparation, before any mutation.
                with self._db() as conn:
                    self._current(conn,token); self._sealed(conn,artifact_id,expected_hash,token)
                    if self._observed_baseline()!=baseline: raise SafetyError('Baseline drift before mutation')
                for index,edit in enumerate(payload['changes']):
                    self._replace(edit['path'],after[edit['path']],before[edit['path']],apply_id,
                                  lambda: crash_hook('STAGED_'+str(index)))
                    crash_hook('FILE_'+str(index))
                if self._tree()!=after: raise SafetyError('Post-apply bytes mismatch')
                self._transition(apply_id,'APPLIED'); crash_hook('APPLIED')
                result=self._commit(apply_id)
            except Exception:
                self._transition(apply_id,'RECONCILIATION_REQUIRED')
                raise
            crash_hook('COMMITTED')
            return result

    def _commit(self,apply_id):
        with self._db() as conn:
            journal=conn.execute('SELECT * FROM applies WHERE apply_id=?',(apply_id,)).fetchone()
            token=PublicationToken(**json.loads(journal['token']))
            self._current(conn,token)
            baseline=json.loads(journal['baseline'])
            artifact=conn.execute('SELECT * FROM artifacts WHERE artifact_id=?',(journal['artifact_id'],)).fetchone()
            self._sealed(conn,journal['artifact_id'],artifact['sha256'],token)
            if (self._identity()!=baseline['identity'] or self._index()!=baseline['index']
                    or self._git('rev-parse','--verify','HEAD').decode().strip()!=baseline['head']
                    or self._tree()!=json.loads(journal['after_image'])):
                raise SafetyError('Commit evidence changed; reconciliation required')
            conn.execute("UPDATE applies SET state='COMMITTED' WHERE apply_id=?",(apply_id,))
            conn.execute('INSERT INTO journal_events(apply_id,state) VALUES(?,?)',(apply_id,'COMMITTED'))
            return self._event(conn,token.work_id,'APPLY_COMMITTED')

    def reconcile(self,apply_id):
        """Read/verify only: never silently writes/reapplies uncertain candidate bytes."""
        with self._lock():
            with self._db() as conn:
                journal=conn.execute('SELECT * FROM applies WHERE apply_id=?',(apply_id,)).fetchone()
                if not journal: raise SafetyError('Unknown apply')
                if journal['state']=='COMMITTED': return 'COMMITTED'
                artifact=conn.execute('SELECT * FROM artifacts WHERE artifact_id=?',(journal['artifact_id'],)).fetchone()
                token=PublicationToken(**json.loads(journal['token']))
                self._current(conn,token)
                self._sealed(conn,journal['artifact_id'],artifact['sha256'],token)
            baseline=json.loads(journal['baseline'])
            classification='UNKNOWN'; observed_hash=None
            try:
                stable=(self._identity()==baseline['identity'] and self._index()==baseline['index']
                        and self._git('rev-parse','--verify','HEAD').decode().strip()==baseline['head'])
                current=self._tree()
                observed_hash=sha(canonical(current).encode())
                before=json.loads(journal['before_image']); after=json.loads(journal['after_image'])
                if not stable: classification='BASELINE_DRIFT'
                elif current==after: classification='FULLY_APPLIED'
                elif current==before: classification='NOT_APPLIED'
                elif set(current)==set(before) and all(current[p] in (before[p],after[p]) for p in before):
                    classification='PARTIALLY_APPLIED'
                elif set(current)>set(before) and all(Path(p).name.startswith('.daio-apply-') for p in set(current)-set(before)):
                    classification='STAGING_REMAINS'
                else: classification='DIVERGENT_BYTES'
            except (OSError,SafetyError):
                pass
            with self._db() as conn:
                conn.execute('INSERT INTO reconciliation_observations(apply_id,classification,observed_sha256) VALUES(?,?,?)',
                             (apply_id,classification,observed_hash))
            if classification=='FULLY_APPLIED':
                self._transition(apply_id,'APPLIED'); self._commit(apply_id)
                return 'COMMITTED'
            self._transition(apply_id,'RECONCILIATION_REQUIRED')
            return 'RECONCILIATION_REQUIRED'

    def authority_transition(self,token,action,approval_id,new_attempt=None):
        if action not in ('REVOKE','REPLACE','COMPLETE'): raise SafetyError('Unknown transition')
        identifier(approval_id)
        if action=='REPLACE': identifier(new_attempt)
        with self._lock(),self._db() as conn:
            self._no_pending(conn); row=self._admit(conn,token)
            conn.execute('INSERT INTO approvals VALUES(?)',(approval_id,))
            if action=='REPLACE':
                if new_attempt==row['attempt']: raise SafetyError('New attempt required')
                conn.execute('UPDATE work SET attempt=?,fence=fence+1 WHERE work_id=?',(new_attempt,token.work_id))
            else:
                conn.execute("UPDATE work SET authority='REVOKED',fence=fence+1,status=? WHERE work_id=?",
                             ('COMPLETED' if action=='COMPLETE' else 'OPEN',token.work_id))
            return self._event(conn,token.work_id,action)

    def journals(self):
        with self._db() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM applies ORDER BY rowid')]
