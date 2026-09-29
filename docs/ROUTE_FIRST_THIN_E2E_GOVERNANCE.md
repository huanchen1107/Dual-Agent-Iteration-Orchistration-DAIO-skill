# ROUTE-FIRST / THIN-E2E-BEFORE-DEEP-BUILD

Status: **CANONICAL GENERIC DAIO GOVERNANCE**
Effective: 2026-09-29

## Purpose

Any substantial DAIO feature that depends on an external product, SaaS, API,
account plan, client platform, authentication mechanism, or execution provider
must validate the riskiest external boundary before deep implementation.

This rule is prospective. It does not rewrite historical evidence.

## Required gates

### G0 — Route survey

Record realistic implementation routes:

- `PRIMARY_ROUTE`
- `FALLBACK_ROUTE_A`
- `FALLBACK_ROUTE_B` when appropriate
- `ESCAPE_HATCH` / provider-independent route

### G1 — External feasibility

Verify against current authoritative documentation, not memory or old notes:

- account/plan requirements;
- mobile/web/desktop support;
- read/write capability;
- authentication and authorization;
- quota/rate limits;
- lifecycle/deprecation risk;
- deployment/network restrictions;
- official source and date last verified.

### G2 — Architecture selection

Record the selected route, fallback routes, escape hatch, external
dependencies, switching cost, and selection rationale.

### G3 — Thin real end-to-end

Before deep implementation, execute the smallest safe **real** vertical slice
across the highest-risk external boundary. Mocks and unit tests do not satisfy
G3 when external integration is the primary risk. The slice must be bounded,
reversible, non-destructive, and independently evidenced.

### G4 — Deep implementation

Only after G0–G3 pass may the team perform substantial hardening, abstraction,
recovery, optimization, or expansion. If a gate fails, stop the affected scope
and select a fallback or obtain an explicit architecture decision.

## External Dependency Register

Every dependency used by a substantial feature must have a register entry with
at least these fields:

```text
DEPENDENCY
PURPOSE
CURRENT_CAPABILITY
PLAN_REQUIREMENT
CLIENT_SUPPORT
AUTH_MODEL
QUOTA_OR_RATE_LIMIT
LIFECYCLE_RISK
FAILURE_MODE
FALLBACK
LAST_VERIFIED_AT
AUTHORITATIVE_SOURCE
```

The register is evidence, not a substitute for G0–G3. Mutable facts must be
re-verified when a feature resumes after interruption or external change.

## Motivating lesson: Native Dispatch / ChatGPT

Generic Native Dispatch, WebAuthn, Cloudflare Relay, and the Mac poller were
implemented before the ChatGPT account-plan and write-capable integration route
was proven. The backend remained valid, but the intended ChatGPT callable path
was unavailable on the active Plus plan. Under this rule, the plan capability
would have been verified in G1 and a thin real external slice would have been
required in G3 before deep integration work.

The accepted current ingress direction is:

```text
Cockpit / LINE / Telegram / Messenger / ChatGPT / future clients
    → channel-neutral canonical ingress
    → DAIO authorization policy
    → existing Native Dispatch
    → existing Relay / poller / inbox / supervisor
```

Cockpit remains the first implemented client. This governance document does not
implement or refactor any future adapter.

## Voice boundary

V1 voice input is limited to iPhone native keyboard dictation. DAIO does not
create a custom voice subsystem under this governance rule.
