# DAIO Human Channel Security Model & Mandatory Invariants (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## Mandatory Security Invariants

### 1. `DAIO-HUMAN-INVARIANT-001`: Authority Boundary
$$\text{COMMUNICATION CHANNEL} \neq \text{AUTHORIZATION AUTHORITY}$$
A messaging interface is a transport medium, not an authorization authority.

### 2. `DAIO-HUMAN-INVARIANT-002`: No Auth Downgrade on Failover
Channel failover **MUST NOT** downgrade security requirements. If Telegram fails and LINE receives the prompt, the decision still requires `STRONG_AUTHENTICATED` validation.

### 3. `DAIO-HUMAN-INVARIANT-003`: Single Canonical Ingestion Path
All Human Gate state transitions strictly route through the canonical SQLite `BEGIN IMMEDIATE` decision ledger and Action Ticket verification engine.

### 4. `DAIO-HUMAN-INVARIANT-004`: Exactly-Once Human Decisions
Concurrent or duplicate responses across multiple messaging channels are deduplicated via idempotency keys and applied exactly once.

### 5. `DAIO-HUMAN-INVARIANT-005`: Credential Isolation
Third-party channel credentials, tokens, or bot secrets must **NEVER** enter DAIO Core, Git history, evidence payloads, or provenance logs.

### 6. `DAIO-HUMAN-INVARIANT-006`: Workflow Ownership
$$\text{CHANNEL} \neq \text{WORKFLOW OWNER}$$
DAIO SQLite state is the sole canonical source of truth.

### 7. `DAIO-HUMAN-INVARIANT-007`: External Natural Language Normalization
Natural-language understanding and command parsing execute outside of DAIO Core.

### 8. `DAIO-HUMAN-INVARIANT-008`: Orthogonal Federation
Agent Provider Federation (AGY, Gemini, Codex, OpenCode) and Human Channel Federation (ChatGPT, Cockpit, Telegram, LINE, Messenger) remain completely orthogonal.
