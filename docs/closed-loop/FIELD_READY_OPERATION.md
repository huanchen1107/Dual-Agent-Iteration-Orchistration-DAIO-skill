# Generic DAIO field-ready operation

Generic DAIO has one durable ingress and one trusted supervisor.  `dispatch`
and `create-work` are productized wrappers for that inbox; they do not create a
second queue, work store, supervisor, or ChatGPT routing path.

## Take over a project

From an unregistered Git project, run:

```sh
daio takeover -C /path/to/project
```

Takeover is onboarding only.  It records `_daio/onboarding_state.json` with the
following durable sequence:

`TAKEOVER_REQUESTED → PROJECT_DISCOVERY → CANONICAL_REPOSITORY_DISCOVERY →
DAIO_PROVENANCE_VERIFICATION → PROJECT_REGISTRATION → CHATGPT_PROJECT_DISCOVERY
→ LEAD_ARCHITECT_CONVERSATION_DISCOVERY → CONVERSATION_BINDING →
BIDIRECTIONAL_CONNECTIVITY_CHECK → DAIO_READY`.

`DAIO_READY` means the repository HEAD, installed Generic DAIO revision and one
exact ChatGPT Project/conversation binding were observed.  No engineering work
is submitted or started by takeover.

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
