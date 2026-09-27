# DAIO AGENT PORTABILITY — PHASE B4B OPENCODE REAL E2E ACCEPTANCE PACKET

**Milestone**: `PORTABILITY-PHASE-B4B — OPENCODE CLI REAL E2E ACCEPTANCE`  
**Status**: `GATE_PASS`  
**Date**: `2026-09-27`  
**Invariant Enforced**: `DAIO-PORTABILITY-INVARIANT-001` (Zero DAIO Core Modifications)

---

## 1. Real Host CLI Environment & Authentication Findings

| Provider | Detected Executable | Detected Version | Observed Authentication Mode | Credential Storage / Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **Antigravity CLI (Control)** | `/Users/huanchen/.local/bin/agy` | `1.2.12` | `LOGIN_SESSION` | Local host session (`~/.gemini`, `~/.antigravity`) |
| **Gemini CLI (Control)** | `/opt/homebrew/bin/gemini` | `0.8.2` | `LOGIN_SESSION` | Local host session (`~/.gemini`) |
| **Codex CLI (Control)** | `/opt/homebrew/bin/codex` | `codex-cli 0.150.1` | `LOGIN_SESSION` | Local host session (`~/.codex`) |
| **OpenCode CLI (New)** | `/Users/huanchen/.opencode/bin/opencode` | `1.17.7` | `PROVIDER_DEPENDENT` | Local provider session / OAuth (`~/.local/share/opencode/auth.json`) |

### Explicit Authentication Classification for OpenCode CLI:
OpenCode operates under **`PROVIDER_DEPENDENT`** authentication mode:
- OpenCode CLI delegates authentication to configured underlying providers (e.g. OpenRouter, OpenCode Go, OpenAI OAuth, Google OAuth) stored in `~/.local/share/opencode/auth.json`.
- DAIO Core does **NOT** own, copy, or persist API keys (`DAIO-AUTH-INVARIANT-001`).
- The user's local authentication environment is used directly by the OpenCode CLI binary during headless invocation.

---

## 2. Actual CLI Invocation Shapes (Redacted)

### 2.1 OpenCode CLI Invocation
```bash
opencode run \
  "<prompt>" \
  --format json \
  --dir <project_root> \
  --dangerously-skip-permissions
```

### 2.2 Control CLI Invocations
- **Antigravity CLI**: `agy --sandbox --dangerously-skip-permissions --print "<prompt>" --output-format json --disable-slash-commands --add-dir <project_root>`
- **Gemini CLI**: `gemini -p "<prompt>" -o json --approval-mode yolo -s -m gemini-2.5-pro`
- **Codex CLI**: `codex exec "<prompt>" --json --sandbox read-only --cd <project_root> -m o3`

---

## 3. Real Disposable Engineering Task E2E Results

The identical deterministic engineering task (`src/math_util.py` `safe_add(a, b) -> a + b`, test gate `tests/test_math.py`) was executed through OpenCode CLI and compared against the 3 control providers:

| Verification Stage | Antigravity CLI | Gemini CLI | Codex CLI | OpenCode CLI | Equivalence Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Proposal Synthesis** | Structured JSON | Structured JSON | Structured JSONL | Structured JSON events | **Normalized `ProposedFileEdit`** |
| **2. Scope Guard Check** | Passed (`src/math_util.py`) | Passed (`src/math_util.py`) | Passed (`src/math_util.py`) | Passed (`src/math_util.py`) | **Identical Two-Tier Policy** |
| **3. Disk Application** | Written by DAIO Executor | Written by DAIO Executor | Written by DAIO Executor | Written by DAIO Executor | **Identical Disk State** |
| **4. Test Integrity Gate** | `pytest tests/ -q` PASSED | `pytest tests/ -q` PASSED | `pytest tests/ -q` PASSED | `pytest tests/ -q` PASSED | **Identical Verification** |
| **5. Turn Audit History** | 1 turn (`APPROVE`) | 1 turn (`APPROVE`) | 1 turn (`APPROVE`) | 1 turn (`APPROVE`) | **Identical SQLite Records** |
| **6. Final FSM Status** | `COMPLETED` | `COMPLETED` | `COMPLETED` | `COMPLETED` | **100% FSM Equivalence** |

---

## 4. Four-Provider 16-Dimensional Comparison Matrix

