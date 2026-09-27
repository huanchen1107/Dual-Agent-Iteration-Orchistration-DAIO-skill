# DAIO Agent Portability: Adapter Registry & Resolution

## 1. Registry Architecture

The `AgentAdapterRegistry` manages available agent adapters dynamically based on configuration. DAIO Core queries the registry via logical role and required capabilities.

```text
               ┌──────────────────────────────┐
               │    DAIO CLOSED LOOP FSM      │
               └──────────────┬───────────────┘
                              │
                    Resolve(Role, Capabilities)
                              │
                              ▼
               ┌──────────────────────────────┐
               │     AgentAdapterRegistry     │
               │                              │
               │  - Priority Order            │
               │  - Fallback Cascades         │
               │  - Health Checks             │
               └──────────────┬───────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  Primary     │       │  Secondary   │       │  Fallback    │
│  Adapter     │       │  Adapter     │       │  Adapter     │
│  (Ready)     │       │  (Degraded)  │       │  (Ready)     │
└──────────────┘       └──────────────┘       └──────────────┘
```

---

## 2. Configuration Schema

Project configurations define primary and fallback chains per role without requiring vendor-specific Python code in Core:

```json
{
  "agents": {
    "LEAD_ARCHITECT": {
      "primary": {
        "provider": "CHATGPT_WEB",
        "adapter_type": "bridge",
        "endpoint": {
          "routing_policy": "EXACT_CONVERSATION",
          "cdp_port": 9222
        }
      },
      "fallback": {
        "provider": "GEMINI",
        "adapter_type": "api",
        "model": "gemini-2.5-pro"
      }
    },
    "ENGINEERING_EXECUTION": {
      "primary": {
        "provider": "ANTIGRAVITY_CLI",
        "adapter_type": "cli",
        "unattended": true,
        "sandbox": true
      },
      "fallback": {
        "provider": "GEMINI",
        "adapter_type": "api",
        "model": "gemini-2.5-pro"
      }
    }
  }
}
```

---

## 3. Resolution & Health Verification

1. **Resolution Step:**
   - Filters registered adapters matching `logical_role`.
   - Filters by advertised `AgentCapability` subset.
   - Evaluates `AgentHealth`: checks `status == READY` or `DEGRADED`.
   - Selects highest priority ready adapter.
2. **Fallback Step:**
   - If primary adapter health check fails (`UNAVAILABLE` or `MISCONFIGURED`), registry automatically switches to next compatible fallback.
   - Emits a health warning in the execution report.
3. **Fail-Closed Boundary:**
   - If no healthy compatible adapter exists, execution halts and escalates to `HUMAN_GATE_REQUIRED` or `BLOCKED` with `PROVIDER_UNAVAILABLE`.
