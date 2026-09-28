# C1.4 Phase 1: contract and safety foundation

Status: implemented in generic source; pending Lead Architect review. This is
not deployment approval or authorization for Phase 2. C1.3 remains COMPLETE /
APPROVED / FROZEN. No C1.3 artifacts or deployed runtime are migrated by this work.

## Ownership and scope

This repository is the implementation source of truth. The project deployment
owns backend authorization, domain scope, frozen-state declarations and acceptance.
The foundation is opt-in through `DurableHandoff`; enrolled work cannot enter the
legacy queue, executor, orchestrator, lease or unfenced publication paths.
Unenrolled work retains the legacy execution path with additional terminal guards.

The contract is `daio-handoff/v1`; immutable checkpoints use `daio-checkpoint/v1`.
Only manual or explicit policy-authorized selection is supported. There is no
automatic fallback, backend launcher, live failover, or IDE automation here.
Backends produce proposals; DAIO remains the only trusted workspace writer.
The new controller records proposal outcomes/digests but does not apply proposals.

## Admission, ordering and fencing

Execution admission rejects COMPLETED, FROZEN, SUPERSEDED, STOP and
HUMAN_GATE_REQUIRED, including explicit frozen/superseded metadata and human gates.
Reopening protected work through the legacy save path is rejected. Enrolled work
must use the controller instead of legacy saves, audit writes or architect decisions.

Each publication consumes the exact current `(work_id, work_revision,
event_sequence, execution_attempt_id, fencing_token)` token under `BEGIN IMMEDIATE`.
Each successful mutation increments revision and event sequence and appends an
immutable event in the same transaction. New attempts and policy revocation
advance the fence. Execution publications additionally require an unexpired lease.
Renewal returns a new token; callers must serialize renewal and publication.
Stale tokens fail without publication. Ordering uses work/attempt/sequence plus
timestamps and work `updated_at`, not browser visibility or wall time alone.

## Handoff protocol

1. Enroll approved, queued engineering work that has never been claimed, with an
   explicit backend allowlist and a trusted baseline manifest.
2. Authorize one backend using a unique authorization ID tied to the checkpoint.
3. Create an attempt and lease. The work ID is preserved; the attempt ID is new.
4. Deliver the bounded handoff containing checkpoint identity, hashes, manifest,
   backend identity and current publication token.
5. Require an acknowledgement binding that attempt/token to the checkpoint and
   manifest hashes. Independently measure the manifest through the trusted host.
6. Recheck the measured manifest before granting proposal execution authority.
7. Record a typed capacity interruption. Independently verify termination of the
   prior execution; UNKNOWN termination blocks replacement.
8. Re-measure the unchanged proposal-only workspace, then publish the immutable
   checkpoint, pointer and event atomically. Explicitly authorize the next backend.

States are READY → AUTHORIZED → RECONSTRUCTION_REQUIRED → PREPARED → EXECUTING.
Capacity interruption follows INTERRUPTED → QUIESCENT → CHECKPOINTED → AUTHORIZED.
Other outcomes enter RESULT_RECORDED for review, with human-gate/superseded work
protected from further execution. Policy stop revokes authority without claiming
that the process has terminated. No automatic human-gate resume is provided.

The manifest binds repository identity, Git HEAD, workspace digest, policy, scope,
frozen declarations and evidence digests, completed step IDs and the next incomplete
step. A completed step cannot be the next step. Checkpoints are canonical JSON with
SHA-256 content identity; SQLite triggers prohibit updating/deleting checkpoints
and events. A failed publication rolls back the checkpoint, pointer and event.

`observe` and `verify_termination` are trusted host callbacks, not assertions from
a model. Production measurement/writer integration is intentionally not installed.
The supplied POSIX verifier checks an already-reaped, owned process group; a live
descendant or inability to establish exit yields UNKNOWN. Future launch integration
must create a dedicated session/process group and retain the actual process handle.
Other receipt methods require separately implemented trusted lifecycle verification.

