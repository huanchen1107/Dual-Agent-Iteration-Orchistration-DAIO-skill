# DAIO Phase C1 Architecture: Persistent Closed-Loop Hardening

## 1. Overview & Operating Model

Phase C1 hardens the canonical closed loop between **ChatGPT (Architect)**, **DAIO Core Orchestrator**, and the **Agent Provider Federation (Engineers)**:

```text
                     Project Owner
                           │
                           ▼
                 ChatGPT / Lead Architect
                 (High-Level Reasoning / Directives)
                           │
                           ▼
                   DAIO Orchestrator
                 (Canonical Supervisor & FSM)
                           │
                           ▼
                 Agent Provider Router
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
        Antigravity     Gemini          Codex
           CLI            CLI             CLI
           │               │               │
           └───────────────┼───────────────┘
                           │  (OpenCode / Claude Code)
                           ▼
               DAIO Evidence / State / Audit
                           │
                           ▼
              ChatGPT / Lead Architect Review
                           │
                           ▼
               Next Autonomous Iteration
```

---

## 2. Core Hardening Components

### A. Robust ChatGPT Project / Conversation Routing
- `ChatGPTConversationRegistry`: Stores validated ChatGPT project/conversation descriptors.
- `ProjectAwareArchitectRouter`:
  - Validates exact pinned conversation when active.
  - If pinned thread is missing/stale, safely discovers active project tabs via Chrome CDP WebSocket.
  - Fails closed if project identity cannot be established.
  - Generates comprehensive routing audit records.

### B. Zero-Touch Architect ↔ Engineer Handoff
- Engineer completion triggers automatic compact evidence compilation.
- Dispatched via Chrome CDP bridge without manual copy/paste.
- Machine-readable decision block returned, validated, and applied automatically to the SQLite WorkStore.

### C. Compact Canonical Evidence Packet (`DAIO_ARCHITECT_EVIDENCE_PACKET`)
- High-density markdown format (< 2000 chars) ensuring optimal token efficiency for ChatGPT.
- Summarizes objectives, implementation, file changes, diffs, test gate results, security invariants, active provider, and git state.

### D. Canonical Architect Decision Contract
- Machine-readable decision format (`APPROVE`, `REVISE`, `STOP`, `HUMAN_GATE`).
- Strict validation protects against stale responses, mismatched work IDs, or out-of-order recovery epochs.

### E. Multi-Provider In-Flight Failover
- Cascade: `Antigravity CLI` → `Gemini CLI` → `Codex CLI` → `OpenCode CLI` (and future `Claude Code`).
- Bounded failover on process crashes, timeouts, rate limits, and provider-level errors.
- Preserves exactly-once mutation semantics without masking code defects or test failures.
