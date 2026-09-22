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
   - Interactive milestone stepper driven by the active project's phases and milestones.
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
# 1. Start autonomous dual-agent iteration loop (with interactive browser prompt)
./daio

# 2. Open live visual taskboard & dialogue stage in your browser
./daio board

# 3. View terminal status, active turn, and safety metrics
./daio status
```

---

## 🚀 Quick Start in 3 Steps

### Step 1: Launch Chrome with Remote Debugging
Launch Google Chrome with remote debugging port `9222` enabled:
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222

# Windows
chrome.exe --remote-debugging-port=9222
```
Navigate to your desired **ChatGPT Project**, **Claude Artifact**, or custom **Web LLM** tab in that Chrome browser.

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Launch DAIO
```bash
# Option A: One-click CLI launch
./daio

# Option B: Run with custom CLI arguments
python3 scripts/daio_orchestrator.py \
  --url "https://chatgpt.com/g/g-p-your-project-id" \
  --phase "PHASE_1_SCAFFOLDING" \
  --cmd "python3 src/main.py" \
  --test "pytest tests/" \
  --max-iterations 20

# Option C: Run with declarative configuration file
python3 scripts/daio_orchestrator.py --config daio_config.example.json
```

Open `taskboard.html` in your browser (or run `./daio board`) to monitor the live dual-agent loop in real-time!

---

## 🛡️ 4 Enterprise Safety Breakers

1. **`TEST_INTEGRITY_GATE`**:
   - Before any report is submitted to the Architect, all unit tests must pass (`pytest` exit code = 0).
   - If tests fail, report transmission is immediately blocked to maintain strict codebase integrity.
2. **Project parameter-freeze policy (project-owned, not enforced by DAIO Core)**:
   - Canonical parameters and frozen specifications cannot be modified automatically.
   - If an Architect instruction suggests modifying frozen parameters, DAIO immediately halts and triggers `HUMAN_REVIEW`.
3. **`CONSECUTIVE_ERRORS_CAP`**:
   - Maximum 3 consecutive errors (execution errors, communication timeouts, unparseable decisions).
   - Exceeding the threshold safely halts the loop and alerts the human operator.
4. **`MAX_ITERATIONS`**:
   - Default safety limit (e.g., 20 rounds) to prevent runaway infinite loops.

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
| **`REVISE`** | Modifications / corrections requested | Re-executes current phase with new adjustments |
| **`REJECT`** | Critical failure identified | Halts loop for complete re-implementation |
| **`HUMAN_REVIEW`** | Ambiguity, parameter freeze, or high-risk decision | Halts and yields control to the human user |
| **`STOP`** | Research/engineering cycle complete | Loop terminates cleanly |

---

## 📂 Repository Structure

```text
.
├── README.md                      # Comprehensive documentation & architecture guide
├── SKILL.md                       # Antigravity / AI Agent Universal Skill Specification
├── requirements.txt               # Dependencies (websockets, pytest)
├── LICENSE                        # MIT Open Source License
├── daio_config.example.json       # Declarative configuration template
└── scripts/
    ├── daio_bridge.py             # Universal Chrome CDP Bridge (URL discovery, stream detection)
    ├── daio_taskboard.py          # Visual Taskboard State & HTML/Markdown Generator
    └── daio_orchestrator.py       # Persistent Iterative Loop CLI Engine
```

---

## 📄 License
MIT License. Free for open source and commercial development orchestration.
