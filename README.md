# Dual-Agent Iteration Orchestrator (DAIO) + Live Taskboard 🤖⚡📊

> **Universal Autonomous Engineering & Auditing Bridge with Integrated Live Kanban Taskboard between Local AI Coding Agents (e.g. Antigravity / Claude Code) and Web LLM Architects (e.g. ChatGPT Projects / Claude Artifacts) via Chrome Remote Debugging Protocol (CDP).**

---

## 🎯 What is DAIO?

**DAIO (Dual-Agent Iteration Orchestrator)** completely eliminates the repetitive manual copy-pasting cycle between an **Execution / Engineer Agent** (writing code, running unit tests, generating backtests/audits) and an **Architect / Auditor Agent** (reviewing reports, enforcing statistical rigor, issuing next-phase directives).

### 🚀 Complete Visual Architecture with Taskboard
```text
                       DAIO ORCHESTRATOR
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   ┌──────────────────┐                  ┌──────────────────┐
   │ Antigravity /    │                  │  LIVE TASKBOARD  │
   │ Engineer Agent   │                  │  (Kanban / HTML) │
   │ Code, Test, Run  │                  │  Auto-Refreshing │
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
   │  Chrome CDP Sync │                           │
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
APPROVE  REVISE  HUMAN/STOP
   │        │        └──→ Yield to Human Operator
   ▼        │
NEXT PHASE  │
   │        │
   └────────┘
        ↓
  Re-invoke Engineer
        ↓
   Next Iteration ↻
```

---

## 📊 Live Visual Taskboard & Dialogue Feed

DAIO features a **rich visual Kanban Taskboard & Live Conversation Hub** (`daio_taskboard.py`):

1. **🚀 Animated Progress Bar & 10-Step Milestone Stepper**:
   - Dynamic glow progress fill showing real-time pipeline completion percentage (e.g. `100% Complete`).
   - Interactive milestone stepper tracking `P4 Freeze` $\rightarrow$ `P5 Canonical` $\rightarrow$ `P6 Runtime` $\rightarrow$ `OOS-1/2/3A/3B` $\rightarrow$ `CE-1/2` $\rightarrow$ `P7 Release`.
2. **⚖️ Interactive Human Governance Action Bar (Dual-Button Sync)**:
   - **One-Click Quick Approve (Top Bar) & Full Governance Gate (Inspector Card)**.
   - **Full Synchronized Lifecycle**:
     - `[ ✅ 快速批准 (Quick Approve P7) ]` $\rightarrow$ `[ ⏳ 批准執行中 (Executing P7 Release...) ]` $\rightarrow$ `[ ✨ 批准已生效 (v4.0.0 RELEASED) ]`.
     - Live floating toast notifications on action dispatch.
3. **🎭 Dual-Agent Live Dialogue Stage (Turn-Taking)**:
   - **Active Turn Indicator**: Visual pulse badge highlighting whose turn it is (`🛠️ Antigravity (Executing)` vs `🏛️ ChatGPT (Auditing)`).
   - **Speech Bubbles Feed**: Chronological dialogic exchange showing the Architect's directive and Engineer's response in real time.
4. **`taskboard.html`**: A sleek, dark-mode, auto-refreshing interactive Kanban dashboard.
5. **`TASKBOARD.md` & `taskboard.json`**: Markdown & structured JSON sync.

---

## ⚡ One-Click CLI (`./daio`)

DAIO comes with an all-in-one executable root CLI:

```bash
# 1. Start autonomous closed loop (reads _daio/daio_config.json)
./daio loop

# 2. Start autonomous dual-agent iteration loop (with interactive browser prompt)
./daio

# 3. Open live visual taskboard & dialogue stage in your browser
./daio board

# 4. View terminal status, active turn, and safety metrics
./daio status
```

---

## 🚀 Quick Start in 3 Steps

### Step 1: Launch Chrome with Remote Debugging
Launch Google Chrome with remote debugging port `9222` enabled:
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/Google/Chrome-CDP"

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.config/google-chrome-cdp"

