# DAIO Phase C1 Canonical Architect Decision Contract

## 1. Machine-Readable JSON Decision Schema

ChatGPT Architect responses must conclude with a machine-readable JSON control block:

```json
{
  "decision": "APPROVE",
  "work_id": "CHANGE_055",
  "change_id": "CHANGE_055",
  "epoch": 1,
  "reason": "Verification suite passed with 100% compliance. Architecture satisfies C1 requirements.",
  "required_actions": [],
  "authorized_next_phase": "FINAL_CLOSURE",
  "human_gate_required": false,
  "evidence_assessment": "SATISFACTORY"
}
```

### Supported Decisions

1. `APPROVE`: Work item verified; advance to authorized next phase.
2. `REVISE`: Defects or omissions identified; trigger subsequent engineering iteration.
3. `STOP`: Terminal halt; stop closed loop without creating successor tasks.
4. `HUMAN_GATE`: Sensitive architectural or security threshold; require Cockpit Passkey / Face ID signoff.

---

## 2. Validation & Stale Protection Invariants

Before applying any decision to the canonical SQLite WorkStore, DAIO verifies:
1. **Work ID & Change ID Matching**: Response must match the currently executing work item. Mismatched IDs fail closed with `STALE_OR_MISMATCHED_WORK_ID`.
2. **Recovery Epoch Verification**: Response must match the active recovery epoch. Stale responses from earlier iterations fail closed with `STALE_EPOCH`.
3. **Schema Compliance**: Unknown decisions or missing required fields are rejected safely.
