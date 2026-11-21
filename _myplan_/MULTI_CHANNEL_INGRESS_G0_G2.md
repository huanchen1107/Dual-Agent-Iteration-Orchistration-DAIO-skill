# Multi-Channel Ingress G0–G2

Status: **PLANNING ONLY — WAITING FOR LEAD ARCHITECT REVIEW**  
Date: 2026-09-29

This document applies `ROUTE-FIRST / THIN-E2E-BEFORE-DEEP-BUILD` to future
human/client ingress. It does not modify `CredentialBinding`, Native Dispatch,
Supervisor, Inbox, or any adapter.

## Canonical identity and authorization split

The target boundary is:

```text
channel adapter
  → canonical DAIO Project Identity resolution
  → channel binding / channel authentication
  → DAIO authorization policy
  → execution authorization (WebAuthn or approved strong proof)
  → existing Native Dispatch
  → Relay / outbound poller / DAIORootWorkInbox / supervisor
```

### Canonical DAIO Project Identity

`project_id` is the authoritative identity and owns configuration, scope,
policy, work, and lifecycle. It is never inferred from a channel conversation
ID, username, page ID, or ChatGPT Project ID.

### Channel-specific binding

The future compatibility shape is a separate binding record, conceptually:

```text
ChannelBinding {
  binding_id
  project_id                 # canonical DAIO identity
  channel_type               # COCKPIT | LINE | TELEGRAM | MESSENGER | CHATGPT
  external_principal_id      # verified channel user/account/page principal
  external_conversation_ref  # channel-local thread/chat/session
  binding_version
  state                      # ACTIVE | REVOKED | PENDING
  allowed_intents/scopes
  auth_profile_ref
}
```

Channel authentication proves who controls a channel principal. It does not
prove authorization to execute engineering work. Execution authorization is a
separate policy decision and remains bound to action, project, task hash,
credential/proof, expiry, and idempotency.

## G0 — Route survey

| Route | Role | Current evidence | Main risk | Decision |
|---|---|---|---|---|
| Existing Cockpit + iPhone WebAuthn | PRIMARY_ROUTE | Implemented and deployed; real HTTPS/WebAuthn/Face ID path | iPhone/browser availability | Select primary |
| LINE Messaging API adapter | FALLBACK_ROUTE_A | Official webhook + channel access-token API | Channel account setup, webhook/token lifecycle, rate limits | Candidate, defer implementation |
| Telegram Bot API adapter | FALLBACK_ROUTE_B | Official HTTPS Bot API + webhook secret-token support | Bot token custody, webhook exposure, channel identity binding | Candidate, defer implementation |
| Messenger Platform adapter | FUTURE_ADAPTER | Meta Page/App/Webhook route exists | Page task/access-token/app-review and policy lifecycle | Future only |
| ChatGPT client/app | FUTURE_ADAPTER | Existing REST/OpenAPI backend; write-capable MCP availability is plan-dependent | Plus plan and product rollout uncertainty | Future only |
| Provider-independent authenticated HTTPS/local route | ESCAPE_HATCH | Existing relay/Cockpit contract and local DAIO paths | Must still satisfy strong execution authorization | Preserve as escape hatch |

`PRIMARY_ROUTE = Cockpit`; `FALLBACK_ROUTE_A = LINE`;
`FALLBACK_ROUTE_B = Telegram`; `ESCAPE_HATCH = provider-independent authenticated
HTTPS/local ingress`. Messenger and ChatGPT remain future adapters.

## G1 — External feasibility

Facts below were checked on 2026-09-29 against authoritative documentation.
They must be rechecked before implementation resumes.