# Windows
chrome.exe --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome-CDP"
```
Navigate to your desired **ChatGPT Project**, **Claude Artifact**, or custom **Web LLM** tab in that Chrome browser.

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Configure `_daio/daio_config.json` & Launch
Copy `daio_config.example.json` to `_daio/daio_config.json` in your repository root, configure the `architect_endpoint`, and run:
```bash
./daio loop
```

Open `taskboard.html` in your browser (or run `./daio board`) to monitor the live dual-agent loop in real-time!

---

## 🛡️ 4 Enterprise Safety Breakers

1. **`DAIO-001 (Test Integrity Gate)`**:
   - Before any report or deliverable is transmitted to the Architect, all unit tests must pass (`pytest` exit code = 0).
   - If tests fail, report transmission is immediately blocked to maintain strict codebase integrity.
2. **`DAIO-002 (Scope & Safety Guardrail)`**:
   - Canonical parameters and frozen specifications cannot be modified automatically.
   - If an Architect instruction suggests modifying frozen parameters or out-of-scope files, DAIO immediately halts and triggers `HUMAN_GATE_REQUIRED`.
3. **`DAIO-003 (Autonomous Recovery Cap & Safety Breaker)`**:
   - Maximum 3 consecutive errors or 10 iteration rounds before safely transitioning to `HUMAN_GATE_REQUIRED`.
4. **`DAIO-004 (Conversation Routing Contract & Tab Isolation)`**:
   - Enforces strict exact-conversation routing via `architect_endpoint`.
   - Never falls back to arbitrary ChatGPT tabs or login/redirect pages (Fail-closed).

---

## 📋 Standard Architect Decision Schema

The external Architect Agent is prompted to provide a machine-readable JSON control block at the end of every response:

```json
{
  "decision": "APPROVE",
  "current_phase": "OOS-3A",
  "next_phase": "OOS-3B",
  "action": "RUN",
  "human_approval_required": false,
  "instruction": "Summary of next objectives and guidelines"
}
```

### Supported Decision States:
| Decision | Meaning | Orchestrator Action |
| :--- | :--- | :--- |
| **`APPROVE`** | Milestone accepted & verified | Advances to `next_phase` and triggers execution engine |
| **`REVISE`** | Modifications / corrections requested | Re-executes current phase with bounded adjustments |
| **`REJECT`** | Critical failure identified | Halts loop for complete re-implementation |
| **`HUMAN_GATE_REQUIRED`** | Ambiguity, parameter freeze, or error budget exhausted | Halts and yields control to the human user |
| **`STOP`** | Research/engineering cycle complete | Loop terminates cleanly |

---

## 📂 Repository Structure

```text
.
├── README.md                      # Comprehensive documentation & architecture guide
├── SKILL.md                       # Antigravity / AI Agent Universal Skill Specification
├── requirements.txt               # Dependencies (websockets, pytest)
├── LICENSE                        # MIT Open Source License
├── daio                           # All-in-one executable CLI wrapper
├── daio_config.example.json       # Declarative configuration template
└── scripts/
    ├── daio_bridge.py             # Universal Chrome CDP Bridge
    ├── daio_taskboard.py          # Visual Taskboard State & HTML/Markdown Generator
    ├── daio_orchestrator.py       # Classic Persistent Iterative Loop Engine
    └── daio_closed_loop/          # DAIO v2.1 Modular Closed-Loop Architecture
        ├── models.py              # DAIOWorkItem & Domain Enums
        ├── store.py               # SqliteDAIOWorkStore (Durable persistence & leases)
        ├── router.py              # DAIORoleRouter (Gate authority transitions)
        ├── orchestrator.py        # DAIOClosedLoopOrchestrator (Safety breakers DAIO-001..004)
        ├── runner.py              # Standalone CLI entrypoint
        └── adapters/
            ├── executor.py        # SubprocessWorkspaceExecutor
            └── bridge.py          # ChromeCDPBridgeAdapter (Exact routing & stream detection)
```

---

## 📄 License
MIT License. Free for open source and commercial development orchestration.
