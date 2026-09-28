# C1.4 Phase 2 — disposable manual handoff integration

Status: implementation/tests complete; pending Lead Architect review. No deployment
or Phase 3 authorization is implied. Accepted Phase-1 parent:
`f82e5f10b8e5e4ac2413ed2b8127da3647538c87` (73 tests).
C1.3 remains COMPLETE / APPROVED / FROZEN and is not modified or replayed.

## Isolation and scenario

`tests/test_c14_manual_handoff_integration.py` creates a temporary Git repository
with one allowlisted text fixture and a separate temporary SQLite database.
A and B are fake lifecycle implementations representing `antigravity_cli` and
`codex_cli`, with adapter version `phase2-fake`; no real CLI adapter is invoked.
The fake backend receives only a handoff/proposal interface. The trusted test host
owns SQLite and artifact writes. Neither backend receives workspace-write authority.
The lifecycle simulator asserts there is never more than one active fake backend.
Its termination receipt models revoked fake isolation, not real OS termination.

The scenario enrolls work, authorizes A, verifies reconstruction and grants proposal
execution. A returns BACKEND_UNAVAILABLE with tests NOT_RUN. The existing failure
count remains 1 of 3, with no FAILED/TEST_FAILURE transition. Unknown termination
blocks checkpoint publication and backend selection. After A terminates, quiescence
clears its lease; state/token validation rejects further A publication. The host
publishes a checkpoint, reopens the database/controller, explicitly authorizes B,
and creates a new attempt with the next fence. B acknowledges the exact durable
checkpoint and independently measured manifest before receiving execution authority.
B resumes `propose-arithmetic`, the next incomplete disposable step, and returns a
proposal for `2 + 2 = 4`. The host persists its artifact outside the workspace,
records SUCCESS/NOT_RUN, verifies B's termination and explicitly accepts the proposal.
The work finishes COMPLETED with a further fence advance and no live lease.

The checkpoint remains byte-for-byte unchanged from publication through B and
completion. The baseline enrollment checkpoint is a separate earlier object.
Quiescence precedes checkpoint publication, as required by the accepted Phase-1
contract. The conceptual scenario listing must not be used to bypass that guard.
A loses publication authority on interruption/state change and lease clearance;
B's new attempt additionally advances the fence. No terminal STOP transition is
used to revoke A, because that would prevent resuming the same work.

## Narrow generic-source extension

Phase 1 ended at RESULT_RECORDED / AWAITING_REVIEW. The new `DurableHandoff.complete`
method completes a proposal-only deliverable after trusted review. It requires:

- the exact current revision/sequence/attempt/fence;
- RESULT_RECORDED and a successful proposal with a result digest;
- a unique, explicit review authorization ID;
- unchanged independently measured workspace/manifest;
- an attempt-bound verified termination receipt.

The same transaction preserves termination provenance, records review authorization,
marks COMPLETED, clears the lease, advances the fence and appends the completion
event. Rejected completion leaves token/state unchanged. This reuses Phase-1 tables;
there is no additional schema migration. The authorization table stores the review
ID, while the completed control record and COMPLETED event establish its purpose.
The API is for the trusted controller, not an externally authenticated review service.
It does not apply edits, attest actual provider identity, or implement live routing.

## Verification and evidence

Combined suite: **80 passed** (7 Phase-2 integration cases, 46 Phase-1 tests,
27 compatibility tests). Negative integration cases A–F all pass:

- A: unknown termination blocks quiescence, checkpoint and replacement.
- B: stale A publications fail before and after B obtains the next fence.
- C: a wrong checkpoint hash rejects acknowledgement.
- D: a wrong workspace measurement rejects acknowledgement.
- E: completed/frozen work cannot be re-admitted.
- F: capacity interruption preserves the failure budget and NOT_RUN tests.

Additional checks cover wrong acknowledgement work/attempt/fence, execution before
acknowledgement, completion before termination, failed-result completion, changed
completion measurement, wrong termination attempt, duplicate authorization and
repeated completion. Revision and event sequence are contiguous 1–14. Fences for
attempts A, B and completion are 1, 2 and 3.

[C1_4_PHASE2_DISPOSABLE_EVIDENCE.json](C1_4_PHASE2_DISPOSABLE_EVIDENCE.json)
contains one successful run's IDs, immutable checkpoint payload/hash, acknowledgement,
actual database attempt records, event sequence/timestamps and final updated_at.
It is disposable test evidence, not production history or live-provider acceptance.
All evidence material is generated from the safe fixture; no credential files,
browser sessions, cookies, API keys or environment secrets are collected.

```sh
python3 -m pytest -q tests/test_c14_manual_handoff_integration.py tests/test_c14_handoff_safety.py tests/test_daio_closed_loop_store.py tests/test_daio_closed_loop_router.py tests/test_executor_with_agent.py tests/test_antigravity_cli_agent.py tests/test_baseline_aware_gate_and_atomic_human_gate.py
```

The run used `/Users/huanchen/opt/anaconda3/bin/python3`, which has pytest installed.

## Limits and recommended next review scope

This proves durable contract integration with fake backend lifecycle and a real
isolated Git/SQLite fixture. It does not establish live Gemini/Codex compatibility,
provider sandboxing, actual process-tree termination, domain engineering acceptance,
automatic failover or production readiness. Completion accepts a proposal artifact;
it does not apply a project patch. The workspace observer deliberately measures
only the allowlisted fixture file, not arbitrary project state.

Recommended Phase 3, only after approval: an isolated local-process lifecycle and
proposal-isolation integration using inert executables, including descendant process
termination, timeout/crash reconciliation and rejection of late results. Retain
manual authorization and disposable state; do not deploy or invoke live providers.
