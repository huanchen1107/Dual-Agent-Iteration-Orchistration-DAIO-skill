# External Dependency Register

Canonical register for current substantial DAIO external dependencies. Mutable
entries must be re-verified at the G1 gate before implementation resumes.

## ChatGPT Native Dispatch integration lesson

| Field | Value |
|---|---|
| DEPENDENCY | ChatGPT callable write/action integration |
| PURPOSE | Architect-originated Native Dispatch command ingress |
| CURRENT_CAPABILITY | Existing REST/OpenAPI `dispatch_work`; ChatGPT custom MCP write path unavailable on active Plus plan |
| PLAN_REQUIREMENT | Business or Enterprise/Edu for full custom MCP write/modify support (verify before use) |
| CLIENT_SUPPORT | ChatGPT web; current Plus account does not expose the required write-capable custom MCP route |
| AUTH_MODEL | WebAuthn/Face ID action ticket, authoritative project/conversation binding |
| QUOTA_OR_RATE_LIMIT | Provider/account-plan dependent; verify current official limits at G1 |
| LIFECYCLE_RISK | Product rollout, plan eligibility, API deprecation, connector snapshot changes |
| FAILURE_MODE | Backend ready but external client cannot expose or invoke write action |
| FALLBACK | Existing Cockpit; future channel-neutral ingress; provider-independent local route |
| LAST_VERIFIED_AT | 2026-09-29 |
| AUTHORITATIVE_SOURCE | https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt |

## Cloudflare Relay

| Field | Value |
|---|---|
| DEPENDENCY | Cloudflare Workers/KV/Durable Objects |
| PURPOSE | Authenticated relay, ticket authority, status plane |
| CURRENT_CAPABILITY | Production Worker with WebAuthn, `dispatch_work`, TicketAuthority, STATUS_KV and DECISION_KV |
| PLAN_REQUIREMENT | Active Cloudflare account and configured bindings/secrets |
| CLIENT_SUPPORT | HTTPS mobile/web clients and outbound Mac poller |
| AUTH_MODEL | WebAuthn action tickets; relay secret for outbound poller/admin paths |
| QUOTA_OR_RATE_LIMIT | KV write limits and Worker platform limits; status plane is backoff-isolated |
| LIFECYCLE_RISK | Worker/runtime/API changes, quota changes, Durable Object migrations |
| FAILURE_MODE | Relay unavailable, quota degradation, ticket or binding rejection |
| FALLBACK | Local durable inbox/supervisor path; bounded retry; no inbound Mac port |
| LAST_VERIFIED_AT | 2026-09-29 |
| AUTHORITATIVE_SOURCE | https://developers.cloudflare.com/workers/ |

## iPhone Safari / WebAuthn

| Field | Value |
|---|---|
| DEPENDENCY | iPhone Safari WebAuthn / Face ID |
| PURPOSE | Human execution authorization for Cockpit command ingress |
| CURRENT_CAPABILITY | `navigator.credentials.get`, user verification required, HTTPS relay origin |
| PLAN_REQUIREMENT | Compatible iOS/Safari device with enrolled passkey |
| CLIENT_SUPPORT | iPhone Safari; Home Screen installation is optional convenience |
| AUTH_MODEL | WebAuthn assertion verified at Cloudflare; single-use short-lived ticket |
| QUOTA_OR_RATE_LIMIT | Challenge and action-ticket TTLs; browser/platform availability |
| LIFECYCLE_RISK | Safari/WebAuthn behavior and passkey policy changes |
| FAILURE_MODE | Cancelled assertion, unsupported browser, expired challenge, invalid credential |
| FALLBACK | Explicit human gate; no custom voice subsystem in V1 |
| LAST_VERIFIED_AT | 2026-09-29 |
| AUTHORITATIVE_SOURCE | https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API |
