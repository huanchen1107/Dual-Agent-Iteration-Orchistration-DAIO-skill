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
