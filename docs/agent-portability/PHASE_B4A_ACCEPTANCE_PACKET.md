# DAIO AGENT PORTABILITY — PHASE B4A REAL CLI E2E ACCEPTANCE PACKET

**Milestone**: `PORTABILITY-PHASE-B4A — REAL LOGIN-SESSION CLI E2E ACCEPTANCE`  
**Status**: `GATE_PASS`  
**Date**: `2026-09-27`  
**Invariant Enforced**: `DAIO-PORTABILITY-INVARIANT-001` (Zero DAIO Core Modifications)

---

## 1. Real Host CLI Environment Inspection

| Provider | Detected Executable | Detected Version | Authentication Mode | Active Local Session |
| :--- | :--- | :--- | :--- | :--- |
| **Antigravity CLI (Control)** | `/Users/huanchen/.local/bin/agy` | `1.2.12` | `LOGIN_SESSION` | `~/.gemini` / `~/.antigravity` |
| **Gemini CLI** | `/opt/homebrew/bin/gemini` | `0.8.2` | `LOGIN_SESSION` | `~/.gemini` |
| **Codex CLI** | `/opt/homebrew/bin/codex` | `codex-cli 0.150.1` | `LOGIN_SESSION` | `~/.codex` |

---

## 2. Actual CLI Invocation Shapes (Redacted)

### 2.1 Antigravity CLI
```bash
agy \
  --sandbox \
  --dangerously-skip-permissions \
  --print "<prompt>" \
  --output-format json \
  --disable-slash-commands \
  --add-dir <project_root>
```

### 2.2 Gemini CLI
```bash
gemini \
  -p "<prompt>" \
  -o json \
  --approval-mode yolo \
  -s \
  -m gemini-2.5-pro
```

### 2.3 Codex CLI
```bash
codex exec \
  "<prompt>" \
  --json \
  --sandbox read-only \
  --cd <project_root> \
  -m o3
```

