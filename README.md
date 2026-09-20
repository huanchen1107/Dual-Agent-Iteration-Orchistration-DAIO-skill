# Dual-Agent Iteration Orchestrator (DAIO) 🤖⚡🤖

> **Universal Autonomous Engineering & Auditing Bridge between Local AI Coding Agents (e.g. Antigravity / Claude Code) and Web LLM Architects (e.g. ChatGPT Projects / Claude Artifacts) via Chrome Remote Debugging Protocol (CDP).**

---

## 🎯 What is DAIO?

**DAIO (Dual-Agent Iteration Orchestrator)** completely eliminates the repetitive manual copy-pasting cycle between an **Execution / Engineer Agent** (writing code, running unit tests, generating backtests/audits) and an **Architect / Auditor Agent** (reviewing reports, enforcing statistical rigor, issuing next-phase directives).

```text
                  DAIO ORCHESTRATOR
                          │
                          ▼
            ┌───────────────────────────┐
            │  Antigravity / Engineer   │
            │  Executes Task & Analysis │
            └─────────────┬─────────────┘
                          │
                          ▼
               Test Gate (Pytest 100%)
               Git Commit & Remote Push
                          │
                          ▼
            ┌───────────────────────────┐
            │  External Web LLM Agent   │
            │  (ChatGPT Project / Tab)  │
            │  Chrome CDP Transmit      │
            └─────────────┬─────────────┘
                          │
                          ▼
                  WAIT_FOR_STREAM
                 (Auto-detect completion)
                          │
                          ▼
                Parse Decision Block
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
        APPROVE         REVISE       HUMAN_REVIEW / STOP
           │              │              │
           ▼              │              └──→ Pause & Yield to User
       NEXT PHASE         │
           │              │
           └──────────────┘
                  ↓
         Re-invoke Engineer
                  ↓
             Next Iteration ↻
```

---

## 🚀 Quick Start

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
Navigate to your desired **ChatGPT Project** or **Web LLM Conversation** in that Chrome browser.

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Run the Orchestrator
```bash
python3 scripts/daio_orchestrator.py \
  --url "https://chatgpt.com/g/g-p-6a7b02e338b8819182fa5b270ed91354" \
  --phase "PHASE_1" \
  --cmd "python3 research/run_task.py" \
  --test "pytest tests/" \
  --max-iterations 15
```

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
   - Default safety limit (e.g., 15 rounds) to prevent runaway infinite loops.

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
├── README.md                      # Documentation & architecture
├── SKILL.md                       # Antigravity / AI Agent Skill Specification
├── requirements.txt               # Dependencies (websockets)
└── scripts/
    ├── daio_bridge.py             # Universal Chrome CDP Bridge (URL discovery, stream detection)
    └── daio_orchestrator.py       # Persistent Iterative Loop CLI Engine
```

---

## 📄 License
MIT License. Free for open source and commercial development orchestration.
