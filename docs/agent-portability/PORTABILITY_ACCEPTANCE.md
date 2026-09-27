# DAIO Agent Portability: Phase A Acceptance & Inventory

## 1. Existing Adapter Inventory

Prior to Phase A standardization, existing adapters in the codebase are classified as follows:

| Adapter Class | File Location | Primary Role | Status Classification | Notes |
|---|---|---|---|---|
| `AntigravityCLIAdapter` | `adapters/antigravity_cli_agent.py` | `ENGINEERING_EXECUTION` | **CONFORMANT** | Primary CLI adapter; supports unattended mode, sandboxing, and JSON proposals |
| `GeminiEngineeringAgentAdapter` | `adapters/gemini_agent.py` | `ENGINEERING_EXECUTION` | **CONFORMANT** | Reference direct API backend; outputs structured `ProposedFileEdit` blocks |
| `ChromeCDPBridgeAdapter` | `adapters/bridge.py` | `LEAD_ARCHITECT` | **CONFORMANT** | Live CDP WebSocket client; conversation-aware routing and JSON decision parser |
| `GeminiArchitectBridgeAdapter` | `adapters/bridge.py` | `LEAD_ARCHITECT` | **CONFORMANT** | Direct Gemini API architect adapter for autonomous headless reviews |
| `MockEngineeringAgentAdapter` | `adapters/agent_contract.py` | `ENGINEERING_EXECUTION` | **CONFORMANT** | Deterministic mock adapter for unit tests |
| `MockArchitectBridgeAdapter` | `adapters/bridge.py` | `LEAD_ARCHITECT` | **CONFORMANT** | Deterministic mock architect bridge for unit tests |
| `SubprocessWorkspaceExecutor` | `adapters/executor.py` | Executor Bridge | **CONFORMANT** | Generic workspace executor delegating to `EngineeringAgentAdapter` |

---

## 2. Phase A Contract Verification Suite

Phase A validates the following 10 canonical contract invariants via automated tests:

1. **Dual-Adapter Request Acceptance:** The same `AgentRequest` is accepted by distinct mock adapters without structural modification.
2. **Schema Normalization:** Different adapters normalize varied raw outputs into the standard `AgentResponse` contract.
3. **Core Mutation Protection:** Raw provider output cannot directly mutate DAIO FSM state without passing validation.
4. **Capability Pre-Flight Checking:** A request requiring unavailable capabilities fails with `CAPABILITY_MISMATCH` before execution.
5. **Dynamic Registry Extensibility:** A newly defined provider adapter can be registered and resolved without modifying DAIO Core files.
6. **Failure Normalization:** Provider timeout or connection drop normalizes to canonical `AgentFailure` with appropriate `recovery_classification`.
7. **Architect Decision Equivalence:** An `APPROVE` decision produced by different architect backends drives identical DAIO state transitions.
8. **Engineering Evidence Equivalence:** Engineering proposals from different backends produce identical policy-validated workspace diffs and audit evidence.
9. **Provider-Neutrality Guard:** Automated AST/grep guard ensures zero hardcoded vendor strings in Core orchestration modules.
10. **Zero Regression:** All existing RPC-1, RPC-2, and RPC-3 tests (201+ tests) remain 100% green.
