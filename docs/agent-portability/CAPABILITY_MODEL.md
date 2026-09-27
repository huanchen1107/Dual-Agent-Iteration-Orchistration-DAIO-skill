# DAIO Agent Portability: Capability Negotiation Model

## 1. Capability Taxonomy

Agents advertise specific functional capabilities (`AgentCapability`). DAIO Core uses these advertisements to resolve compatible adapters for work items without inspecting provider brand names.

```text
┌─────────────────────────────────────────────────────────────┐
│                    CAPABILITY TAXONOMY                      │
├────────────────────────────┬────────────────────────────────┤
│ Repository Operations      │ READ_REPOSITORY                │
│                            │ WRITE_REPOSITORY               │
│                            │ PROPOSE_EDITS                  │
│                            │ GIT_COMMIT                     │
│                            │ GIT_PUSH                       │
├────────────────────────────┼────────────────────────────────┤
│ Runtime & Execution        │ RUN_COMMANDS                   │
│                            │ RUN_TESTS                      │
│                            │ LONG_RUNNING_EXECUTION         │
├────────────────────────────┼────────────────────────────────┤
│ Cognitive & Architectural  │ ARCHITECT_REVIEW               │
│                            │ STRUCTURED_DECISION            │
│                            │ ARTIFACT_GENERATION            │
│                            │ WEB_RESEARCH                   │
└────────────────────────────┴────────────────────────────────┘
```

---

## 2. Standard Capability Enums

| Capability Enum | Description | Contract Invariant |
|---|---|---|
| `READ_REPOSITORY` | Ability to inspect project files, directory trees, and configurations | Read-only; zero disk mutation |
| `WRITE_REPOSITORY` | Direct or policy-validated file modifications | Must strictly obey `allowed_scope` and `frozen_paths` |
| `PROPOSE_EDITS` | Structured file edit proposal without direct disk write | Returned as `ProposedFileEdit` blocks for verification |
| `RUN_COMMANDS` | Subprocess command execution | Bounded by timeout and security sandbox |
| `RUN_TESTS` | Automated test suite execution | Captures exit codes, stdout, stderr, and failure logs |
| `GIT_COMMIT` | Atomic git commit of verified changes | Preserves git author and message provenance |
| `GIT_PUSH` | Outbound push to remote tracking branch | Protected by Human Gate / configuration policy |
| `WEB_RESEARCH` | Outbound documentation or knowledge retrieval | Read-only; rate-limited |
| `ARCHITECT_REVIEW` | High-level engineering review of changes | Evaluates reports against design constraints |
| `STRUCTURED_DECISION` | Production of canonical `AgentDecision` envelope | Must output strictly validated JSON blocks |
| `ARTIFACT_GENERATION` | Markdown / architecture spec creation | Writes to approved `docs/` or `_daio/` artifacts |
| `LONG_RUNNING_EXECUTION` | Background daemon / task execution | Supports async streaming and health heartbeats |

---

## 3. Capability Negotiation & Matching

When DAIO Core resolves an adapter for a given `AgentRequest`:

```python
def is_adapter_compatible(adapter: AgentAdapter, request: AgentRequest) -> bool:
    """Verifies that adapter satisfies role and all requested capabilities."""
    identity = adapter.get_identity()
    if identity.logical_role != request.role:
        return False
    
    advertised = adapter.get_capabilities()
    for req_cap in request.requested_capabilities:
        if req_cap not in advertised:
            return False
            
    return True
```

If no registered adapter satisfies the required capabilities, DAIO Core fails closed with `CAPABILITY_MISMATCH` before executing any commands or mutating state.
