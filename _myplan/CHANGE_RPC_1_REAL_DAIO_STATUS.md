# OpenSpec Change Record: CHANGE-DAIO-RPC-001

* **Change ID**: `CHANGE-DAIO-RPC-001`
* **Title**: `RPC-1: Real DAIO Two-Plane Status Adapter & Outbound Publication Engine`
* **Status**: **`IMPLEMENTATION_COMPLETE_AWAITING_OWNER_E2E_ACCEPTANCE`**
* **Target Stage**: `RPC-1 (Read-Only Status)`
* **Author**: `Antigravity Coding Agent`
* **Reviewer**: `Lead Architect (ChatGPT) & Project Owner`

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
4. **Outbound-Only Ingress**: Workstation initiates authenticated HTTPS publication (`POST /api/v1/publish`) to Cloudflare Relay. Zero open inbound ports on the developer workstation.
5. **Mandatory Publisher Authentication & Fail-Closed Invariant**: `DAIO_RPC_PUBLISH_TOKEN` is mandatory on the Cloudflare Relay. If the secret is missing/unconfigured, the relay strictly fails closed (HTTP 503) and rejects all publications. Publications without valid matching Bearer tokens are rejected (HTTP 401).
6. **Strict Scope Boundary**: Strictly read-only status inspection. Zero remote decision delivery (RPC-2), remote push alerts (RPC-3), remote shell, or Human Gate mutation.


---

## 3. Implementation Manifest

| Component | File Path | Scope & Responsibility |
|---|---|---|
| **Two-Plane Models** | `scripts/daio_closed_loop/models.py` | `FreshnessEnum`, `evaluate_freshness()`, `LivePlaneStatus`, `DurablePlaneStatus`, `DAIOProjectStatusResponse`. |
| **Status Collector** | `scripts/daio_closed_loop/adapters/rpc_status_collector.py` | Gathers real state from `SqliteDAIOWorkStore` and Git CLI; evaluates PID liveness and freshness. |
| **Status Publisher** | `scripts/daio_closed_loop/adapters/rpc_status_publisher.py` | Outbound authenticated HTTPS client transmitting Two-Plane payloads with Bearer token. |
| **Adapter Registry** | `scripts/daio_closed_loop/adapters/__init__.py` | Exports `DAIOStatusCollector` and `DAIOStatusPublisher`. |
| **DAIO CLI** | `daio` | Implements `daio rpc-status` (local JSON dump) and `daio rpc-publish` (relay publication). |
| **Relay Worker** | `_myplan/poc0/poc0_worker.js` | Cloudflare Worker accepting authenticated POST `/api/v1/publish` and serving dynamic GET `/api/v1/status`. |
| **Test Suite** | `tests/test_rpc_status_collector.py` | 6 unit tests validating freshness engine, PID checks, RUNNING suppression, and domain neutrality. |
| **Test Suite** | `tests/test_rpc_status_publisher.py` | 4 unit tests validating HTTP auth headers, 200 OK, 401 Unauthorized, network resilience, and loop termination. |

---

## 4. Verification Results

```text
pytest tests/ -q
134 passed in 8.33s (100% PASS)
```

Domain neutrality validated with zero domain-specific token leaks (`2330.TW`, `SMC7S`, `Pine`).
