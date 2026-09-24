---
name: daio
description: >-
  Universal Dual-Agent Iteration Orchestrator (DAIO). Bridges Antigravity (Execution/Engineer Agent)
  and ChatGPT Project / Web LLM (Architect/Auditor Agent) via Chrome Remote Debugging (CDP).
  Connects to any browser URL (e.g. ChatGPT Project, Claude, custom Web UI), transmits reports,
  detects stream completion, parses structured JSON decisions (APPROVE, REVISE, REJECT, HUMAN_REVIEW, STOP),
  enforces test integrity gates, and executes persistent iterative development loops autonomously.
  Use when the user asks for dual agent orchestration, DAIO, ChatGPT iteration, iterative browser sync, or /daio.
---

# Dual-Agent Iteration Orchestrator (DAIO) v2.1

## 🎯 Overview: The Persistent Engineer-Architect Autonomous Closed-Loop

DAIO eliminates manual copy-pasting between Antigravity (Local Execution/Engineer Agent) and external Web LLMs (ChatGPT Projects, Claude Artifacts, Custom Web LLM Auditors). It creates an automated, test-gated, exact-conversation-routed, durable SQLite-backed closed loop:

```text
                  DAIO CLOSED-LOOP ORCHESTRATOR
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   ┌──────────────────┐                  ┌──────────────────┐
   │ Antigravity /    │                  │  SqliteDAIOWork  │
   │ WorkspaceEngine  │                  │  Durable State   │
   │ Code, Test, Run  │                  │  Lease & Lock    │
   └────────┬─────────┘                  └────────┬─────────┘
            │                                     │
            ▼                                     │
     Test Integrity Gate                          │
     Git Commit & Remote Push                     │
            │                                     │
            ▼                                     │
   ┌──────────────────┐                           │
   │  External LLM    │                           │
   │  Architect Agent │                           │
   │  (ChatGPT / Web) │                           │
   │  Exact Tab Route │                           │
   └────────┬─────────┘                           │
            │                                     │
            ▼                                     │
     WAIT_FOR_STREAM                              │
    (Auto-completion)                             │
            │                                     │
            ▼                                     │
    Parse Decision Block ─────────────────────────┘
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
APPROVE  REVISE  HUMAN_GATE / STOP
   │        │        └──→ Yield to Human Operator
   ▼        │
NEXT PHASE  │
   │        │
   └────────┘
        ↓
  Re-invoke Engineer
        ↓
   Next Iteration ↻ (human_relay_count == 0)
```

---

## 🔔 Automatic Skill Activation Protocol & UI Launch Inquirer

**CRITICAL BEHAVIORAL RULE**: Whenever the user activates or invokes this skill (via `/daio`, `daio`, `啟動 daio`, or asks for dual-agent orchestration), the AI assistant MUST strictly follow this 3-step activation protocol in its very first response:

1. **Proactively Inquire & Offer UI Launch**:
   - Explicitly ask the user: *"是否需要為您在瀏覽器中自動開啟即時視覺對話看板 (Live Taskboard)？"*
   - Provide clickable local file link: [taskboard.html](file:///Users/huanchen/Desktop/2026%20Projects/2026.8.26AwinFinTechSMCHybridSystemFolder/_AwinFinTechHybridSystem_/taskboard.html).
2. **Report Active Turn & Dialogue State**:
   - Clearly state whose turn it is right now (`🟢 當前行動回合: 🛠️ Antigravity (執行工程師)` 或 `🟡 🏛️ ChatGPT (審計架構師)`).
   - Show the latest speech bubble exchange between both agents.
3. **Report Milestone Pipeline Progress**:
   - Report the overall completion percentage (e.g. `8 / 10 里程碑完成 (80%)`) and the active milestone task.

---

## 🚀 Quick Start & Usage

### 1. One-Click CLI (`./daio`)
In the workspace root, use the unified executable CLI:
```bash
./daio loop     # Start autonomous closed loop (reads _daio/daio_config.json)
./daio board    # Open live visual taskboard in browser
./daio status   # Check current active turn, tasks, and audit log
./daio          # Start autonomous dual-agent iteration loop (with interactive UI prompt)
```

### 2. Launch Chrome in Debugging Mode
Ensure Google Chrome is open with remote debugging enabled on port `9222`:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/Google/Chrome-CDP"
```

### 3. Declarative Exact-Conversation Configuration (`_daio/daio_config.json`)
```json
{
  "project_name": "MyProject",
  "architect_endpoint": {
    "provider": "CHATGPT_WEB",
    "project_id": "g-p-6a7b02e338b8819182fa5b270ed91354",
    "conversation_id": "6ab4c10a-38a8-83e8-a71d-64199b27393f",
    "canonical_url": "https://chatgpt.com/g/g-p-6a7b02e338b8819182fa5b270ed91354/c/6ab4c10a-38a8-83e8-a71d-64199b27393f",
    "routing_policy": "EXACT_CONVERSATION"
  },
  "cdp_url": "http://127.0.0.1:9222",
  "workspace_path": ".",
  "test_command": "pytest tests/ -q",
  "max_iterations": 10
}
```

---

## 🛡️ Built-in Safety Breakers (DAIO-001 .. DAIO-004)

1. **`DAIO-001 (Test Integrity Gate)`**:
   - Before any report or deliverable is transmitted to the Architect, all test suites must pass (`pytest` exit code = 0).
   - If tests fail, report transmission is blocked immediately.
2. **`DAIO-002 (Scope & Safety Guardrail)`**:
   - Enforces workspace scope protection and frozen parameter lock.
   - Out-of-scope file modifications or frozen policy changes trigger `HUMAN_GATE_REQUIRED`.
3. **`DAIO-003 (Autonomous Recovery Cap & Safety Breaker)`**:
   - Max 3 consecutive errors or 10 iteration rounds before safely transitioning to `HUMAN_GATE_REQUIRED`.
4. **`DAIO-004 (Conversation Routing Contract & Tab Isolation)`**:
   - Enforces strict exact-conversation routing via `architect_endpoint`.
   - Never falls back to arbitrary ChatGPT tabs or login/redirect pages (Fail-closed).

---

## 📋 Standard Architect Decision Schema

The external Architect Agent is prompted to provide a machine-readable JSON control block at the end of every response:

```json
{
  "decision": "APPROVE",
  "current_phase": "PHASE-1",
  "next_phase": "PHASE-2",
  "action": "PROCEED",
  "human_approval_required": false,
  "instruction": "Summary of next objectives and guidelines"
}
```

### Supported Decision States:
- **`APPROVE`**: Milestone/proposal accepted. Orchestrator advances to next milestone or completes work.
- **`REVISE`**: Modification requested. Re-invokes workspace executor with bounded adjustments.
- **`REJECT`**: Failure identified. Requires fundamental redesign.
- **`HUMAN_GATE_REQUIRED` / `HUMAN_REVIEW`**: Ambiguity, freeze decision, or high-risk decision. Halts and yields control to the human user.
- **`STOP`**: Work completed cleanly.
