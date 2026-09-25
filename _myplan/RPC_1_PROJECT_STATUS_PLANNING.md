# DAIO RPC-1: `RPC-ProjectStatus` Planning & Architecture Checkpoint

---

## 1. Executive Summary & Objective

**RPC-1 (`RPC-ProjectStatus`)** defines the standard, domain-neutral remote procedure call (RPC) endpoint for the DAIO orchestration framework. It provides structured, machine-readable observability into DAIO's durable work queue, active supervisor heartbeats, git synchronization state, and watchdog recovery metrics.

This enables:
* **Remote Mobile Observability (e.g., iPhone / Telegram / Web Dashboards)**: Real-time inspection of continuous iteration progress without terminal/SSH access.
* **Automated CI/CD & Governance Gates**: Structured polling of work-item completion and human-gate requirements.
* **Audit & Forensics**: Immediate, zero-overhead verification of durable lineage, active recovery epochs, and baseline regression results.

---

## 2. Architectural Boundaries & Invariants

1. **Strict Read-Only Semantics**:
   * Invoking `RPC-ProjectStatus` must **never** mutate SQLite state, acquire/release worker leases, trigger stall recoveries, or modify git files.
2. **Domain Neutrality**:
   * Zero hardcoded financial terms, tickers, trading indicators, or project-specific symbols. The RPC layer is purely orchestration-native.
3. **Fail-Closed Fallback & Security**:
   * Operates over loopback (`127.0.0.1`) by default with optional bearer token authorization.
   * If the SQLite database is temporarily locked, returns a well-typed degraded response rather than crashing the supervisor daemon.

---

## 3. Protocol Specification

* **Protocol**: JSON-RPC 2.0 / REST GET query
* **Method Name**: `daio.getProjectStatus` (or HTTP `GET /api/v1/status`)

### 3.1 Request Payload
```json
{
  "jsonrpc": "2.0",
  "method": "daio.getProjectStatus",
  "params": {
    "include_history": false,
    "include_heartbeats": true,
    "include_watches": true
  },
  "id": "req-001"
}
```

### 3.2 Structured Response Schema
```json
{
  "jsonrpc": "2.0",
  "result": {
    "project_name": "AwinFinTechSMCHybridSystem",
    "project_root": "/Users/.../_AwinFinTechHybridSystem_",
    "timestamp": "2026-09-25T09:30:00.000000Z",
    "git": {
      "branch": "main",
      "head_sha": "fed57af9587d7b7e99957604bda0bf875f54a13e",
      "remote_url": "https://github.com/...",
      "remote_head_sha": "fed57af9587d7b7e99957604bda0bf875f54a13e",
      "ahead": 0,
      "behind": 0,
      "clean": true
    },
    "supervisor": {
      "supervisor_id": "supervisor-029cb6",
      "pid": 91763,
      "status": "RUNNING",
      "started_at": "2026-09-25T08:00:42.000000Z",
      "last_heartbeat_at": "2026-09-25T09:30:00.000000Z",
      "active_work_id": null,
      "queue_depth": 0
    },
    "work_items": [
      {
        "work_id": "daio-root-change_051_implementation",
        "change_id": "CHANGE_051_IMPLEMENTATION",
        "current_stage": "CHANGE_051_IMPLEMENTATION",
        "current_gate": "IMPLEMENTATION_GATE",
        "assigned_role": "LEAD_ARCHITECT_REVIEW",
        "status": "COMPLETED",
        "last_decision": "APPROVE",
        "attempt_count": 0,
        "head_sha": "5d5d4e2c6e1ec9055b68d2444e17b81d7ca435de",
        "human_action_required": false
      }
    ],
    "handoff_watches": {
      "active_count": 0,
      "stalled_count": 0,
      "watches": []
    },
    "regression_gate_summary": {
      "test_command": "pytest tests/ -q",
      "baseline_sha": "3836a3e",
      "baseline_failures_count": 4,
      "last_regression_status": "NO_NEW_REGRESSIONS_PASS"
    }
  },
  "id": "req-001"
}
```

---

## 4. Implementation Decomposition & Milestones

* **[M1] Model & Protocol Contracts**: Define `ProjectStatusRequest`, `ProjectStatusResponse`, `GitStatusDTO`, and `SupervisorStatusDTO` dataclasses in `scripts/daio_closed_loop/models.py`.
* **[M2] Core RPC Handler**: Implement `DAIOStatusRPCService` in `scripts/daio_closed_loop/rpc.py` to query `SqliteDAIOWorkStore` and Git environment safely.
* **[M3] CLI & Lightweight Server Endpoint**: Add `daio rpc status` subcommand and integrate an optional async HTTP JSON endpoint inside `DAIOSupervisor`.
* **[M4] Determinism & Isolation Tests**: Implement `tests/test_rpc_project_status.py` verifying domain neutrality, schema conformance, read-only guarantees, and offline degraded mode handling.

---

## 5. Review & Authorization Gate

* **Status**: **`PLANNING_CHECKPOINT_AWAITING_REVIEW`**
* **Next Action**: Awaiting Lead Architect sign-off before commencing M1–M4 implementation code.
