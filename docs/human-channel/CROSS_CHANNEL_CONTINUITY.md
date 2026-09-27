# DAIO Cross-Channel Continuity & Workflow Ownership Invariants (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## 1. Core Invariant: Canonical Workflow Ownership

$$\mathbf{CHANNEL \neq WORKFLOW\ OWNER}$$
$$\mathbf{DAIO\ IS\ THE\ SOLE\ CANONICAL\ WORKFLOW\ OWNER}$$

Channels (ChatGPT, Telegram, LINE, Messenger) act solely as interaction and command transport mediums. They do not own or persist SQLite work state, gate authority, or execution leases.

---

## 2. Conversation Reference Mapping Layer

```text
Channel / Conversation Session            Canonical DAIO Context
┌──────────────────────────────┐          ┌──────────────────────┐
│ ChatGPT Thread #101          │ ───────► │ Project: awin-fintech│
├──────────────────────────────┤          │ Work: daio-work-052  │
│ Telegram Chat #555           │ ───────► │ Change: CHANGE_052   │
├──────────────────────────────┤          │ Gate: S3 / IMPL_GATE │
│ LINE Group #999              │ ───────► │ Status: IN_PROGRESS  │
└──────────────────────────────┘          └──────────────────────┘
```

When a user switches devices throughout the day:
1. **Morning in ChatGPT**: `"Start Change 052"` $\rightarrow$ establishes canonical context `daio-work-052`.
2. **Afternoon on Telegram**: `"What is the status of Change 052?"` $\rightarrow$ maps to `daio-work-052`.
3. **Evening in ChatGPT**: `"Continue until the next Human Gate"` $\rightarrow$ maps to `daio-work-052`.

---

## 3. Exactly-Once Decision Ledger Invariant

When multiple channels present options or receive approvals concurrently:

```text
ChatGPT APPROVE   ──► Idempotency Key: "idemp-052-approval" ──► APPLIED (1st)
Telegram APPROVE  ──► Idempotency Key: "idemp-052-approval" ──► DUPLICATE (Ignored)
Cockpit APPROVE   ──► Idempotency Key: "idemp-052-approval" ──► DUPLICATE (Ignored)
```

The atomic SQLite decision ledger ensures that exactly **ONE** state transition is processed.
