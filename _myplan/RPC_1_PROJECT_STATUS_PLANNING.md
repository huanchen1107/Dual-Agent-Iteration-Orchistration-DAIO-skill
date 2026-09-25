# DAIO RPC-1: `RPC-ProjectStatus` (Remote Project Cockpit) Planning & Architecture Checkpoint

---

## 1. Canonical Definition & Objective

* **RPC Identifier**: `RPC-1 — RPC-ProjectStatus`
* **Canonical Terminology**: **RPC = Remote Project Cockpit** *(Not "Remote Procedure Call")*

The **Remote Project Cockpit (RPC)** framework defines the standard, domain-neutral remote observability architecture for DAIO. `RPC-ProjectStatus` provides structured, verifiable inspection into a project's live execution telemetry, durable Git checkpoints, supervisor heartbeats, and watchdog recovery metrics.

### Primary Use Cases:
* **Mobile Project Cockpit (e.g. iPhone ChatGPT / Telegram / Web UI)**: Real-time, trusted inspection of continuous development and iteration progress without direct terminal/SSH access.
* **Continuous Governance & Gate Polling**: Structured evaluation of work-item completion, human-gate requirements, and regression gates.
* **Audit & Forensics**: Independent verification of durable lineage, active recovery epochs, and baseline regression results.

---

## 2. End-User Acceptance Scenario

### Scenario: iPhone Project Cockpit Query
* **User Context**: The human project owner is away from the workstation, opening ChatGPT on an iPhone.
* **User Query**:
  > **「現在專案做到哪裡了？」**
* **Expected Cockpit Response Contract**:
  The response must be grounded in fresh, verifiable DAIO state and **strictly separate live execution state from durable Git checkpoint state**:
  1. **Durable Milestone**: State the latest verified, pushed GitHub commit SHA, change title, and test pass baseline.
  2. **Live Execution**: State whether the local supervisor daemon is actively running right now, what work item is in progress, current gate, and whether human action is required.
  3. **Freshness & Degraded Transparency**: If the workstation is asleep, offline, or behind NAT, explicitly declare live state as `OFFLINE` or `STALE` with the last observed heartbeat timestamp—**never hallucinate that work is actively progressing when live telemetry is unavailable**.

---

## 3. Formal Two-Plane Architecture