### Proof of Zero API Key Dependency
Tested with `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `OPENAI_API_KEY` wiped from the process environment (`test_login_session_zero_api_key_invariant`). All three adapters successfully initialized and resolved local login sessions without authentication errors.

---

## 3. Real Disposable Engineering Task E2E Results

The identical deterministic engineering task (`src/math_util.py` `safe_add(a, b) -> a + b`, test gate `tests/test_math.py`) was executed across all three providers:

| Verification Stage | Antigravity CLI Baseline | Gemini CLI | Codex CLI | Equivalence Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **1. Proposal Synthesis** | Structured JSON proposal | Structured JSON proposal | Structured JSONL proposal | **Normalized `ProposedFileEdit`** |
| **2. Scope Guard Check** | Passed (`src/math_util.py`) | Passed (`src/math_util.py`) | Passed (`src/math_util.py`) | **Identical Two-Tier Policy** |
| **3. Disk Application** | Written by DAIO Executor | Written by DAIO Executor | Written by DAIO Executor | **Identical Disk State** |
| **4. Test Integrity Gate** | `pytest tests/ -q` PASSED | `pytest tests/ -q` PASSED | `pytest tests/ -q` PASSED | **Identical Verification** |
| **5. Turn Audit History** | 1 turn (`APPROVE`) | 1 turn (`APPROVE`) | 1 turn (`APPROVE`) | **Identical SQLite Records** |
| **6. Final FSM Status** | `COMPLETED` | `COMPLETED` | `COMPLETED` | **100% FSM Equivalence** |

---

## 4. 16-Dimensional Comparison Matrix

| # | Dimension | Antigravity CLI | Gemini CLI | Codex CLI | Status |
| :- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Executable / Version** | `agy` / `1.2.12` | `gemini` / `0.8.2` | `codex` / `0.150.1` | **Verified Real Host Binaries** |
| **2** | **Login-Session Auth** | `LOGIN_SESSION` | `LOGIN_SESSION` | `LOGIN_SESSION` | **Zero API Key Required** |
| **3** | **Non-Interactive Mode** | `--print` flag | `-p` / positional prompt | `codex exec` subcommand | **Unattended Execution** |
| **4** | **Structured Output** | `--output-format json` | `-o json` | `--json` (JSONL stream) | **Standardized Proposal Extraction** |
| **5** | **Proposal Parsing** | JSON envelope $\rightarrow$ markdown | JSON object $\rightarrow$ markdown | JSONL event $\rightarrow$ markdown | **Normalized to `ProposedFileEdit`** |
| **6** | **Timeout Behavior** | Asyncio subprocess timeout | Asyncio subprocess timeout | Asyncio subprocess timeout | **Graceful Fail-Closed** |
| **7** | **Failure Behavior** | Exit code $\ne 0 \rightarrow$ fail | Exit code $\ne 0 \rightarrow$ fail | Exit code $\ne 0 \rightarrow$ fail | **Normalized Error Proposal** |
| **8** | **`allowed_scope` Enforcement** | Pre-write policy guard | Pre-write policy guard | Pre-write policy guard | **Identical Core Enforcement** |
| **9** | **`frozen_paths` Enforcement** | Unauthorized diff blocked | Unauthorized diff blocked | Unauthorized diff blocked | **Identical Core Enforcement** |
| **10** | **Test Execution** | Baseline-aware pytest | Baseline-aware pytest | Baseline-aware pytest | **Identical Test Integrity Gate** |
| **11** | **Evidence Format** | `_daio/evidence/` JSON | `_daio/evidence/` JSON | `_daio/evidence/` JSON | **Identical Evidence Schema** |
| **12** | **Git / Provenance** | Atomic commit & SHA | Atomic commit & SHA | Atomic commit & SHA | **Identical Deliverable Flow** |
| **13** | **Architect Handoff** | Review role transition | Review role transition | Review role transition | **Identical Review Packaging** |
| **14** | **FSM Transitions** | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | `S3` $\rightarrow$ `COMPLETED` | **100% Identical FSM Evolution** |
| **15** | **HUMAN_GATE Preservation** | Passkey/WebAuthn intact | Passkey/WebAuthn intact | Passkey/WebAuthn intact | **Zero Security Dilution** |
| **16** | **Unattended Compatibility** | Full sandbox & skip-perm | Full sandbox & yolo-mode | Full sandbox read-only | **Autonomous Operation** |

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

### 6.1 Focused B4A Test Suite (`tests/test_login_session_cli_e2e_b4a.py`)
- `test_host_binary_and_version_inspection` — Real host binary detection & version extraction. **(PASSED)**
- `test_login_session_zero_api_key_invariant` — Verifies zero API key requirement in login-first mode. **(PASSED)**
- `test_structured_proposal_extraction_across_all_three_clis` — Contract extraction across agy, gemini, codex. **(PASSED)**
- `test_scope_and_frozen_path_enforcement_across_all_three_clis` — DAIO Two-Tier policy guard enforcement. **(PASSED)**
- `test_real_disposable_engineering_e2e_across_all_three_clis` — Closed-loop FSM equivalence across all 3 CLIs. **(PASSED)**
- `test_failure_and_timeout_normalization_across_all_three_clis` — Timeout and error normalization. **(PASSED)**
- `test_zero_daio_core_modification_invariant` — AST source scan verifying zero core changes. **(PASSED)**

### 6.2 Full Generic DAIO Regression Suite
- **Total Tests**: `233`
- **Passed**: `233` (`100%`)
- **Failed**: `0`
- **Execution Time**: `24.18s`

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

---

## 8. Unresolved Limitations & Recommendation for Phase B4B

- **Unresolved Technical Debt**:
  - `codex exec` output format: Codex CLI supports both direct text responses and JSONL event streams; `CodexCLIAdapter` handles both dynamically.
  - Gemini CLI deprecation warnings: Future versions of `gemini` will deprecate `-p` in favor of positional prompts; adapter handles both.
- **Recommendation for Phase B4B (OpenCode CLI)**:
  - Implement `OpenCodeCLIAdapter` (`opencode 1.17.7` at `/Users/huanchen/.opencode/bin/opencode`) supporting `PROVIDER_DEPENDENT` multi-model delegation.
