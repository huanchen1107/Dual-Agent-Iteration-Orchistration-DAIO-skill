# C1.4 Phase 3B3 — unified handoff and trusted-writer admission

Status: implemented and tested in generic source; pending Lead Architect review.
Accepted parent: `9aaba9b2ae5d02afa3e53d9593d20c858ed92c3a`.
Scope: disposable repositories, disposable SQLite, inert proposals, manual approval.
C1.3 remains COMPLETE / APPROVED / FROZEN. No deployment or production migration.

## One authority source

`UnifiedHandoff` extends `DurableHandoff`. Its `ControllerWriter` asks that controller
for the exact current work ID, execution attempt, fencing token, work revision and
event sequence in the same SQLite transaction used for apply admission. Mutation
requires nonterminal work, control state EXECUTING and authority AUTHORIZED. New
proposal/apply admission also requires an unexpired execution lease.

The integrated database uses the existing `daio_work_items`, backend control,
attempts, authorizations, checkpoints and `daio_work_events`. It reuses the sealed
artifact, repository binding, apply journal and journal history. It does **not**
create the standalone writer's `work` or `events` tables. Repository scope/baseline
records contain no separate authority, attempt or fencing truth.

The opt-in enrollment discriminator is `daio-handoff-writer/v1`; proposal payloads
remain `daio-trusted-apply/v1` and checkpoints remain `daio-checkpoint/v1`. This
explicit discriminator makes the older controller reject integrated work instead
of bypassing the writer boundary. The repository binding also records the unified
mode; reopening it with a standalone writer fails. Standalone registration and
standalone writer authority-transition APIs are disabled on ControllerWriter.
Legacy queue/lease admission continues to reject enrolled work.

No existing production schema is migrated. Fresh disposable integrated state adds
`authority` to backend control, `daio_writer_scope` for measured baseline and immutable
file policy, and immutable `resolutions` approval records. The original v1 path and
standalone writer remain available for their accepted compatibility tests.

## Serialization and admission

One repository-scoped nonblocking POSIX flock spans ingestion, controller
transitions, apply, reconciliation and explicit resolution. SQLite transactions use
BEGIN IMMEDIATE and synchronous FULL. Every public controller transaction checks
for unresolved applies across the bound repository. Another work cannot select a
backend while a work has an authorized/reconstructing/executing owner.

If apply wins, its PREPARED admission is durable before any repository mutation.
Revocation/replacement/completion contenders receive WriterBusy, not successful
acknowledgement. After process death releases the lock, the unresolved journal
continues blocking these operations. If apply commits, the caller must acquire the
new controller token before revoking. If revocation wins, its authority change,
fence advance and work event commit atomically; the old artifact cannot enter apply.

The final COMMITTED journal state, controller event/revision/sequence increment,
attempt result digest and measured baseline advancement share one SQLite transaction.
Internal journal phases retain their ordered append-only journal history and the
admission token. They do not independently create execution authority.

**COMMITTED is journal finalization, not a Git commit.** The initial baseline must
be clean. Later baselines may contain exactly the working-tree edits proven by the
previous COMMITTED journal. HEAD and index remain unchanged. No arbitrary dirty
baseline, automatic rebase, candidate Git command, Git commit or push is accepted.

## Handoff, reconstruction and completion

A completes its trusted apply, then the trusted host explicitly revokes A. Revocation
advances the fence and clears its lease without asserting termination. A checkpoint
binds the current measured repository, unchanged repository/policy identity, and
monotonic completed-step list. Advancing a step requires the current attempt's latest
accepted artifact to have a COMMITTED journal and matching authoritative bytes.

The host explicitly selects B; the inherited controller creates a different attempt
with an advanced fence and A-to-B lineage. B has NEVER_GRANTED mutation authority
until checkpoint/hash/manifest acknowledgement and independent repository measurement
succeed, followed by explicit start_execution. Scope/baseline drift blocks authority.

The disposable acceptance resumes step-B after step-A, applies B's artifact and
completes W. Completion requires the current reconstructed owner and the latest
accepted artifact's known COMMITTED effect, rechecked against actual repository
identity, HEAD, index and bytes. A newer sealed-but-unapplied artifact blocks completion.
Unresolved journals block completion and terminal policy transitions as well.

Lifecycle remains UNKNOWN throughout this Route-B scenario, including after work
completion. AUTHORITY_REVOKED never becomes VERIFIED_QUIESCENCE. Authority and state
transitions are captured in the existing monotonic work event stream. No backend
lifecycle, provider or candidate code is executed.

## Restart and bounded resolution

Restart loads the same controller, sealed artifact and journal state; no in-memory
claim is authoritative. Actual child processes are terminated with os._exit during
proposal ingestion, revocation, replacement selection, new-attempt creation and
apply phases. A SQLite transaction is either committed or absent after restart.
An unresolved apply blocks new transitions regardless of released OS locks.