`RPC-ProjectStatus` aggregates information across two decoupled planes, preserving provenance and timestamps independently:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│              DAIO Remote Project Cockpit (RPC-ProjectStatus)            │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         ▼                                                       ▼
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│           LIVE PLANE            │     │          DURABLE PLANE          │
├─────────────────────────────────┤     ├─────────────────────────────────┤
│ • Daemon Liveness & Heartbeat   │     │ • Git Working Tree Cleanliness  │
│ • Active Supervisor PID/Uptime  │     │ • Local HEAD vs Remote SHA      │
│ • Active Work Item & Gate       │     │ • Verified Push Status (Origin) │
│ • Current Assigned Agent / Role │     │ • Closed OpenSpec Changes       │
│ • Recovery Epoch & Watchdog     │     │ • Durable Audit Turn History    │
│ • Human Action Requirement      │     │ • Baseline Regression Archive   │
└─────────────────────────────────┘     └─────────────────────────────────┘
```

---

## 4. Freshness Contract & Invariants

### 4.1 Freshness State Machine
Every telemetry payload emitted by `RPC-ProjectStatus` must declare an explicit `freshness_state`:

| Freshness Class | Criteria | Semantics & Cockpit Policy |
|---|---|---|
| **`FRESH`** | Live supervisor/worker heartbeat recorded within the last **30 seconds**. | Active, real-time live execution. Work-in-progress claims are valid. |
| **`STALE`** | Last heartbeat recorded between **30 seconds and 180 seconds** ago. | Potential daemon stall, high system load, or brief network disruption. Report with clear staleness warning. |
| **`OFFLINE`** | No heartbeat received for **> 180 seconds**, or daemon explicitly stopped. | Host machine is asleep, disconnected, or daemon terminated. |
| **`UNKNOWN`** | Telemetry source unreachable or database uninitialized. | Cannot determine live status. State must be treated as unverified. |

### 4.2 Core Freshness Invariant
> [!IMPORTANT]
> **A previously recorded `RUNNING` state must NEVER be presented as currently `RUNNING` when the live heartbeat is `STALE`, `OFFLINE`, or `UNKNOWN`.**

---

## 5. Degraded-State Behavior

When the host machine or DAIO daemon is unreachable:
1. `live_plane.status` MUST be reported as **`OFFLINE`** or **`UNKNOWN`**.
2. `live_plane.last_observed_heartbeat` may be provided for forensic context with an explicit historical timestamp.
3. `durable_plane` MUST independently report the last verified GitHub commit SHA, push status, and completed OpenSpec milestones.
4. **Safety Constraint**: The cockpit response MUST explicitly declare that live execution is stopped/unreachable and MUST NOT claim that background iterations are ongoing.

---

## 6. Remote Transport Architecture

* **Status**: **`UNRESOLVED — ARCHITECTURE DECISION REQUIRED`**

### Implementation Candidates Under Consideration:
1. **Candidate A: GitHub-Backed Ephemeral Checkpoint Channel**
   * DAIO daemon pushes non-blocking, lightweight telemetry / status snapshots to a dedicated branch, issue comment, or release asset on GitHub.
   * *Pros*: Works 100% through NAT, zero firewall configuration, directly accessible by ChatGPT Web/Mobile.
   * *Cons*: Small latency delay (30–60s), rate limit budgeting required.
2. **Candidate B: Reverse Tunnel / Webhook Relay (e.g. Cloudflare Tunnel / WebSocket Relay)**
   * Outbound secure websocket connection from DAIO daemon to a hardened relay endpoint.
   * *Pros*: Sub-second real-time responsiveness.
   * *Cons*: Requires external relay infrastructure and credentials.
3. **Candidate C: Local-Only Read-Only Service API**
   * Loopback HTTP/IPC query on `127.0.0.1`.
   * *Pros*: Zero external dependencies, pure local inspection.
   * *Cons*: Cannot be queried directly by mobile iPhone ChatGPT across NAT without local tunneling.

> [!NOTE]
> Local read-only service APIs are evaluated as foundational local inspection utilities, but the canonical iPhone remote transport mechanism remains an open architectural decision for Lead Architect determination.

---

## 7. Open Architecture Questions for Lead Architect Review

1. **NAT Traversal & Remote Ingestion**:
   * *Core Question*: **How does iPhone ChatGPT securely obtain fresh PC/DAIO live state when the PC is behind NAT and localhost is not reachable from ChatGPT?**
   * *Decision Options*: GitHub-mediated telemetry branch/issue vs. lightweight encrypted outbound relay vs. ChatGPT Custom GPT Action with authenticated webhook.
2. **Polling vs. Push Cadence**:
   * What is the maximum acceptable telemetry freshness window for mobile cockpit queries (e.g., 30s vs. 60s vs. on-demand event-driven)?
3. **Authentication & Authorization**:
   * What token verification mechanism should guard remote cockpit queries if an external transport endpoint is exposed?

---

## 8. Domain Neutrality & Integration Boundaries

* **Pure Generic Orchestration**: The RPC layer operates strictly on DAIO orchestration models (`DAIOWorkItem`, `SupervisorHeartbeat`, `HandoffWatch`, Git status).
* **Domain Isolation**: Zero hardcoded trading rules, symbols (e.g., `2330.TW`), or algorithmic strategies. Target systems (such as `_AwinFinTechHybridSystem_` / SMC7S) serve strictly as downstream execution and verification consumers.

---

## 9. Implementation Milestones (Deferred Pending Review)

* **[M1] Two-Plane Data Contracts & Models**: Define `CockpitStatusResponse`, `LivePlaneDTO`, `DurablePlaneDTO`, and `FreshnessEnum` in `scripts/daio_closed_loop/models.py`.
* **[M2] Status Aggregator Service**: Implement read-only `ProjectStatusService` evaluating Git and `SqliteDAIOWorkStore` with strict freshness contracts.
* **[M3] Transport Adapters**: Implement the Lead Architect–approved remote transport channel.
* **[M4] Deterministic Verification & Degraded-Mode Test Suite**: Implement `tests/test_rpc_project_status.py` verifying freshness transitions, degraded offline reporting, and domain neutrality.

---

## 10. Checkpoint Status

* **Status**: **`REVISED_PLANNING_CHECKPOINT_AWAITING_LEAD_ARCHITECT_REVIEW`**
* **Action**: **STOPPED BEFORE IMPLEMENTATION**.
