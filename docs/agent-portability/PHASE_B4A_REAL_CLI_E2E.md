# DAIO Portability: Real Login-Session CLI E2E Architecture (Phase B4A)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B4A`  
**Status**: `APPROVED`  

---

## 1. Executive Summary & Verification Scope

Under `PORTABILITY-PHASE-B4A`, DAIO proved end-to-end execution of real, provider-swappable engineering work using the user's authenticated local CLI sessions:

* **Control Baseline**: Antigravity CLI (`agy`) — `1.2.12`
* **Real CLI Provider 1**: Gemini CLI (`gemini`) — `0.8.2`
* **Real CLI Provider 2**: Codex CLI (`codex`) — `codex-cli 0.150.1`

### Core Invariants Enforced:
1. **`DAIO-PORTABILITY-INVARIANT-001`**: Swapping between Antigravity, Gemini, and Codex CLI required **ZERO modifications to DAIO Core**.
2. **`DAIO-AUTH-INVARIANT-001`**: Zero API keys required or processed. Execution relied entirely on host login sessions (`~/.gemini`, `~/.codex`, `~/.antigravity`).
3. **`DAIO-EXECUTION-INVARIANT-001`**: CLI outputs were treated as non-authoritative proposals (`ProposedFileEdit`). DAIO Two-Tier policy engine maintained sole authority over disk mutation, scope checking, test execution, and git commits.
4. **`DAIO-HUMAN-INVARIANT-001`**: Preserved strict authority of DAIO Human Gate (Passkey / WebAuthn / Face ID).

---

## 2. Real CLI Invocation Contracts (Redacted)

### 2.1 Antigravity CLI Adapter (`AntigravityCLIAdapter`)
```bash
agy \
  --sandbox \
  --dangerously-skip-permissions \
  --print "<prompt>" \
  --output-format json \
  --disable-slash-commands \
  --add-dir <project_root>
```

### 2.2 Gemini CLI Adapter (`GeminiCLIAdapter`)
```bash
gemini \
  -p "<prompt>" \
  -o json \
  --approval-mode yolo \
  -s \
  -m gemini-2.5-pro
```

### 2.3 Codex CLI Adapter (`CodexCLIAdapter`)
```bash
codex exec \
  "<prompt>" \
  --json \
  --sandbox read-only \
  --cd <project_root> \
  -m o3
```

---

## 3. 16-Dimensional Comparison Matrix

| # | Dimension | Antigravity CLI (Control) | Gemini CLI | Codex CLI | Status |
| :- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Executable / Version** | `/Users/huanchen/.local/bin/agy`<br>`1.2.12` | `/opt/homebrew/bin/gemini`<br>`0.8.2` | `/opt/homebrew/bin/codex`<br>`codex-cli 0.150.1` | **Verified Real Host Binaries** |
| **2** | **Login-Session Auth** | `LOGIN_SESSION` (`~/.gemini`) | `LOGIN_SESSION` (`~/.gemini`) | `LOGIN_SESSION` (`~/.codex`) | **Zero API Key Required** |
| **3** | **Non-Interactive Mode** | `--print` flag | `-p` / positional prompt | `codex exec` subcommand | **Unattended Execution** |
| **4** | **Structured Output** | `--output-format json` | `-o json` | `--json` (JSONL stream) | **Standardized Proposal Extraction** |
| **5** | **Proposal Parsing** | JSON outer envelope $\rightarrow$ inner markdown | JSON response object $\rightarrow$ inner markdown | JSONL message event $\rightarrow$ inner markdown | **Normalized to `ProposedFileEdit`** |
| **6** | **Timeout Behavior** | `asyncio.wait_for` subprocess timeout | `asyncio.wait_for` subprocess timeout | `asyncio.wait_for` subprocess timeout | **Graceful Fail-Closed** |
| **7** | **Failure Behavior** | Non-zero exit mapped to `success=False` | Non-zero exit mapped to `success=False` | Non-zero exit mapped to `success=False` | **Normalized Error Proposal** |
| **8** | **`allowed_scope` Enforcement** | Pre-write & post-diff policy guard (DAIO-002) | Pre-write & post-diff policy guard (DAIO-002) | Pre-write & post-diff policy guard (DAIO-002) | **Identical Core Enforcement** |
| **9** | **`frozen_paths` Enforcement** | Unauthorized diff blocked (DAIO-002) | Unauthorized diff blocked (DAIO-002) | Unauthorized diff blocked (DAIO-002) | **Identical Core Enforcement** |
| **10** | **Test Execution** | Baseline-aware pytest by DAIO executor | Baseline-aware pytest by DAIO executor | Baseline-aware pytest by DAIO executor | **Identical Test Integrity Gate** |
| **11** | **Evidence Format** | `_daio/evidence/` JSON payload | `_daio/evidence/` JSON payload | `_daio/evidence/` JSON payload | **Identical Evidence Schema** |
| **12** | **Git / Provenance** | Atomic commit & SHA tracking | Atomic commit & SHA tracking | Atomic commit & SHA tracking | **Identical Deliverable Flow** |
| **13** | **Architect Handoff** | Role handoff to `LEAD_ARCHITECT_REVIEW` | Role handoff to `LEAD_ARCHITECT_REVIEW` | Role handoff to `LEAD_ARCHITECT_REVIEW` | **Identical Review Packaging** |
| **14** | **FSM Transitions** | `S3 / IMPLEMENTATION_GATE` $\rightarrow$ `COMPLETED` | `S3 / IMPLEMENTATION_GATE` $\rightarrow$ `COMPLETED` | `S3 / IMPLEMENTATION_GATE` $\rightarrow$ `COMPLETED` | **100% Identical FSM Evolution** |
| **15** | **HUMAN_GATE Preservation** | Invariant & Passkey/WebAuthn intact | Invariant & Passkey/WebAuthn intact | Invariant & Passkey/WebAuthn intact | **Zero Security Dilution** |
| **16** | **Unattended Compatibility** | Full `--sandbox` + permissions bypass | Full `-s` + `--approval-mode yolo` | Full `--sandbox read-only` | **Autonomous Operation** |
