# DAIO Phase C1 Recovery Model & Fault Resilience

## 1. Fault Matrix & Autonomous Recovery

| Fault Scenario | Detection Mechanism | Recovery Behavior |
|---|---|---|
| **Supervisor Daemon Restart** | PID probe / SQLite lease check | Reclaims active work leases without duplicating executions; preserves recovery epochs. |
| **Provider Process Crash** | Non-zero exit code / process death | In-flight failover to next preferred provider in federation (`Antigravity` → `Gemini` → `Codex` → `OpenCode`). |
| **Provider Timeout** | Timeout watchdog (300s budget) | Cancels hung process, records `TIMEOUT` audit record, and cascades to next provider. |
| **ChatGPT Routing Failure** | Chrome CDP endpoint probe | Resolves active project tab via `ProjectAwareArchitectRouter`; fails closed if identity cannot be verified. |
| **ChatGPT Response Timeout** | CDP stream completion watcher | Retries stream extraction or alerts supervisor without corrupting work state. |
| **Stale Decision Received** | Epoch / Work ID validator | Idempotently drops stale response; maintains active epoch. |
| **Expired Work Lease** | Handoff watchdog timer | Re-queues work for clean worker claim under a new lease ID. |

---

## 2. Invariant Protection

- **Exactly-Once Mutation**: Provider failover preserves clean state so fallback providers do not duplicate already-applied file edits.
- **Fail-Closed Security**: Policy violations, scope boundaries, and test assertion failures are never masked by provider failover.

## 3. Same-conversation browser history divergence

Operational recovery rule approved by the Lead Architect on 2026-09-28:

1. If two browser views have the exact same canonical Project ID and Conversation ID but show different conversation tails, do not immediately classify the condition as a DAIO routing failure.
2. Identify the stale view. Preserve the other view as the control and record the stale view's URL, target identity, and latest rendered messages.
3. If no active response or critical browser transaction would be disrupted, refresh the stale view exactly once using a normal page refresh.
4. If the histories converge, classify the incident as `REFRESH_RECOVERABLE_FRONTEND_VIEW_DIVERGENCE` and close it.
5. If they remain divergent after that single controlled refresh, escalate to diagnostic investigation; do not repeat refreshes as an unbounded recovery loop.
6. Do not create a replacement conversation merely to recover visibility.

Missing DOM content does not prove that a DAIO event did not occur. Correlate authoritative work state using work ID, execution attempt ID, event sequence where available, timestamps, and SQLite `updated_at`. Do not invent missing sequence values or roll authoritative state backward based on a stale browser view. This is an operational procedure, not an automated browser-routing change.

### Closed incident: DAIO-MULTI-BROWSER-HISTORY-DIVERGENCE-001

Lead Architect disposition: **APPROVE / CLOSE**, 2026-09-28. Final classification: `REFRESH_RECOVERABLE_FRONTEND_VIEW_DIVERGENCE`. Engineering decision: **NO DAIO PRODUCTION PATCH**.

- Both views used Project ID `g-p-6ab0712af5848191afeace514396d91f-zhuan-an-daio-shuang-dai-li-agent-xie-tong` and Conversation ID `6ab65f8e-2d00-83e8-93c9-df017a69f274`.
- View A retained Chrome-CDP PID `52715`, profile `Chrome-CDP/Default`, target `4A7BED1286C1FBAB59B299F89815AFC4`, and the same canonical URL across exactly one normal refresh. No new page target was created. View B was left untouched.
- At `2026-09-28T03:37:14.461Z`, A's latest user/assistant IDs were `71c74d6a-c61c-4185-832f-e4b8adebcadd` / `6ce33ae1-3181-4b5a-83af-d7ffe42e0744` (obsolete-successor escalation and STOP response).
- At `2026-09-28T03:37:20.709Z`, the refreshed, stable A view displayed the previously missing B discussion and the subsequent refresh authorization. Latest user/assistant IDs were `426f07fb-b5de-4b88-9f2f-09344bf8ad28` / `c47c2221-3310-4fa6-b551-54b41114b9e9`. Convergence was established against previously observed B content, not a simultaneous comparison of B's message IDs.
- The conversation-specific request succeeded with HTTP 200. `/backend-api/conversations` returned HTTP 429, but those responses did not prevent convergence and are insufficient to explain the stale view.
- No evidence establishes wrong-conversation routing or server-history divergence. The precise internal frontend mechanism remains **UNKNOWN**; further investigation is not required at this time.

C1.3 remains **COMPLETE / APPROVED / FROZEN** under `c1.3-full-acceptance-001`. The older `daio-root-c1-3-minimal-probe-001__to__c1.3-full-regression` successor remains superseded. This closure does not authorize C1.3 replay, production changes, SQLite mutation, acceptance-evidence repair, or C1.4.

### Separate future evidence-provenance hardening observation

The deployed `_daio/evidence/c1_3_full_acceptance.json` contains partially uncorroborated/conflicting metadata and references nonexistent paths (`_daio/cdp_adapter.py`, `_daio/browser_sync.py`, `_daio/orchestrator.py`). This does not invalidate the independently corroborated C1.3 completion and freeze. Preserve the artifact unchanged; evidence provenance should be hardened only in a future, separately authorized task. This observation is separate from the closed browser-view incident.