| Dependency | Capability / requirement | Auth and limits | Lifecycle / failure risk | Source |
|---|---|---|---|---|
| iPhone Safari WebAuthn | Existing HTTPS Cockpit can call `navigator.credentials.get` with required user verification | Passkey/Face ID, challenge and ticket TTL; browser/device support required | Safari/passkey policy changes; cancelled or expired ceremony | MDN Web Authentication API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API |
| LINE Messaging API | HTTPS webhook receives events; channel access token sends replies | Channel access token; webhook endpoint and LINE developer channel required; API rate limits apply | Token revocation, webhook delivery failure, LINE channel policy/API changes | LINE Messaging API reference: https://developers.line.biz/en/reference/messaging-api |
| Telegram Bot API | HTTPS Bot API; webhook can include secret header | Bot token; webhook `secret_token`; Bot API rate limits apply | Token compromise/revocation, webhook/network failure, Telegram policy/API changes | Telegram Bot API: https://core.telegram.org/bots/api |
| Messenger Platform | Meta app/Page webhook and Page access-token model | Page/app permissions, Page access token, Meta review/policy requirements | Permission/app-review changes, token expiry, webhook changes | Meta Messenger setup: https://developers.facebook.com/docs/messenger-platform/getting-started/app-setup |
| ChatGPT custom MCP | Current official Help documentation describes full write/modify MCP for Business and Enterprise/Edu; Plus availability is not a safe assumption | Workspace developer mode/admin, remote MCP, app action approval | Rollout/plan/product snapshot and availability changes | OpenAI Help: https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt |

Channel tokens, webhook signatures, or ChatGPT app approval are channel
authentication only. None is accepted as engineering execution authorization.
Each adapter must obtain an approved execution authorization before invoking
Native Dispatch.

## G2 — Architecture selection

```yaml
PRIMARY_ROUTE: EXISTING_COCKPIT
FALLBACK_ROUTES:
  - LINE_MESSAGING_API
  - TELEGRAM_BOT_API
FUTURE_ADAPTERS:
  - MESSENGER_PLATFORM
  - CHATGPT_CLIENT_OR_APP
ESCAPE_HATCH: PROVIDER_INDEPENDENT_AUTHENTICATED_HTTPS_OR_LOCAL_INGRESS
EXTERNAL_DEPENDENCIES:
  - iPhone Safari/WebAuthn
  - Cloudflare HTTPS relay
  - optional channel webhook/token platforms
SWITCHING_COST: Adapter-only for transport; shared policy/Native Dispatch/inbox/supervisor remain unchanged
SELECTION_REASON: Cockpit is already real, secure, deployed, and has the lowest external uncertainty
```

### Minimal channel-neutral ingress contract

The future adapter boundary should normalize into one envelope before Native
Dispatch:

```text
CanonicalIngressCommand {
  ingress_id
  project_id                 # required canonical DAIO identity
  channel_type
  channel_binding_id
  external_principal_ref
  external_conversation_ref
  command_text / normalized_task
  requested_action
  requested_role
  idempotency_key
  channel_auth_proof_ref     # channel authentication only
  execution_auth_ref        # WebAuthn/strong authorization, separate
  provenance
}
```

Native Dispatch receives the canonical project/task/idempotency and execution
authorization fields. Supervisor, poller, inbox, Work ID creation, and provider
execution remain untouched.

## Compatibility migration plan (no implementation yet)

1. **Preserve V1:** keep current `CredentialBinding`, ChatGPT Project ID,
   Conversation ID, and `8739a3c` Cockpit behavior unchanged.
2. **Add a compatibility view later:** expose current ChatGPT binding as a
   channel-specific projection of the canonical project identity; do not rewrite
   existing records.
3. **Dual-read boundary:** future ingress resolution first reads the new
   channel-neutral binding when present, then falls back to the legacy ChatGPT
   fields for existing work and replay.
4. **Dual-write only after approval:** new bindings may write both the generic
   record and the legacy projection, with one binding/version and explicit
   provenance. No silent migration of historical tickets or emitted requests.
5. **Native Dispatch compatibility:** retain the existing ticket/task hash and
   idempotency semantics; add channel context as provenance/policy input, not as
   a replacement identity or a second work lifecycle.
6. **Cutover gate:** only after a future adapter passes G0–G3 may its route be
   enabled. Historical ChatGPT records remain replayable through the legacy
   projection.

## Gate status

```yaml
G0_ROUTE_SURVEY: PASS
G1_EXTERNAL_FEASIBILITY: PASS_WITH_CHATGPT_PLAN_UNCERTAINTY
G2_ARCHITECTURE_SELECTION: PROPOSED
G3_THIN_REAL_E2E: NOT_STARTED
G4_DEEP_IMPLEMENTATION: NOT_AUTHORIZED
```

No LINE, Telegram, Messenger, or ChatGPT adapter is implemented. V1 voice
remains iPhone native keyboard dictation only; no custom voice subsystem is
proposed.
