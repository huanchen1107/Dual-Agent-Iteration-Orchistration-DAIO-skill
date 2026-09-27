# DAIO Portability: Provider Capability Registry, Router & Failover Engine (Phase B5)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B5`  
**Status**: `APPROVED`  

---

## 1. Architecture Overview

Under `PORTABILITY-PHASE-B5`, Generic DAIO introduces a provider-neutral **Agent Federation Router & Provider Capability Registry** operating strictly at the adapter/orchestration boundary outside of DAIO Core FSM.

```text
                  DAIO Core
       (Orchestration, FSM, Human Gate)
                      │
           daio-agent/v1 Contract
                      │
         ┌────────────┴─────────────┐
         │ Provider Capability      │
         │ Registry & Discovery     │
         │ (State: NOT_INSTALLED,   │
         │  AVAILABLE, AUTH_REQ...) │
         └────────────┬─────────────┘
                      │
         ┌────────────┴─────────────┐
         │     Provider Router      │
         │  (Preferred Policy &     │
         │   Failover Engine)       │
         └────────────┬─────────────┘
                      │
     ┌────────────────┼────────────────┬────────────────┐
     │                │                │                │
Antigravity      Gemini CLI       Codex CLI        OpenCode CLI
CLI Adapter      CLI Adapter      CLI Adapter      CLI Adapter
(LOGIN_SESSION)  (LOGIN_SESSION)  (LOGIN_SESSION)  (PROVIDER_DEP)
     │
Claude Code CLI (Future Ready: NOT_INSTALLED)
```

---

## 2. Provider Capability Registry & State Machine

The registry enforces strict separation between binary discovery on disk and operational routing availability:

$$\text{DISCOVERED} \neq \text{AVAILABLE}$$

### Operational Provider States (`ProviderState`):
- `NOT_INSTALLED`: Binary not found on host machine.
- `DISCOVERED`: Binary detected on filesystem/PATH, but authentication, session markers, or health probe have not yet validated unattended execution readiness.
- `AVAILABLE`: Binary installed, login session / credentials validated, fully operational for unattended task routing.
- `AUTH_REQUIRED`: Binary installed, but active login session or credentials missing/expired.
- `DEGRADED`: Binary usable but operating under degraded health, rate limit warnings, or missing non-critical capabilities.
- `UNAVAILABLE`: Binary crashed, probe failed, or transient system error.

### Normalized Provider Metadata Schema:
```python
@dataclass
class ProviderDescriptor:
    provider_id: str
    display_name: str
    transport: ProviderTransport          # CLI, API, CDP, IPC
    auth_mode: AuthMode                  # LOGIN_SESSION, PROVIDER_DEPENDENT, API_KEY
    state: ProviderState                 # NOT_INSTALLED, AVAILABLE, AUTH_REQUIRED...
    installation_status: InstallationStatus
    auth_status: AuthStatus
    availability: AvailabilityStatus
    capabilities: Set[AgentCapability]
    supported_roles: Set[AgentRole]
    executable: Optional[str]
    version: Optional[str]
    supports_non_interactive: bool
    supports_structured_output: bool
    supports_sandbox: bool
    supports_unattended: bool
    model: Optional[str]
    underlying_provider: Optional[str]
    health: str
    last_probe_at: str
    metadata: Dict[str, Any]
```

---

## 3. Provider Routing Policy & Deterministic Selection

The router dynamically evaluates provider candidate order per logical role without modifying DAIO Core:

```yaml
engineering:
  preferred:
    - antigravity_cli
    - gemini_cli
    - codex_cli
    - opencode_cli
  failover: true
```

*Note: This preference list is a configuration default for acceptance testing, not a hardcoded ranking.*

---

## 4. Strict Failover Taxonomy & Semantics

Failover is permitted **ONLY** for provider/runtime availability failures:

| Permitted Failover Reasons (`RoutingFailureType`) | Description |
| :--- | :--- |
| `BINARY_UNAVAILABLE` | Executable missing from host PATH and fallback directories. |
| `AUTH_UNAVAILABLE` | Login session expired or credential missing (`AUTH_REQUIRED`). |
| `SESSION_EXPIRED` | Host login token expired during execution. |
| `PROVIDER_UNAVAILABLE` | Process crashed or backend unreachable. |
| `TIMEOUT` | Subprocess execution exceeded allocated timeout budget. |
| `RATE_LIMIT` | Provider returned HTTP 429 or quota exhaustion error. |
| `TRANSIENT_NETWORK_ERROR` | Connection drop or socket reset. |
| `MALFORMED_PROVIDER_RESPONSE` | Process returned non-zero exit code or unparseable envelope. |

### Forbidden Failover Scenarios:
Failover is **STRICTLY PROHIBITED** for workflow and validation outcomes:
1. **Tests Failed**: A test failure during DAIO validation is an execution result, not a provider availability failure. No provider search is allowed.
2. **`allowed_scope` Violation**: If a proposal touches files outside `allowed_scope`, DAIO Two-Tier policy engine blocks the mutation. No fallback occurs.
3. **`frozen_paths` Touched**: Blocked by DAIO Executor.
4. **Architect Rejected Implementation**: Workflow decision routed to retry loop or Human Gate.
5. **`HUMAN_GATE` Required**: Human signature is authoritative; no provider can route around it.

---

## 5. Failover Audit Trail Schema (`FailoverAuditRecord`)

Every routing attempt generates a structured, immutable audit trail preserved in evidence:

```json
{
  "routing_id": "route-a1b2c3d4",
  "work_id": "work-example-001",
  "requested_capabilities": ["PROPOSE_EDITS", "READ_REPOSITORY"],
  "preferred_order": ["antigravity_cli", "gemini_cli", "codex_cli", "opencode_cli"],
  "provider_attempts": [
    {
      "provider_id": "antigravity_cli",
      "timestamp": "2026-09-27T11:30:00.000Z",
      "status": "FAILURE",
      "failure_reason": "TIMEOUT",
      "latency_ms": 30012.5,
      "details": {"error_message": "Subprocess timed out"}
    },
    {
      "provider_id": "gemini_cli",
      "timestamp": "2026-09-27T11:30:30.100Z",
      "status": "SUCCESS",
      "latency_ms": 2410.2,
      "model": "gemini-2.5-pro",
      "details": {"proposed_edits_count": 1}
    }
  ],
  "selected_provider": "gemini_cli",
  "fallback_occurred": true,
  "fallback_reason": "Failover triggered by antigravity_cli TIMEOUT",
  "started_at": "2026-09-27T11:30:00.000Z",
  "completed_at": "2026-09-27T11:30:32.510Z"
}
```

---

## 6. Claude Code CLI Future-Readiness

Claude Code is registered in the capability descriptor model as:
```text
claude_code:
    installed: false
    state: NOT_INSTALLED
    availability: UNAVAILABLE
```
When installed in the future, integrating Claude Code will require only:
1. `ClaudeCodeCLIAdapter` class implementation.
2. Capability discovery registration.
3. Policy configuration update.
Zero Core FSM or orchestrator changes will be required.