Read-only reconciliation can finalize an exact fully applied after-image without
rewriting it. Other uncertain states remain RECONCILIATION_REQUIRED.

The new `resolve_forward(apply_id, approval_id)` is an explicit trusted-host operation:

1. Require exactly one unresolved journal, its current controller token/authority,
   immutable sealed artifact and a fresh approval ID.
2. Require unchanged repository identity, HEAD and index, the exact same path set,
   and each observed file to match either its complete before-image or after-image
   (including bytes and mode).
3. Persist approval, apply identity and observed measurement before mutation.
4. Write only files still at their before-image, using the existing bounded fsync /
   atomic-replace writer. Leave already applied files untouched.
5. Recheck the entire after-image and finalize through the same atomic controller
   and journal commit.

Unexplained bytes, modes, extra files, index/HEAD drift and orphan staging files
remain blocked. There is no rollback, cleanup heuristic or speculative rebase.
A crash during resolution requires a fresh explicit approval/measurement; the test
verifies an already applied file's inode does not change on the second resolution.

An expired lease blocks **new** ingestion/apply admission. It does not prevent a
trusted host from resolving the exact apply already durably admitted under that
lease. All authority transitions remain blocked until its effect is known.

## Acceptance and evidence

Final suite: **172 passed**: 43 unified integration cases and the accepted 129-case
baseline. See [recorded evidence](C1_4_PHASE3B3_UNIFIED_EVIDENCE.json), including the
actual disposable lineage, journal records, test names/results and source hashes.
Temporary paths in observations identify disposable fixtures, not required persistent
handoff resources. The evidence JSON and source tests are the durable artifacts.

| Required case | Test / result |
| --- | --- |
| A — revoke before admission | Sealed artifact rejected, no writes/journal |
| B — revoke after admission | OS lock denies acknowledgement; fresh token required afterward |
| C — crash during apply | PREPARED, APPLYING, FILE_0, FILE_1, APPLIED, COMMITTED tested |
| D — restart unresolved | Journal blocks all controller transitions and new proposals |
| E — B while A unresolved | Backend selection and attempt creation rejected |
| F — stale A after B | Original token and attempted rebinding to B both rejected |
| G — concurrent A/B apply | Current B owns lock; stale A denied during and after B apply |
| H — premature completion | Unresolved, unapplied and drifted effects rejected |
| I — transition restart | Before/after commit crashes in revoke, replacement authorization, attempt creation, ingestion |
| J — changed baseline | Valid artifact denied for HEAD/index/byte drift |
| K — deterministic partial resolution | Approved roll-forward, including a second crash/restart, succeeds |
| L — unresolvable partial apply | Unknown bytes/mode/files/index/HEAD/staging remain blocked |

Additional cases cover exact five-field controller token matching, work/repository
binding, reconstruction-before-authority, terminal states, legacy bypass rejection,
one repository owner, lease expiry, unchanged Git HEAD, NOT_RUN tests, attempt lineage
and monotonic event ordering.

Reproduce from generic source with a pytest-enabled Python:

```sh
python -m pytest -q tests/test_c14_unified_handoff.py tests/test_c14_trusted_writer.py tests/test_c14_manual_handoff_integration.py tests/test_c14_handoff_safety.py tests/test_daio_closed_loop_store.py tests/test_daio_closed_loop_router.py tests/test_executor_with_agent.py tests/test_antigravity_cli_agent.py tests/test_baseline_aware_gate_and_atomic_human_gate.py
```

## Limits and review boundary

These are trusted-host control APIs, not backend-accessible RPC. Phase-3B1 isolation
must independently deny backend access to the repository, controller state, tokens,
credentials, browser sessions and host mutation operations. This module does not
launch or sandbox providers, expose sockets or weaken those isolation assumptions.
A malicious trusted host/administrator and unrelated host tools bypassing the lock
remain outside the proof. This acceptance tests process crashes, not OS power-loss
or filesystem corruption; POSIX locking and filesystem/SQLite durability are assumed.

The accepted writer's bounded existing-text-file constraints remain. Candidate
builds/tests never run here. Attempt test status is NOT_RUN. The unified path derives
successful artifact provenance from journal commit; its generic publish_outcome and
termination-receipt APIs deliberately reject calls in this scoped integration.
The older typed capacity outcome implementation remains unchanged and tested; live
adapter/outcome plumbing is not authorized or claimed complete by this phase.

The supervisor, executor, production database, deployed runtime, C1.3 artifacts and
live backend adapters are untouched. No automatic failover exists. The development
commit records source/tests/docs only; it does not implement runtime Git commits.

Next: Lead Architect review of this disposable integration. Any provider isolation,
real adapter/outcome wiring, production sizing/migration or deployment requires a
separate authorization. No next phase or live compatibility testing begins here.
