# C1.4 Phase 3B2 — trusted apply and baseline revalidation

Status: implemented/tested in generic source for disposable acceptance, pending
Lead Architect review. Parent: `f14dba604e3cc78a293db1c778d0369779e1d997`.
No production deployment, migration, live backend, C1.3 changes or full Route-B
integration is included. Contract: `daio-trusted-apply/v1`.

## Trusted writer and sealed input

`TrustedWriter` is an opt-in trusted-host API. A platform isolation provider must
exclude backend processes from both the authoritative repository and writer state.
The module neither launches a backend nor imports or invokes sandbox-exec. Its
current repository lock uses POSIX flock; Darwin and Linux implementations can
share these contracts, while other platforms need an equivalent lock provider.

Ingestion accepts bounded proposal bytes, not a backend path. It validates a strict
schema, canonicalizes the document, hashes the exact resulting bytes, and stores
that payload as a sealed SQLite BLOB. Update/delete triggers prevent modification
through the normal database API. The artifact binds the work ID and exact resulting
attempt/fence/revision/sequence token. Apply loads only that host-owned record and
verifies its digest and binding again immediately before mutation. Mutation of the
original backend file after ingestion cannot change the sealed artifact.

This is immutability against backends and accidental API mutation, not protection
against a malicious trusted database owner or host administrator. The threat model
retains the trusted OS, writer, controller and host-managed state.

## Declarative changes and scope

The version-1 payload contains only `version` and a bounded `changes` list. Each
entry contains `path`, `expected_sha256` and UTF-8 `content`:

```json
{
  "version": "daio-trusted-apply/v1",
  "changes": [
    {"path": "src/example.txt", "expected_sha256": "<baseline SHA-256>", "content": "replacement bytes\n"}
  ]
}
```

Only replacements of existing regular files are supported. Creation, deletion,
rename, binary payloads, submodules, linked worktrees and symlink entries are outside
this bounded implementation. Maximum proposal is 64 KiB and 16 replacements; each
file is at most 64 KiB. The baseline inventory is limited to 256 files and 3 MiB
of base64 content. These are explicit feasibility limits, not production sizing.

No backend shell/Git commands are accepted. No candidate tests, builds, hooks or
filters run under trusted-writer authority. Candidate validation that executes code
requires a separately isolated runner; it is not part of this writer.

## Authority, baseline and paths

Each apply validates work ID, execution attempt, fence, AUTHORIZED state, OPEN work
status, work revision, event sequence, artifact identity and artifact hash. Lifecycle
is independently recorded as UNKNOWN in these fixtures and is never converted to
TERMINATED by revocation. Explicit host approval IDs are unique. Older artifacts
cannot be retargeted to a new token or attempt, even when their hash is still valid.

A registered immutable baseline binds canonical repository path and repository/
.git device+inode identity, HEAD, Git index, file bytes/hashes/modes and trusted
allowlist/frozen policy. Admission requires a clean complete working tree and index;
untracked, missing, staged, mode or content changes block it. Read-only Git plumbing
(rev-parse, ls-tree, cat-file, ls-files) is invoked with fixed argument arrays and a
clean environment. It avoids status/diff/filter execution and ignores global/system
configuration. HEAD/index and applied bytes are checked again before COMMITTED.

Paths reject absolute names, traversal, ambiguous separators, protected control and
credential components, .git mutation, symlink directories/files and hardlinked files.
Directory traversal uses no-follow directory descriptors. Replacement writes and
fsyncs a fresh temporary file, then atomically renames relative to its opened parent
and fsyncs that directory. Allowed paths are explicit existing-file names; frozen
paths additionally block exact names/subtrees.

The only writer-owned .git operations are its fixed lock and control-binding marker.
Candidate proposals cannot target .git. The binding prevents a second control database
from independently administering the same repository. Git HEAD and index are not
changed by candidate apply: **COMMITTED means the durable apply journal committed,
not that a Git commit was created.** Applied changes intentionally remain in the
working tree for later trusted review/commit workflows.

## Serialization and journal

One repository-scoped nonblocking flock serializes apply, ingestion, registration,
revocation, replacement and completion through this module. Contenders get WriterBusy;
no authority-transition acknowledgement is issued while the lock is held. A pending
journal also blocks transitions after process death releases the OS lock.

The durable SQLite journal contains immutable artifact identity, publication token,
baseline and exact before/after images. Its states are:

`PREPARED → APPLYING → APPLIED → COMMITTED`

Ambiguity enters `RECONCILIATION_REQUIRED`. Journal state history is append-only;
COMMITTED cannot regress. SQLite uses synchronous FULL. File and directory fsyncs
precede the final controller commit. The final work event/revision increment and
COMMITTED state are one SQLite transaction. Internal journal transitions have their
own ordered history; work revision/sequence advances on accepted host publications.

Once preparation is durable, admission checks are repeated before filesystem writes.
Multiple file replacements are not globally atomic. A crash may leave a partial
working tree, which is why the pending journal blocks subsequent authoritative work.

## Restart and reconciliation

Tests terminate a separate apply process using os._exit at PREPARED, APPLYING,
after temporary-file staging, after each replacement, APPLIED and COMMITTED. The
restarted writer reconstructs entirely from host-owned journal/artifact state.

Reconciliation records NOT_APPLIED, PARTIALLY_APPLIED, FULLY_APPLIED, STAGING_REMAINS,
BASELINE_DRIFT, DIVERGENT_BYTES or UNKNOWN observations with a measured tree digest.
It never writes or replays candidate bytes. If the exact entire after
image, repository identity, HEAD/index, authority and sealed artifact still match,
it can finish COMMITTED without applying again. If bytes are untouched, partially
applied, externally changed, or an orphan staging file remains, it leaves
RECONCILIATION_REQUIRED and blocks further apply/revocation/replacement/completion.

An unchanged-before image does not silently authorize a retry. Version 1 deliberately
has no automatic rollback, rebase or human-resolution API. A separately authorized
resolution contract is needed to clear unresolved cases. Recognizing a completed
journal is idempotent; it does not reapply the artifact.

Revocation races have serialized outcomes: an admitted apply owns the lock, commits
(or leaves a blocking journal), and only then can a caller revalidate and revoke
using the fresh token. If revocation happens first, apply fails with no file writes.
An old revocation token cannot succeed after apply advanced the work revision.

## Validation and evidence

Final suite: **129 passed** — 49 new writer cases plus the accepted 80 Phase-1/2
safety/compatibility cases. The normal scenario reaches COMMITTED with exactly the
accepted bytes, unchanged unrelated/frozen files and unchanged Git HEAD. A script-like
candidate is written as data and its side effect never runs.

Required A–M cases are covered: wrong hash/storage corruption, backend-source TOCTOU,
wrong/stale attempt, revocation, stale fence/revision/sequence, HEAD drift, dirty/index
conflict, frozen path, traversal/symlink/hardlink escape, concurrent writer, real
process crash, unresolved restart and both revocation/apply orderings. Additional
cases cover protected paths, schema extras, duplicate edits, expected-file hash,
repository identity drift, binding to a second database and post-crash drift.

Reproduce using the environment's pytest-enabled Python:

```sh
/Users/huanchen/opt/anaconda3/bin/python3 -m pytest -q tests/test_c14_trusted_writer.py tests/test_c14_manual_handoff_integration.py tests/test_c14_handoff_safety.py tests/test_daio_closed_loop_store.py tests/test_daio_closed_loop_router.py tests/test_executor_with_agent.py tests/test_antigravity_cli_agent.py tests/test_baseline_aware_gate_and_atomic_human_gate.py
```

See [disposable evidence](C1_4_PHASE3B2_APPLY_EVIDENCE.json). Temporary run paths are
observations, not dependencies needed to reproduce the tests.

## Integration boundaries and next recommendation

This module has its own opt-in writer control tables. It is not wired into the old
executor, live router, supervisor or DurableHandoff authority path. The proven race
and uncertainty guards apply to transitions routed through TrustedWriter. A future
integration MUST make this the shared authoritative admission boundary; independently
calling the legacy controller must never be allowed to bypass a pending writer
journal. No such mixed production configuration is authorized by this phase.

The OS isolation provider is an external prerequisite, not implemented by this module.
Cooperating trusted writers must use the repository lock. A malicious host owner or
an unrelated tool modifying directories concurrently is outside the isolation proof;
ordinary drift observed at validation checkpoints fails closed. Git object/database
integrity and filesystem durability are trusted platform prerequisites.

Next: Lead Architect review, then a separately authorized integration/reconciliation
contract that connects authority handoff to this writer boundary and defines explicit
operator resolution for partial applies. No deployment, production migration or live
backend compatibility testing is started.
