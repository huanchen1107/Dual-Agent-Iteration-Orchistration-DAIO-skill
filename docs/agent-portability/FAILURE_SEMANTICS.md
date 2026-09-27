# DAIO Agent Portability: Normalized Failure Semantics

## 1. Objective
Vendor-specific API exceptions, HTTP errors, CLI exit codes, and rate limits must never leak directly into DAIO Core state-machine logic. Adapters must normalize all operational issues into standard `AgentFailure` descriptors.

---

## 2. Failure Types & Recovery Classification

| Failure Type Enum | Description | Recovery Classification | Default DAIO Action |
|---|---|---|---|
| `TIMEOUT` | Execution exceeded `timeout_seconds` | `RETRYABLE` | Retry up to attempt limit; escalate if progress stalls |
| `PROVIDER_UNAVAILABLE` | Network down, endpoint unreachable | `RETRYABLE` | Exponential backoff or fallback adapter switch |
| `RATE_LIMITED` | Vendor quota or token limit hit | `RETRYABLE` | Pause with bounded backoff |
| `AUTH_FAILURE` | Invalid or expired credentials | `NON_RETRYABLE` | Fail closed; alert operator |
| `CAPABILITY_MISMATCH` | Adapter lacks required capabilities | `NON_RETRYABLE` | Fail closed before invocation |
| `INVALID_RESPONSE` | Malformed JSON or unparseable schema | `NON_RETRYABLE` | Reject proposal; request revision |
| `TOOL_FAILURE` | Tool or compiler command failed | `RETRYABLE` | Record stderr evidence in turn history |
| `CONTRACT_VIOLATION` | Scope violation, missing required fields | `HUMAN_GATE_REQUIRED` | Stop execution; trigger Human Gate |
| `SECURITY_BOUNDARY_VIOLATION` | Attempted write to frozen/protected paths | `HUMAN_GATE_REQUIRED` | Immediate safety halt |
| `UNKNOWN_FAILURE` | Unhandled exception | `NON_RETRYABLE` | Log diagnostics; fail closed |

---

## 3. Normalized `AgentFailure` Schema

```json
{
  "failure_type": "TIMEOUT",
  "recovery_classification": "RETRYABLE",
  "message": "Process timed out after 300 seconds without producing output.",
  "details": {
    "elapsed_seconds": 300.2,
    "pid": 41203,
    "last_activity_at": "2026-09-27T10:40:00Z"
  }
}
```

DAIO Watchdog and Recovery modules consume `recovery_classification` to make deterministic recovery decisions:
- `RETRYABLE`: Incidental restart within attempt budget.
- `NON_RETRYABLE`: Transition work item to `BLOCKED`.
- `HUMAN_GATE_REQUIRED`: Atomically transition work item to `HUMAN_GATE_REQUIRED`.
