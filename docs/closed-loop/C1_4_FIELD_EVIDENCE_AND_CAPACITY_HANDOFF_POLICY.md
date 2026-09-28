# C1.4 field evidence and capacity handoff policy

Status: **canonical operational policy**

Operational mode: **FIELD_ACCEPTANCE**

Next useful workload: **RETURN_TO_NORMAL_ENGINEERING / SMC7S**

This document freezes the current C1.4 operational state and governs future
field evidence. It does not reopen C1.3, authorize provider probes, deploy DAIO,
or change the accepted handoff implementation.

## Current acceptance state

### Phase 5C

Phase 5C is **BLOCKED_BY_REAL_CODEX_UNKNOWN_FAILURE**. This state is neither a
pass, an engineering failure, nor a capacity failure.

The established facts are:

- Codex CLI 0.150.1 previously completed a real execution successfully.
- Support for its nested `item.completed.item.text` response envelope was added
  in parser repair commit `1fd5b8ac9a48b5c8551edeec3648f8066ff906dc`.
- Sanitized diagnostic classification was added in commit
  `b38c21c0c5a60ec8f0462fc3c00b26161455d437`.
- A later real Codex execution exited nonzero. The available evidence did not
  establish capacity, authentication, incompatibility, repository, permission,
  or another known failure class.
- DAIO classified the result as `UNKNOWN_FAILURE` and failed closed.

The accepted regression baseline for this state is **507 passed, 0 failed,
0 skipped**.

### Phase 5B-2

Phase 5B-2 remains **PENDING_REAL_CAPACITY_EVENT / NOT_RUN**. DAIO must not
manufacture a provider-capacity failure to complete acceptance.

## Unknown-failure field policy

When a real backend returns `UNKNOWN_FAILURE`, DAIO must not infer quota or
capacity and must not switch backends solely because the result is unknown.
Execution fails closed while a sanitized packet from that same event is
preserved where available. The packet should contain:

- timestamp, work ID, execution-attempt ID, backend ID, and model ID;
- CLI/provider version and appropriate executable identity;
- exit code and event sequence/types;
- sanitized argument shape, working-directory class, and transport method;
- stdout classification and sanitized stderr diagnostic classification;
- checkpoint state, fence, work revision, event sequence, and authority state.

The packet must never persist credentials, access or refresh tokens, API keys,
session secrets, authentication headers, or raw sensitive environment data.
`UNKNOWN_FAILURE` remains fail closed until supported evidence establishes a
known class.

## Capacity-event policy

A real execution enters capacity handling only when provider evidence supports
a canonical classification such as `CAPACITY_EXHAUSTED`, `RATE_LIMITED`, or
`TEMPORARILY_UNAVAILABLE`. These outcomes are execution-capacity conditions,
not engineering or test failures.

The only authorized path is the existing architecture:

```text
backend execution
  -> canonical outcome classification
  -> CapacityRegistry
  -> CapacityHandoffController
  -> Phase 4E orchestrator handoff
```

No second quota manager, registry, or handoff subsystem may be introduced.

## Codex and Gemini handoff policy

Codex and Gemini have no permanent primary/secondary assignment. Selection is
based on authorization, safety-contract compatibility, work compatibility,
fresh capacity evidence, an `AVAILABLE` state, and deterministic policy.

After a genuine capacity event, DAIO must stop admission to the failing
attempt, preserve and verify its checkpoint, revoke its authority, advance the
fence, select an eligible available backend, create a new execution-attempt ID,
and resume the same work ID. This permits Codex-to-Gemini and Gemini-to-Codex
handoffs when policy and evidence support them.

A low UI percentage alone cannot authorize a switch. It may affect selection
only if an approved machine-readable observation mechanism later makes it
trusted DAIO evidence.

## Capacity-observability limitation

Current supported Antigravity and DAIO local interfaces do not expose a trusted
pre-execution API for the UI's exact remaining quota percentage or reset time.
DAIO must not invent those values. Operational capacity is learned through
supported observations and real provider execution outcomes. A future supported
API may be integrated after separate review.

The detailed historical investigation is preserved in
[C1_4_CAPACITY_OBSERVABILITY_INVESTIGATION.md](C1_4_CAPACITY_OBSERVABILITY_INVESTIGATION.md).

## Field acceptance

Infrastructure work does not remain blocked to force Phase 5C or Phase 5B-2.
Normal engineering work, including SMC7S, may provide the field workload:

```text
UNKNOWN_FAILURE
  -> capture sanitized evidence
  -> fail closed
  -> diagnose from that real event

GENUINE CAPACITY EVENT
  -> existing automatic capacity handoff
  -> capture Phase 5B-2 evidence

NORMAL SUCCESS
  -> continue normally
```

When a natural capacity event occurs, Phase 5B-2 evidence must identify the
original backend, canonical classification, registry update, checkpoint
verification, authority revocation, fence advancement, replacement selection,
new attempt ID, unchanged work ID, resumed execution, and final outcome.

## Safety invariants

Field acceptance preserves:

- `HUMAN_RELAY_COUNT = 0` as the target;
- same-work handoff semantics;
- fencing and checkpoint verification;
- authority revocation;
- unified admission and the Trusted Writer boundary;
- fail-closed handling of unknown outcomes;
- no direct candidate mutation of the authoritative repository;
- no silent fallback around DAIO safety controls.

## Implementation and evidence references

- Phase 4C registry: [`capacity.py`](../../scripts/daio_closed_loop/capacity.py),
  introduced by commit `77a036e`.
- Phase 4D controller: [`capacity_handoff_v2.py`](../../scripts/daio_closed_loop/capacity_handoff_v2.py),
  accepted through commit `0804f8c`.
- Phase 4E integration: [`orchestrator.py`](../../scripts/daio_closed_loop/orchestrator.py),
  integrated by `39322be` and repaired through `8f28f59`.
- Handoff safety foundation:
  [C1_4_HANDOFF_SAFETY_FOUNDATION.md](C1_4_HANDOFF_SAFETY_FOUNDATION.md).
- Unified admission and Trusted Writer:
  [C1_4_PHASE3B3_UNIFIED_ADMISSION.md](C1_4_PHASE3B3_UNIFIED_ADMISSION.md).
- Phase 5C parser repair: commit `1fd5b8a`.
- Phase 5C diagnostic repair: commit `b38c21c`.

Historical evidence remains historical. This document is the current
operational policy and handoff point.
