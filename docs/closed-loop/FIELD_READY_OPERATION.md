# Generic DAIO field-ready operation

Generic DAIO has one durable ingress and one trusted supervisor.  `dispatch`
and `create-work` are productized wrappers for that inbox; they do not create a
second queue, work store, supervisor, or ChatGPT routing path.

## Take over a project

From an unregistered project directory, run:

```sh
daio takeover -C /path/to/project
```

Takeover is onboarding only.  It records `_daio/onboarding_state.json` with the
following durable sequence:

`TAKEOVER_REQUESTED → PROJECT_DISCOVERY → CANONICAL_REPOSITORY_DISCOVERY →
DAIO_PROVENANCE_VERIFICATION → PROJECT_REGISTRATION → CHATGPT_PROJECT_DISCOVERY
→ LEAD_ARCHITECT_CONVERSATION_DISCOVERY → CONVERSATION_BINDING →
BIDIRECTIONAL_CONNECTIVITY_CHECK → DAIO_READY`.

`DAIO_READY` means the installed Generic DAIO revision and one exact ChatGPT
Project/conversation binding were observed.  Git repository identity is an
optional engineering resource, separate from ChatGPT Project identity.  No
engineering work is submitted or started by takeover.

Takeover reports one repository state: `REMOTE_CANONICAL` for one configured
remote, `LOCAL_REPO_ONLY` for a local Git repository without a remote, or
`NO_REPOSITORY` when no Git repository exists.  All three can reach
`DAIO_READY`.  Takeover never initializes Git, creates files or commits,
creates GitHub repositories, configures a remote, or guesses from similar
repository names.  Multiple remotes and a conflict with durable repository
identity fail closed and require an explicit project-owner decision.

A project can evolve from `NO_REPOSITORY` to `LOCAL_REPO_ONLY` to
`REMOTE_CANONICAL` without changing its DAIO Project or conversation binding.
Repository-required engineering work is an explicit later transition, not an
implicit effect of onboarding.

The active browser must already expose exactly one unambiguous ChatGPT Project
conversation.  Ambiguous or missing bindings fail closed.  A CDP target ID is
only a browser target and never defines a ChatGPT conversation identity.

## Start work

After `DAIO_READY`, submit an explicit request:

```sh
daio dispatch -C /path/to/project \
  --change-id CHANGE_ID --requested-action 'bounded engineering task'
```

The default dispatch idempotency key is a deterministic hash of the logical
request and its exact routed endpoint.  Repeating that same command uses the
same root work item.  Use `--request-id` only to name an intentionally distinct
logical request.  Execution retries retain the work ID and use a new execution
attempt under the current fencing rules.

## Conversation recovery and restart

The durable endpoint contains both Project ID and Conversation ID.  If the CDP
target disappears, recovery may reopen only that exact canonical URL and then
must verify both IDs.  It must never create a new ChatGPT conversation merely
because a tab is absent.  More than one matching target is ambiguous and stops
routing.  Supervisor restart reloads the existing work, attempt, fence and
delivery ledger; it must not create replacement work or duplicate delivery.

## Completion and capacity

The terminal delivery ledger binds completion publication to work, attempt,
fence, revision and origin endpoint.  It permits at most one user-visible
completion for a logical terminal result and is restart-safe.

Provider capacity signals are separate from engineering and test failure.  Only
sanitized evidence that passes the canonical classifier may update the capacity
registry and trigger the existing checkpoint/revocation/fence/new-attempt
handoff path.  An `UNKNOWN_FAILURE` is not quota exhaustion.

## Upgrade and evidence hygiene

Upgrade a downstream installation only from a committed Generic DAIO revision,
record that revision in downstream provenance, preserve project overlays and
runtime state, then reload exactly the supervisor that owns the project.
Health checks are local and must not invoke an engineering model.  Do not place
credentials, tokens, cookies, raw provider stderr, or browser session data in
logs, evidence, Git, or documentation.

## WebAuthn Phase 0 and native dispatch

Phase 0 is frozen only after the executable verifier-backed matrix records
`WEBAUTHN_PHASE0_RESULT: PASS`. The matrix includes the valid path plus
`LEGACY_UNVERIFIED`, project/context mismatch, and required-user-verification
rejection. The Generic acceptance harness is
`scripts/daio_closed_loop/webauthn_phase0.py` and its executable matrix is
`tests/test_webauthn_phase0_acceptance.py`.

Native dispatch is a separate pre-admission path:

```text
verified WebAuthn identity
  -> authoritative credential/binding registry
  -> pre-admission dispatch ticket
  -> Cloudflare Relay
  -> outbound-only Mac poller
  -> DAIORootWorkInbox
  -> RootWorkRequest
  -> canonical Work ID
```

The binding registry is authoritative for project, ChatGPT Project, and
Conversation IDs. Caller-supplied context can only be checked against that
record; it cannot establish authority. A dispatch ticket binds credential,
binding version, `dispatch_work`, normalized task hash, client idempotency key,
and expiry. It never contains a `work_id` or `gate_id`; those exist only after
canonical inbox admission. Relay delivery is acknowledged after durable
admission, so poll retries and supervisor restart map to one root work.

## RPC-1 status write budget

`STATUS_KV` is an operational snapshot plane. The publisher observes local
state every supervisor tick, suppresses unchanged material payloads, refreshes
at most once per five-minute heartbeat, and publishes immediately when the
material status fingerprint changes. Quota/rate-limit/network failures use
bounded exponential backoff and set a local degraded marker; they never stop
inbox admission or worker execution. Credentials, challenges, action tickets,
and native dispatch tickets use the auth/decision plane and do not depend on
high-frequency status publication. Two namespaces provide isolation, not
additional Free-plan daily write allowance. At one normal five-minute
heartbeat this is at most `86,400 / 300 = 288` status writes per day, before
additional material-transition writes; unchanged observations add zero KV
writes.

## ChatGPT `dispatch_work` action connection

The relay exposes the typed action contract at `GET /openapi.json`. The
Native Dispatch operation is `POST /api/v1/dispatch/ticket` with
`operationId: dispatch_work` and schema `DispatchWorkRequest`.

ChatGPT must supply a real, single-use WebAuthn action ticket in the
`action_ticket` request field (native clients may use `X-Action-Ticket`). The
relay validates that ticket against the authoritative credential/binding
registry, project/conversation context, action name, expiry, task hash, and
idempotency key. A missing, invented, expired, or reused ticket fails closed.

To expose the operation in ChatGPT, an authorized user must create/connect a
custom GPT Action or custom MCP app using the production `/openapi.json`
metadata and allow the relay domain. This repository cannot install or enable
that ChatGPT-side connection. The real field acceptance remains blocked until
the connected ChatGPT conversation visibly exposes `dispatch_work` and invokes
it; do not create a work item manually as a substitute.
