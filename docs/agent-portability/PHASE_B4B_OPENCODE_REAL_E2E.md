# DAIO Portability: OpenCode CLI Real E2E Acceptance Architecture (Phase B4B)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B4B`  
**Status**: `APPROVED`  

---

## 1. Executive Summary & Verification Scope

Under `PORTABILITY-PHASE-B4B`, DAIO integrated **OpenCode CLI** as the fourth real engineering provider while preserving the existing provider-neutral architecture:

* **Control Baseline 1**: Antigravity CLI (`agy`) — `1.2.12`
* **Control Baseline 2**: Gemini CLI (`gemini`) — `0.8.2`
* **Control Baseline 3**: Codex CLI (`codex`) — `codex-cli 0.150.1`
* **New Provider Under Acceptance**: OpenCode CLI (`opencode`) — `1.17.7`

### Core Invariants Enforced:
1. **`DAIO-PORTABILITY-INVARIANT-001`**: Adding OpenCode CLI required **ZERO modifications to DAIO Core** (orchestrator, FSM, supervisor, store, leasing, watchdog, recovery, Human Gate, remote ingress).
2. **`DAIO-AUTH-INVARIANT-001`**: DAIO does not own, copy, or persist API keys. OpenCode CLI operates via `AuthMode.PROVIDER_DEPENDENT` using local provider credentials/sessions (`~/.local/share/opencode/auth.json`).
3. **`DAIO-EXECUTION-INVARIANT-001`**: OpenCode CLI output is treated strictly as a proposal (`ProposedFileEdit`). DAIO Two-Tier policy engine maintained sole authority over disk mutation, scope checking, test execution, git commits, and FSM transitions.
4. **`DAIO-HUMAN-INVARIANT-001`**: Preserved strict authority of DAIO Human Gate (Passkey / WebAuthn / Face ID).

---

## 2. OpenCode CLI Inspection & Delegation Architecture

### 2.1 Host Binary Inspection
- **Path**: `/Users/huanchen/.opencode/bin/opencode`
- **Version**: `1.17.7`
- **Non-Interactive Execution**: `opencode run "<prompt>"`
- **Structured Output**: `--format json` (streams structured JSON events)
- **Working Directory**: `--dir <project_root>`
- **Unattended Mode**: `--dangerously-skip-permissions`
- **Model / Provider Routing**: `-m <model_id>` or `--provider <provider_id>`

### 2.2 Provider Delegation vs DAIO Core Separation
OpenCode routes to multiple underlying providers (OpenRouter, OpenCode Go, OpenAI, Google, etc.). In accordance with Section D:
```text
DAIO provider:
    opencode_cli

OpenCode underlying provider:
    <detected provider e.g. openrouter / opencode-go>

OpenCode model:
    <detected/configured model e.g. opencode/glm-4-9b-chat>
```
Underlying provider and model information is captured as provenance/evidence metadata and never encoded into DAIO Core.

### 2.3 Real Invocation Shape (Redacted)
```bash
opencode run \
  "<prompt>" \
  --format json \
  --dir <project_root> \
  --dangerously-skip-permissions
```

---

## 3. Four-Provider Comparison Matrix

| # | Dimension | Antigravity CLI | Gemini CLI | Codex CLI | OpenCode CLI | Status |
| :- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Executable / Version** | `/Users/huanchen/.local/bin/agy`<br>`1.2.12` | `/opt/homebrew/bin/gemini`<br>`0.8.2` | `/opt/homebrew/bin/codex`<br>`codex-cli 0.150.1` | `/Users/huanchen/.opencode/bin/opencode`<br>`1.17.7` | **Verified Real Host Binaries** |
| **2** | **Auth Mode** | `LOGIN_SESSION` | `LOGIN_SESSION` | `LOGIN_SESSION` | `PROVIDER_DEPENDENT` | **Zero API Key in DAIO Core** |
| **3** | **Non-Interactive Mode** | `--print` flag | `-p` / positional prompt | `codex exec` subcommand | `opencode run` subcommand | **Unattended Execution** |
| **4** | **Structured Output** | `--output-format json` | `-o json` | `--json` (JSONL stream) | `--format json` (JSON stream) | **Standardized Proposal Extraction** |
| **5** | **Proposal Parsing** | JSON envelope $\rightarrow$ markdown | JSON object $\rightarrow$ markdown | JSONL message $\rightarrow$ markdown | JSON event stream $\rightarrow$ markdown | **Normalized to `ProposedFileEdit`** |
| **6** | **Timeout Behavior** | Asyncio subprocess timeout | Asyncio subprocess timeout | Asyncio subprocess timeout | Asyncio subprocess timeout | **Graceful Fail-Closed** |
| **7** | **Failure Behavior** | Non-zero exit mapped to `success=False` | Non-zero exit mapped to `success=False` | Non-zero exit mapped to `success=False` | Non-zero exit mapped to `success=False` | **Normalized Error Proposal** |
| **8** | **`allowed_scope` Enforcement** | Pre-write & post-diff policy guard | Pre-write & post-diff policy guard | Pre-write & post-diff policy guard | Pre-write & post-diff policy guard | **Identical Core Enforcement** |
| **9** | **`frozen_paths` Enforcement** | Unauthorized diff blocked | Unauthorized diff blocked | Unauthorized diff blocked | Unauthorized diff blocked | **Identical Core Enforcement** |
| **10** | **Test Execution** | Baseline-aware pytest by DAIO executor | Baseline-aware pytest by DAIO executor | Baseline-aware pytest by DAIO executor | Baseline-aware pytest by DAIO executor | **Identical Test Integrity Gate** |
| **11** | **Evidence Format** | `_daio/evidence/` JSON payload | `_daio/evidence/` JSON payload | `_daio/evidence/` JSON payload | `_daio/evidence/` JSON payload | **Identical Evidence Schema** |
| **12** | **Git / Provenance** | Atomic commit & SHA tracking | Atomic commit & SHA tracking | Atomic commit & SHA tracking | Atomic commit & SHA tracking | **Identical Deliverable Flow** |
| **13** | **Architect Handoff** | Role handoff to `LEAD_ARCHITECT_REVIEW` | Role handoff to `LEAD_ARCHITECT_REVIEW` | Role handoff to `LEAD_ARCHITECT_REVIEW` | Role handoff to `LEAD_ARCHITECT_REVIEW` | **Identical Review Packaging** |
| **14** | **FSM Transitions** | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | **100% Identical FSM Evolution** |
| **15** | **HUMAN_GATE Preservation** | Invariant & Passkey/WebAuthn intact | Invariant & Passkey/WebAuthn intact | Invariant & Passkey/WebAuthn intact | Invariant & Passkey/WebAuthn intact | **Zero Security Dilution** |
| **16** | **Unattended Compatibility** | Full `--sandbox` + permissions bypass | Full `-s` + `--approval-mode yolo` | Full `--sandbox read-only` | Full `--dangerously-skip-permissions` | **Autonomous Operation** |
