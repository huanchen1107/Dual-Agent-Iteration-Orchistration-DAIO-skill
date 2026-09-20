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

## 📊 Live Visual Taskboard Integration

DAIO now comes with a **built-in visual Kanban Taskboard engine** (`daio_taskboard.py`):

1. **`taskboard.html`**: A sleek, dark-mode, auto-refreshing interactive Kanban board with live status pulses, phase tags, agent assignment badges, and a chronological audit decision stream.
2. **`TASKBOARD.md`**: Markdown-formatted Kanban table automatically maintained in your repository for clean Git history.
3. **`taskboard.json`**: Structured state representation for programmatic integrations.

### Task Status Lifecycle:
- 📝 **`TODO`**: Backlog & upcoming planned milestones.
- ⚙️ **`IN_PROGRESS`**: Active engineering execution by Antigravity.
- 🧪 **`TESTING`**: Automated Test Integrity Gate execution.
- 🧐 **`REVIEW`**: Transmitted to Architect via Chrome CDP; awaiting review.
- ✅ **`DONE`**: Formally approved by Architect & verified by tests.
- 🛑 **`BLOCKED`**: Safety Breaker triggered or Human Review requested.

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

### Step 3: Launch DAIO Orchestrator
```bash
# Option A: Run directly with CLI arguments
python3 scripts/daio_orchestrator.py \
  --url "https://chatgpt.com/g/g-p-your-project-id" \
  --phase "PHASE_1_SCAFFOLDING" \
  --cmd "python3 src/main.py" \
  --test "pytest tests/" \
  --max-iterations 20

# Option B: Run with declarative configuration file
python3 scripts/daio_orchestrator.py --config daio_config.example.json
```

Open `taskboard.html` in your browser to monitor the live dual-agent loop in real-time!

---

## 🛡️ 4 Enterprise Safety Breakers

1. **`TEST_INTEGRITY_GATE`**:
   - Before any report is submitted to the Architect, all unit tests must pass (`pytest` exit code = 0).
   - If tests fail, report transmission is immediately blocked to maintain strict codebase integrity.
2. **`FROZEN_PARAMETER_LOCK`**:
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
