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

# Dual-Agent Iteration Orchestrator (DAIO)

## 🎯 Overview: The Persistent Engineer-Architect Autonomous Loop

DAIO eliminates manual copy-pasting between Antigravity and external Web LLMs (ChatGPT Projects, Claude Artifacts, Custom Web LLM Auditors). It creates an automated, test-gated, safety-bounded persistent loop:

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

## 🔔 Automatic Skill Activation Protocol & UI Launch Inquirer

**CRITICAL BEHAVIORAL RULE**: Whenever the user activates or invokes this skill (via `/daio`, `daio`, `啟動 daio`, or asks for dual-agent orchestration), the AI assistant MUST strictly follow this 3-step activation protocol in its very first response:

1. **Proactively Inquire & Offer UI Launch**:
   - Explicitly ask the user: *"是否需要為您在瀏覽器中自動開啟即時視覺對話看板 (Live Taskboard)？"*
   - Resolve the active project's taskboard dynamically; never hard-code a project-specific local path.
2. **Report Active Turn & Dialogue State**:
   - Clearly state whose turn it is right now (`🟢 當前行動回合: 🛠️ Antigravity (執行工程師)` 或 `🟡 🏛️ ChatGPT (審計架構師)`).
   - Show the latest speech bubble exchange between both agents.
3. **Report Milestone Pipeline Progress**:
   - Report the overall completion percentage (e.g. `8 / 10 里程碑完成 (80%)`) and the active milestone task.

---

## ♻️ Robust Cross-Session Recovery

DAIO MUST treat the Git repository as durable coordination state and browser/chat context as a replaceable cache.

On activation, continuation, browser-tab replacement, ChatGPT Project thread switch, or Agent context loss:

1. Resolve the actual project Git root and current HEAD.
2. Run `./daio recover` (or the equivalent recovery preflight).
3. Read `.daio/recovery_state.json` only as a non-authoritative checkpoint.
4. If the checkpoint is missing, reconstruct from Git/project artifacts and continue.
5. If checkpoint HEAD differs from actual HEAD, classify `STALE`, inspect intervening commits, rehydrate context, and continue automatically.
6. Never require the human to paste an old conversation when repository evidence is sufficient.
7. Only stop for a real semantic conflict, destructive/human approval gate, or irreconcilable ownership conflict.
8. ChatGPT conversation URLs/IDs are optional navigation hints; they are never the source of truth and DAIO must not assume GitHub can enumerate private ChatGPT conversations.

Recovery health states: `SYNCED`, `STALE`, `CHECKPOINT_MISSING`, `DEGRADED`, `BLOCKED`.

## 🚀 Quick Start & Usage

### 1. One-Click CLI (`./daio`)
In the workspace root, use the unified executable CLI:
```bash
./daio board    # Open live visual taskboard in browser
./daio status   # Check current active turn, tasks, and audit log
./daio          # Start autonomous dual-agent iteration loop (with interactive UI prompt)
```

### 2. Launch Chrome in Debugging Mode
Ensure Google Chrome is open with remote debugging enabled on port `9222`:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

### 2. Run Universal DAIO CLI
Pass the target ChatGPT / Web LLM URL (or part of the URL) along with the execution command and test command:

```bash
python3 /Users/huanchen/.gemini/config/skills/daio/scripts/daio_orchestrator.py \
  --url "https://chatgpt.com/g/g-p-6a7b02e338b8819182fa5b270ed91354" \
  --phase "OOS-3A" \
  --cmd "python3 research/run_phase.py" \
  --test "pytest tests/" \
  --max-iterations 15
```

---

## 🛡️ Built-in Safety Breakers

1. **`TEST_INTEGRITY_GATE`**:
   - Before any report is sent to the Architect, all unit tests must pass (`pytest` exit code = 0).
   - If tests fail, report transmission is blocked immediately.
2. **`FROZEN_PARAMETER_LOCK`**:
   - Canonical strategy parameters (e.g. S1–S7 frozen contracts) are strictly locked.
   - If an Architect instruction suggests tweaking frozen parameters, DAIO immediately halts and triggers `HUMAN_REVIEW`.
3. **`CONSECUTIVE_ERRORS_CAP`**:
   - Max 3 consecutive errors (execution errors, communication timeouts, unparseable decisions).
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
- **`APPROVE`**: Milestone accepted. Orchestrator advances to `next_phase`.
- **`REVISE`**: Modification requested. Re-runs current phase with new adjustments.
- **`REJECT`**: Failure identified. Requires reimplementation.
- **`HUMAN_REVIEW`**: Ambiguity, freeze decision, or high-risk decision. Halts and yields control to the human user.
- **`STOP`**: Research/engineering cycle is complete. Loop terminates cleanly.