## Outcomes and provenance

Outcomes distinguish ENGINEERING_FAILURE, TEST_FAILURE, BACKEND_UNAVAILABLE,
QUOTA_EXHAUSTED, AUTHENTICATION_REQUIRED, HUMAN_GATE_REQUIRED, STALE_EXECUTION,
SUPERSEDED_WORK and UNKNOWN_FAILURE (plus SUCCESS).
Tests independently use NOT_RUN, PASSED, FAILED or UNKNOWN. Capacity/authentication
interruptions require NOT_RUN; TEST_FAILURE requires FAILED. Capacity and unknown
non-test failures do not consume the legacy test retry budget.

Provider error normalization recognizes only explicit allowlisted machine codes.
Unrecognized output stays UNKNOWN_FAILURE; prose or a generic resource-exhaustion
signal does not establish quota exhaustion. These mappings have mocked tests,
not live provider acceptance. CLI errors use sanitized messages and do not retain
raw provider responses in proposal records.

Attempt provenance stores backend ID, adapter/version, transport, execution mode,
authorization ID, previous attempt, fence, start time, typed outcome/test status,
reconstruction/result hashes and quiescence receipt/method. Backend identity is
validated against the declared registry; live launch attestation is future work.
`antigravity_cli` and `codex_cli` are CLI classes. `codex_ide_manual` is distinct and
is rejected by automated attempt creation. Only PROPOSAL_ONLY mode is accepted.

## Schema and deployment compatibility

The store adds `work_revision`, `event_sequence`, `fencing_token` (integers defaulting
to zero) and nullable `handoff_contract`; `execution_attempt_id` already existed.
The opt-in controller creates `daio_backend_control`, `daio_backend_attempts`,
`daio_backend_authorizations`, `daio_checkpoints` and `daio_work_events`.
Existing rows are not enrolled automatically. Migration tests use temporary legacy
databases and verify preservation of completed/frozen records.

A separately authorized deployment migration is required before production use.
Never run old binaries against enrolled work: old code does not honor this contract.
No production SQLite database was opened for mutation or migrated for Phase 1.

## Security boundary and remaining limitations

Backends must not receive database or workspace-write authority. Only the trusted
controller may authorize selection, supply observations or publish state. The API
is not an authentication boundary against arbitrary code with database access.
Identifiers/hashes and bounded metadata belong in records, never credentials,
cookies, tokens, API keys, sensitive headers or raw provider output. Identifier
validation is not a secret detector; trusted callers must supply non-secret values.
Future manifest collection must use an explicit safe-file allowlist, excluding
credential stores and secret-bearing files. No browser/session credentials were
inspected for this implementation.

The foundation does not wire enrolled work into live worker/supervisor execution,
enforce a provider OS sandbox, apply proposals, or implement acceptance/completion
and human-gate recovery for enrolled work. An expired executing lease without a
recorded interruption requires controlled reconciliation, not automatic takeover.
Unenrolled legacy work does not gain the C1.4 fenced publication protocol. These
limits must be resolved or explicitly bounded before live acceptance is authorized.

## Validation

Focused safety and compatibility suite: **73 passed**, including 46 C1.4 tests.
Coverage includes terminal admission, stale tokens/fences/leases, concurrent
authorization, restart reconstruction, immutable/transactional checkpoints,
unknown termination, owned process-group exit, policy denial, IDE/CLI separation,
typed capacity outcomes, no test-budget consumption, additive migration and
sanitized mocked CLI failures. Existing store/router/executor/adapter and atomic
human-gate tests also pass. No live backend or failover was invoked.

Command (with the environment's pytest-enabled Python):

```sh
python3 -m pytest -q tests/test_c14_handoff_safety.py tests/test_daio_closed_loop_store.py tests/test_daio_closed_loop_router.py tests/test_executor_with_agent.py tests/test_antigravity_cli_agent.py tests/test_baseline_aware_gate_and_atomic_human_gate.py
```