| # | Dimension | Antigravity CLI | Gemini CLI | Codex CLI | OpenCode CLI | Status |
| :- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Executable / Version** | `agy` / `1.2.12` | `gemini` / `0.8.2` | `codex` / `0.150.1` | `opencode` / `1.17.7` | **Verified Real Host Binaries** |
| **2** | **Auth Mode** | `LOGIN_SESSION` | `LOGIN_SESSION` | `LOGIN_SESSION` | `PROVIDER_DEPENDENT` | **Zero API Key in DAIO Core** |
| **3** | **Non-Interactive Mode** | `--print` flag | `-p` / positional prompt | `codex exec` subcommand | `opencode run` subcommand | **Unattended Execution** |
| **4** | **Structured Output** | `--output-format json` | `-o json` | `--json` (JSONL stream) | `--format json` (JSON stream) | **Standardized Proposal Extraction** |
| **5** | **Proposal Parsing** | JSON envelope $\rightarrow$ markdown | JSON object $\rightarrow$ markdown | JSONL event $\rightarrow$ markdown | JSON event stream $\rightarrow$ markdown | **Normalized to `ProposedFileEdit`** |
| **6** | **Timeout Behavior** | Asyncio subprocess timeout | Asyncio subprocess timeout | Asyncio subprocess timeout | Asyncio subprocess timeout | **Graceful Fail-Closed** |
| **7** | **Failure Behavior** | Exit code $\ne 0 \rightarrow$ fail | Exit code $\ne 0 \rightarrow$ fail | Exit code $\ne 0 \rightarrow$ fail | Exit code $\ne 0 \rightarrow$ fail | **Normalized Error Proposal** |
| **8** | **`allowed_scope` Enforcement** | Pre-write policy guard | Pre-write policy guard | Pre-write policy guard | Pre-write policy guard | **Identical Core Enforcement** |
| **9** | **`frozen_paths` Enforcement** | Unauthorized diff blocked | Unauthorized diff blocked | Unauthorized diff blocked | Unauthorized diff blocked | **Identical Core Enforcement** |
| **10** | **Test Execution** | Baseline-aware pytest | Baseline-aware pytest | Baseline-aware pytest | Baseline-aware pytest | **Identical Test Integrity Gate** |
| **11** | **Evidence Format** | `_daio/evidence/` JSON | `_daio/evidence/` JSON | `_daio/evidence/` JSON | `_daio/evidence/` JSON | **Identical Evidence Schema** |
| **12** | **Git / Provenance** | Atomic commit & SHA | Atomic commit & SHA | Atomic commit & SHA | Atomic commit & SHA | **Identical Deliverable Flow** |
| **13** | **Architect Handoff** | Review role transition | Review role transition | Review role transition | Review role transition | **Identical Review Packaging** |
| **14** | **FSM Transitions** | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | **100% Identical FSM Evolution** |
| **15** | **HUMAN_GATE Preservation** | Passkey/WebAuthn intact | Passkey/WebAuthn intact | Passkey/WebAuthn intact | Passkey/WebAuthn intact | **Zero Security Dilution** |
| **16** | **Unattended Compatibility** | Full sandbox & skip-perm | Full sandbox & yolo-mode | Full sandbox read-only | Full skip-permissions | **Autonomous Operation** |

---

## 5. DAIO Core Modification Count & Audit

| Component | Files Checked | Modifications | Status |
| :--- | :--- | :--- | :--- |
| **DAIO Core Orchestration** | `continuous_orchestrator.py`, `orchestrator.py` | `0` | **ZERO Core Modifications** |
| **Finite State Machine & Routing** | `fsm.py`, `router.py` | `0` | **ZERO Core Modifications** |
| **Supervisor & Work Store** | `supervisor.py`, `store.py`, `sqlite_store.py` | `0` | **ZERO Core Modifications** |
| **Leasing & Watchdog** | `lease.py`, `watchdog.py`, `recovery.py` | `0` | **ZERO Core Modifications** |
| **Human Gate & Ingress** | `remote_relay.py`, `passkey_admin.py` | `0` | **ZERO Core Modifications** |

---

## 6. Test Verification Summary

### 6.1 Focused B4B Test Suite (`tests/test_opencode_cli_e2e_b4b.py`)
- `test_opencode_host_binary_and_version_inspection` — Real host binary detection & version 1.17.7 verification. **(PASSED)**
- `test_opencode_provider_dependent_auth_mode` — Verifies provider-dependent auth without DAIO API keys. **(PASSED)**
- `test_opencode_structured_proposal_extraction_and_event_stream` — Multi-line JSON event stream proposal parsing. **(PASSED)**
- `test_opencode_scope_and_frozen_path_enforcement` — DAIO Two-Tier policy guard enforcement against OpenCode proposals. **(PASSED)**
- `test_opencode_real_disposable_engineering_e2e_equivalence` — Closed-loop FSM equivalence matching B4A control CLIs. **(PASSED)**
- `test_opencode_failure_and_timeout_normalization` — Timeout and error normalization. **(PASSED)**
- `test_zero_daio_core_modification_invariant_b4b` — AST source scan verifying zero core changes across all core modules. **(PASSED)**

**Focused Test Count**: `7 passed / 7`

### 6.2 Full Generic DAIO Regression Suite
- **Total Tests**: `240`
- **Passed**: `240` (`100%`)
- **Failed**: `0`
- **Execution Time**: `26.93s`

---

## 7. Multi-Repository Provenance Synchronization

1. **Canonical Upstream Repository**:
   - URL: `https://github.com/huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill.git`
   - Branch: `main`
2. **Installed Skill**:
   - Path: `/Users/huanchen/.gemini/config/skills/daio`
3. **Downstream Integration**:
   - Path: `_AwinFinTechHybridSystem_/_daio/`
4. **Persistent Live Supervisor**:
   - Status: `ONLINE / FRESH` (PID `36108`, `queue_depth: 0`, `human_gate_required: false`)
