# DAIO Agent Portability: Canonical Agent Contract (daio-agent/v1)

## 1. Objective & Philosophy
The DAIO Core must orchestrate **logical roles and capabilities**, not specific AI vendors or model APIs. 
DAIO Core FSM, Work Store, Gates, Leasing, Watchdogs, Supervisor, and Human Gate mechanisms must remain 100% provider-independent.

Vendor-specific prompting, API payloads, response parsing, and error mapping belong exclusively inside **Adapters**.

---

## 2. Layer Separation Model

```text
┌─────────────────────────────────────────────────────────┐
│                      PROJECT OWNER                      │
│            HUMAN_GATE / PASSKEY AUTHENTICATION          │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                        DAIO CORE                        │
│                                                         │
│   FSM • Work Store • Gates • Leasing • Watchdog         │
│   Evidence • Audit • Supervisor • HUMAN_GATE            │
│                                                         │
│             STRICTLY PROVIDER-INDEPENDENT               │
└────────────────────────────┬────────────────────────────┘
                             │
                  Canonical Agent Contract
                   (AgentRequest / AgentResponse)
                             │
                             ▼
              ┌─────────────────────────────┐
              │    AGENT ADAPTER REGISTRY   │
              │  (Role + Capability Match)  │
              └──────────────┬──────────────┘
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
  ┌──────────────────────┐       ┌──────────────────────┐
  │  ARCHITECT ADAPTERS  │       │ ENGINEERING ADAPTERS │
  └──────────┬───────────┘       └──────────┬───────────┘
             │                              │
       ┌─────┼─────┐                  ┌─────┼─────┐
       ▼     ▼     ▼                  ▼     ▼     ▼
    ChatGPT Gemini Claude            AGY  Claude Codex
      ... future ...                    ... future ...
```

---

## 3. Logical Roles (`AgentRole`)

DAIO Core supports N-role federation beyond the classic two-agent model:

| Role Enum | Description | Typical Capabilities |
|---|---|---|
| `LEAD_ARCHITECT` | High-level system design, milestone review, contract approval | `ARCHITECT_REVIEW`, `STRUCTURED_DECISION` |
| `ENGINEERING_EXECUTION` | Implementation of change tasks, automated code editing | `READ_REPOSITORY`, `WRITE_REPOSITORY`, `RUN_TESTS` |
| `RESEARCH_AGENT` | Autonomous domain, market, and codebase research | `READ_REPOSITORY`, `WEB_RESEARCH` |
| `REVIEW_AGENT` | Code quality, lint, security, and invariant auditing | `READ_REPOSITORY`, `STRUCTURED_DECISION` |
| `TEST_AGENT` | Test generation, fuzzing, and benchmark execution | `READ_REPOSITORY`, `RUN_TESTS`, `RUN_COMMANDS` |
| `OPTIONAL_SPECIALIST` | Domain-specific pluggable autonomous capability | Dynamic |

---

## 4. Agent Identity (`AgentIdentity`)

Every adapter advertises an immutable identity envelope:

```json
{
  "logical_role": "ENGINEERING_EXECUTION",
  "provider": "antigravity",
  "adapter_type": "cli",
  "model": "gemini-2.5-pro",
  "instance_id": "engineering-primary",
  "capability_version": "1",
  "contract_version": "daio-agent/v1",
  "metadata": {
    "sandbox": true,
    "unattended": true
  }
}
```

---

## 5. Canonical Agent Request (`AgentRequest`)

DAIO Core dispatches work using the versioned `AgentRequest` envelope:

```json
{
  "contract_version": "daio-agent/v1",
  "request_id": "req-20260927-001",
  "work_id": "daio-work-change-052",
  "change_id": "CHANGE_052_PORTABILITY",
  "role": "ENGINEERING_EXECUTION",
  "requested_capabilities": [
    "READ_REPOSITORY",
    "WRITE_REPOSITORY",
    "RUN_TESTS"
  ],
  "instruction": "Implement provider-neutral capability model and adapter registry.",
  "project_root": "/Users/huanchen/workspace/project",
  "allowed_scope": ["scripts/**", "tests/**", "docs/**"],
  "frozen_paths": ["_daio/state.db", "keys/**"],
  "base_sha": "3836a3e9",
  "head_sha": "b41cb0c4",
  "evidence_refs": ["evidence/audit_log.json"],
  "timeout_seconds": 300,
  "metadata": {}
}
```

---

## 6. Canonical Agent Response (`AgentResponse`)

Adapters normalize raw outputs into a unified `AgentResponse` before DAIO Core inspects it:

```json
{
  "contract_version": "daio-agent/v1",
  "request_id": "req-20260927-001",
  "agent_identity": {
    "logical_role": "ENGINEERING_EXECUTION",
    "provider": "antigravity",
    "adapter_type": "cli",
    "model": "gemini-2.5-pro",
    "instance_id": "engineering-primary",
    "capability_version": "1",
    "contract_version": "daio-agent/v1"
  },
  "status": "SUCCESS",
  "summary": "Implemented capability contract and registered mock adapters.",
  "decision": null,
  "artifacts": [
    {
      "path": "docs/agent-portability/AGENT_CONTRACT.md",
      "action": "CREATE"
    }
  ],
  "evidence": [
    {
      "evidence_type": "TEST_OUTPUT",
      "uri": "_daio/evidence/test_run.log",
      "description": "Pytest 201 passed"
    }
  ],
  "commands": ["pytest tests/test_agent_portability.py"],
  "changed_files": ["scripts/daio_closed_loop/adapters/agent_contract.py"],
  "test_results": [
    {"suite": "contract_tests", "passed": 10, "failed": 0}
  ],
  "warnings": [],
  "failure": null,
  "started_at": "2026-09-27T10:45:00Z",
  "completed_at": "2026-09-27T10:45:15Z"
}
```

---

## 7. Portability Invariant (`DAIO-PORTABILITY-INVARIANT-001`)

> **Invariant Definition:** Replacing an AI provider for a compatible logical role MUST require only adapter/configuration changes and MUST NOT require modifications to DAIO Core orchestration, FSM, work-store, gate, lease, recovery, HUMAN_GATE, or provenance semantics.
