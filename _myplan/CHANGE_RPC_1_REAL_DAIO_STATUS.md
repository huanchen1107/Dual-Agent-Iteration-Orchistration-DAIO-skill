# OpenSpec Change Record: CHANGE-DAIO-RPC-001

* **Change ID**: `CHANGE-DAIO-RPC-001`
* **Title**: `RPC-1: Real DAIO Two-Plane Status Adapter & Outbound Publication Engine`
* **Status**: **`ACCEPTED_BY_PROJECT_OWNER (PASS)`**
* **Target Stage**: `RPC-1 (Read-Only Status)`
* **Author**: `Antigravity Coding Agent`
* **Reviewer**: `Lead Architect (ChatGPT) & Project Owner`
* **Canonical Milestones**:
  * `PoC-0A`: **`PASS`**
  * `RPC-1`: **`PASS`**
  * `RPC-2`: **`NOT STARTED`**
  * `RPC-3`: **`NOT STARTED`**

---

## 1. Context & Motivation

PoC-0A verified remote reachability from iPhone to Cloudflare Relay (`https://daio-relay.huanchen1107.workers.dev/`).
`CHANGE-DAIO-RPC-001` establishes the real, non-mock data pipeline replacing hardcoded mock status with live execution evidence and durable Git provenance collected directly from the Mac/PC DAIO instance without exposing localhost to the public Internet.

---

## 2. Inviolable Governance & Architecture Invariants

1. **Adapter Over Control Plane**: RPC is strictly an access adapter over the existing canonical DAIO control plane (`SqliteDAIOWorkStore` + local/remote Git). Zero duplicate state machines, secondary task boards, or parallel databases.
2. **Two-Plane Separation**:
   * **Live Plane**: Host status, real supervisor PID liveness, active work item, gate, role, `HUMAN_GATE_REQUIRED`, and heartbeat freshness.
   * **Durable Plane**: Git branch, local HEAD SHA, remote `origin/main` SHA, ahead/behind counts, working-tree cleanliness, push synchronization.
3. **Freshness Invariant**: A previously recorded `RUNNING` supervisor state must **NEVER** be presented as currently `RUNNING` when live heartbeat freshness is `STALE` ($\ge 30\text{s}$), `OFFLINE` ($> 180\text{s}$), or `UNKNOWN`.
4. **Publisher Liveness vs Supervisor Freshness**: `FRESH` strictly requires fresh real DAIO supervisor heartbeat evidence, not merely that the `rpc-publish` client process is running.
5. **Outbound-Only Ingress**: Workstation initiates outbound authenticated HTTPS publication (`POST /api/v1/publish`) to Cloudflare Relay. Zero open inbound ports on the developer workstation.
6. **Mandatory Publisher Authentication & Fail-Closed Invariant**: `DAIO_RPC_PUBLISH_TOKEN` is mandatory on the Cloudflare Relay. If the secret is missing/unconfigured, the relay strictly fails closed (HTTP 503) and rejects all publications. Publications without valid matching Bearer tokens are rejected (HTTP 401).
7. **Read-Only Status Surface**: The remote status API (`GET /api/v1/status`) is strictly read-only. Zero remote SQLite mutation, zero Human Gate mutation, zero remote command execution, and zero remote shell capabilities.

---

## 3. Implementation Manifest

| Component | File Path | Scope & Responsibility |
|---|---|---|
| **Two-Plane Models** | `scripts/daio_closed_loop/models.py` | `FreshnessEnum`, `evaluate_freshness()`, `LivePlaneStatus`, `DurablePlaneStatus`, `DAIOProjectStatusResponse`. |
| **Status Collector** | `scripts/daio_closed_loop/adapters/rpc_status_collector.py` | Gathers real state from `SqliteDAIOWorkStore` and Git CLI; evaluates PID liveness and freshness. |
| **Status Publisher** | `scripts/daio_closed_loop/adapters/rpc_status_publisher.py` | Outbound authenticated HTTPS client transmitting Two-Plane payloads with `Connection: close` and live CLI output. |
| **Adapter Registry** | `scripts/daio_closed_loop/adapters/__init__.py` | Exports `DAIOStatusCollector` and `DAIOStatusPublisher`. |
| **DAIO CLI** | `daio` | Implements `daio rpc-status` (local JSON dump) and `daio rpc-publish` (relay publication). |
| **Relay Worker** | `_myplan/poc0/poc0_worker.js` | Cloudflare Worker accepting authenticated POST `/api/v1/publish` and serving dynamic GET `/api/v1/status`. |
| **Test Suite** | `tests/test_rpc_status_collector.py` | 6 unit tests validating freshness engine, PID checks, RUNNING suppression, and domain neutrality. |
| **Test Suite** | `tests/test_rpc_status_publisher.py` | 5 unit tests validating HTTP auth headers, 200 OK, 401 Unauthorized, network resilience, and continuous multi-cycle loop. |

---

## 4. Verification Results & Project Owner E2E Acceptance

### Automated Test Suite
```text
pytest tests/ -q
136 passed in 14.01s (100% PASS)
```

### Live Project Owner E2E Acceptance Evidence
Target Project: `/Users/huanchen/Desktop/2026 Projects/2026.8.26AwinFinTechSMCHybridSystemFolder/_AwinFinTechHybridSystem_`
Relay Endpoint: `https://daio-relay.huanchen1107.workers.dev/api/v1/status`

#### 1. FRESH State (Live Continuous Publishing Active)
* `host_status`: `ONLINE`
* `freshness`: `FRESH`
* `supervisor_running`: `true`
* `heartbeat_age_seconds`: `28`
* `transit_age_seconds`: `27`
* `active_work_item`: `050`
* `current_phase`: `S3`
* `current_gate`: `IMPLEMENTATION_GATE`
* `active_agent`: `Antigravity`

#### 2. STALE State (After Stopping RPC Publisher)
* `freshness`: `STALE`
* `heartbeat_age_seconds`: `46`
* `transit_age_seconds`: `44`
* `degraded_note`: `Live execution unconfirmed.`

#### 3. OFFLINE State (After Freshness Expiry)
* `host_status`: `OFFLINE`
* `freshness`: `OFFLINE`
* `heartbeat_age_seconds`: `200`
* `transit_age_seconds`: `198`
* `supervisor_running`: `false`
* `degraded_note`: `Host heartbeat expired (200s ago). Execution offline.`

#### 4. Durable Plane Truthfulness (Intact Throughout)
* `repository`: `huanchen1107/_AwinFinTechHybridSystem_`
* `local_head_sha`: `f584dd175e8ecf858eb2dbe8651632f81654e360`
* `remote_origin_sha`: `f584dd175e8ecf858eb2dbe8651632f81654e360`
* `ahead_count`: `0`
* `behind_count`: `0`
* `working_tree_clean`: `true`
* `push_synchronized`: `true`

---

## 5. Security & Governance Invariants Summary

* ✅ Outbound-only Mac HTTPS publication (`POST /api/v1/publish`).
* ✅ Mandatory fail-closed token authentication on Cloudflare Relay.
* ✅ Zero secrets stored or committed in Git repository.
* ✅ Read-only remote query surface (`GET /api/v1/status`).
* ✅ Zero remote SQLite database mutations.
* ✅ Zero Human Gate remote bypass or mutation.
* ✅ Zero remote arbitrary command or shell execution.
