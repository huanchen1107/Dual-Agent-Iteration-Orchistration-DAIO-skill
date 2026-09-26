# RPC-3: iPhone Owner Cockpit MVP Architecture & UX Plan

**Protocol Version**: `daio-rpc/v3.0-draft`  
**Target Device**: Apple iPhone (Mobile Safari / iOS PWA / Standalone Web App)  
**Upstream Repository**: `Dual-Agent-Iteration-Orchistration-DAIO-skill`  
**Downstream Consumer**: `_AwinFinTechHybridSystem_`  
**Status**: `RPC-3A Architecture & UX Planning`  

---

## 1. Executive Summary & Objective

The primary objective of **RPC-3 (iPhone Owner Cockpit MVP)** is to empower the Project Owner to monitor and govern the entire DAIO autonomous loop using **only an iPhone**:

$$\text{Look at Status} \longrightarrow \text{Inspect Active Work} \longrightarrow \text{Detect Human Gate} \longrightarrow \text{APPROVE / REVISE / STOP} \longrightarrow \text{Mac DAIO Atomic Commit} \longrightarrow \text{Antigravity Resumes} \longrightarrow \text{iPhone Observes Progress}$$

### The 5-Second Rule (iPhone-First UX)
The Project Owner opening the iPhone cockpit must be able to answer **4 key questions within 5 seconds**:
1. **Which Project?** $\rightarrow$ e.g., `AwinFinTechHybridSystem` (`main`)
2. **Is it Alive?** $\rightarrow$ `ONLINE / FRESH` (Mac Host, PID, Heartbeat age)
3. **What is it doing right now?** $\rightarrow$ Work ID, Change ID, Stage, Gate, Role, Git SHA
4. **Is any action required from me?** $\rightarrow$
   - If autonomous: `🟢 No action required. DAIO is operating autonomously.`
   - If Human Gate: `🔴 HUMAN DECISION REQUIRED` with clear reason, context, and immediate action buttons (`APPROVE`, `REVISE`, `STOP`).

---

## 2. End-to-End System Architecture

```mermaid
flowchart TD
    subgraph Owner_Device [Owner iPhone - Mobile Safari / iOS PWA]
        CockpitUI["iPhone Cockpit UI (Single-Page App)"]
        LocalStorage[("localStorage: DAIO_RELAY_SECRET")]
        CockpitUI <--> LocalStorage
    end

    subgraph Cloudflare_Edge [Cloudflare Unified Relay: daio-relay.huanchen1107.workers.dev]
        WorkerRoutes["Cloudflare Worker (relay_worker.js)"]
        UI_Endpoint["GET /cockpit (Static HTML/CSS/JS)"]
        Status_KV[("STATUS_KV (status:latest)")]
        Decision_KV[("DECISION_KV (decision:project:id)")]
        
        WorkerRoutes --- UI_Endpoint
        WorkerRoutes <--> Status_KV
        WorkerRoutes <--> Decision_KV
    end

    subgraph Mac_Host [Local Mac DAIO Execution Host (Outbound-Only)]
        StatusPublisher["RPC-1 Status Publisher (Outbound Push)"]
        DecisionPoller["RPC-2 Remote Decision Adapter (Outbound Poll)"]
        Orchestrator["DAIOClosedLoopOrchestrator"]
        Store["SqliteDAIOWorkStore (BEGIN IMMEDIATE)"]
        Agent["Antigravity Execution Agent"]
        GitRepo[("Local Git Repository")]
        
        StatusPublisher -->|POST /api/v1/publish| WorkerRoutes
        DecisionPoller -->|GET /api/v1/decisions| WorkerRoutes
        DecisionPoller -->|POST /api/v1/decisions/:id/ack| WorkerRoutes
        
        DecisionPoller --> Orchestrator
        Orchestrator --> Store
        Orchestrator --> Agent
        Agent --> GitRepo
    end

    CockpitUI -->|1. Polling: GET /api/v1/status| WorkerRoutes
    CockpitUI -->|2. Ingress: POST /api/v1/decisions| WorkerRoutes
```

---

## 3. Five-Zone iPhone Screen Layout & Wireframe

### Mobile Safari Viewport Layout (390px $\times$ 844px)

```
┌────────────────────────────────────────────────────────┐
│  DAIO COCKPIT                           [ ⚙️ Settings ] │
├────────────────────────────────────────────────────────┤
│ ① PROJECT                                              │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 📁 AwinFinTechHybridSystem                         │ │
│ │ 🌿 main (HEAD 71c722e)    [ ✓ Push Synced ]        │ │
│ └────────────────────────────────────────────────────┘ │
│                                                        │
│ ② LIVE STATUS                                          │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 🟢 ONLINE  •  FRESH (1.8s ago)                     │ │
│ │ 🖥️ Mac Host: huanchen-mac  •  PID: 45123 (Running) │ │
│ │ ⏱️ Last Report: 2026-09-26 20:00:15 UTC             │ │
│ └────────────────────────────────────────────────────┘ │
│                                                        │
│ ③ CURRENT WORK                                         │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 🏷️ Work ID: daio-1327528c                          │ │
│ │ 📝 Change: smc-orderbook-v1                         │ │
│ │ 📊 Stage: S3_EXECUTION  •  Gate: HUMAN_GATE         │ │
│ │ 👤 Assigned: HUMAN_PROJECT_OWNER                   │ │
│ │ 📌 Status: HUMAN_GATE_REQUIRED                     │ │
│ └────────────────────────────────────────────────────┘ │
│                                                        │
│ ④ HUMAN ACTION                                         │
│ ┌────────────────────────────────────────────────────┐ │
│ │ ⚠️ HUMAN DECISION REQUIRED                          │ │
│ │ "Execution completed, awaiting Owner authorization" │ │
│ │                                                    │ │
│ │ [   ✅ APPROVE   ]   [   🔄 REVISE   ]             │ │
│ │                                                    │ │
│ │ [              🛑 STOP LOOP             ]           │ │
│ └────────────────────────────────────────────────────┘ │
│                                                        │
│ ⑤ TIMELINE / AUDIT TRAIL                               │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 1. 20:00:15 - iPhone Decision [APPROVE] Submitted   │ │
│ │ 2. 20:00:16 - Cloudflare KV Buffered                │ │
│ │ 3. 20:00:18 - Mac Polled & Verified Live State      │ │
│ │ 4. 20:00:18 - SQLite Atomically Applied (0.012s)   │ │
│ │ 5. 20:00:19 - Antigravity Resumed Next Phase        │ │
│ └────────────────────────────────────────────────────┘ │
│                                                        │
│ 🔄 Auto-refreshing in 3s...            [ Manual Pull ] │
└────────────────────────────────────────────────────────┘
```

### Dynamic State Switching for Zone ④ (Human Action)

- **State A: Normal Autonomous Operation**
  ```
  ┌────────────────────────────────────────────────────┐
  │ 🟢 No Action Required                              │
  │ DAIO is operating autonomously in S2_CONTRACT.     │
  └────────────────────────────────────────────────────┘
  (Decision buttons are completely hidden)
  ```

- **State B: Human Gate Active**
  ```
  ┌────────────────────────────────────────────────────┐
  │ 🔴 HUMAN DECISION REQUIRED                         │
  │ Reason: Structural contract upgrade needs Owner signoff
  │                                                    │
  │ [ ✅ APPROVE ]   [ 🔄 REVISE ]   [ 🛑 STOP ]       │
  └────────────────────────────────────────────────────┘
  (Tapping APPROVE brings up 1-tap confirmation modal)
  (Tapping REVISE opens inline text feedback input)
  ```

---

## 4. Existing API Reuse Matrix

| Endpoint | Method | Role in RPC-3 iPhone Cockpit | Auth / Headers | Status |
| :--- | :---: | :--- | :--- | :--- |
| `GET /api/v1/status` | `GET` | Powers Zones ①, ②, ③, ④ status detection. Polled every 3–5 seconds. | None (Public read) | **100% Reused** (No changes needed) |
| `GET /api/v1/health` | `GET` | Health indicator & Cloudflare Edge latency badge. | None | **100% Reused** |
| `POST /api/v1/decisions` | `POST` | Submits Owner decisions (`APPROVE`, `REVISE`, `STOP`) directly from iPhone. | `Authorization: Bearer <SECRET>` | **100% Reused** (RPC-2A contract) |
| `GET /api/v1/decisions` | `GET` | Mac Outbound Poller queries pending buffer. | `Authorization: Bearer <SECRET>` | **100% Reused** |
| `POST /api/v1/decisions/{id}/ack` | `POST` | Mac Outbound Poller ACKs after SQLite commit. | `Authorization: Bearer <SECRET>` | **100% Reused** |
| `GET /cockpit` (or `GET /`) | `GET` | Serves the single-file iPhone Cockpit HTML/CSS/JS web application directly from Cloudflare Worker edge. | None (HTML content negotiation) | **New entrypoint in `relay_worker.js`** |

---

## 5. Missing API / Schema Gap Analysis

### Gap Analysis Result: **ZERO Core Backend API Gaps**
1. **Status Schema**: `LivePlaneStatus` and `DurablePlaneStatus` already export all necessary telemetry:
   - `project_name`, `host`, `host_status`, `freshness`, `supervisor_running`, `supervisor_pid`, `heartbeat_age_seconds`
   - `active_work_id`, `active_work_item`, `current_phase`, `current_gate`, `assigned_role`, `human_gate_required`, `human_gate_reason`
   - `repository`, `git_branch`, `local_head_sha`, `remote_origin_sha`, `push_synchronized`
2. **Decision Schema**: `RemoteDecisionEnvelope` accepts `decision`, `action`, `instruction`, `work_id`, `project_id`, `gate_id`.
3. **Identified Front-End Serving Addition**:
   - Add a route `GET /cockpit` (and browser fallback for `GET /`) in `cloudflare/relay_worker.js` returning the bundled, zero-dependency, mobile-optimized HTML/CSS/JS UI.

---

## 6. Security & Invariant Boundary Analysis

1. **Mac Zero Inbound Ports**: The Mac host never accepts incoming connections. The iPhone never connects to the Mac directly. All interactions mediate through Cloudflare Edge.
2. **Privilege Separation**:
   - Status telemetry read: Unauthenticated or scoped.
   - Decision submission: Protected by `DAIO_RELAY_SECRET`. Secret is stored only in the iPhone's `localStorage` (client-side) and never embedded in Git or code.
3. **Fail-Closed & Atomic Ingestion**:
   - The UI does not touch SQLite.
   - When the Owner taps `APPROVE`, an envelope is buffered in `DECISION_KV`.
   - Mac poller reads the decision, invokes `DAIOClosedLoopOrchestrator.process_incoming_architect_decision()`, and executes `apply_decision_transition_atomically()` inside a single SQLite `BEGIN IMMEDIATE` transaction.
   - If the local state changed during transmission (TOCTOU), the transaction aborts with zero mutation.
4. **Replay & Crash Protection**:
   - Deduplicated by `decision_id` in `daio_decision_ledger`.

---

## 7. Implementation Roadmap & Phases

```
┌────────────────────────────────────────────────────────────────────────┐
│ Phase RPC-3A: Architecture & UX Planning (CURRENT PHASE)              │
│ - Finalize UI design, 5 zones, API reuse matrix, security invariants.  │
├────────────────────────────────────────────────────────────────────────┤
│ Phase RPC-3B: Read-Only iPhone Cockpit                                │
│ - Implement mobile web UI in generic DAIO repository.                  │
│ - Serve UI at `GET /cockpit` from Cloudflare Worker.                  │
│ - Render live status, project telemetry, heartbeat, and current work.  │
├────────────────────────────────────────────────────────────────────────┤
│ Phase RPC-3C: Human Gate Decision Controls                            │
│ - Implement interactive action buttons (`APPROVE`, `REVISE`, `STOP`).   │
│ - Secure credential vault in client `localStorage`.                   │
│ - Submit authenticated decision envelopes to `/api/v1/decisions`.     │
│ - Display real-time execution timeline and audit trail.               │
├────────────────────────────────────────────────────────────────────────┤
│ Phase RPC-3D: Real iPhone End-to-End Controlled Acceptance             │
│ - Test on real iOS Mobile Safari via Cloudflare edge URL.             │
│ - Execute controlled test item through iPhone decision $\to$ Mac apply.│
├────────────────────────────────────────────────────────────────────────┤
│ Phase RPC-3 PASS: Skill & Downstream Project Synchronization          │
│ - Push generic DAIO repo $\to$ sync installed skill $\to$ verify Awin. │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Acceptance Criteria for RPC-3

1. **iPhone Usability**:
   - Loads in under 1 second on mobile Safari (`daio-relay.huanchen1107.workers.dev/cockpit`).
   - Clean dark-mode UI with high contrast, responsive touch targets ($\ge 44\text{px}$).
   - Accurately conveys all 4 key questions in $\le 5$ seconds.
2. **Read-Only Telemetry**:
   - Status refreshes automatically without page reload.
   - Displays real freshness (`FRESH` / `STALE` / `OFFLINE`) and Git synchronization status.
3. **Action Gating**:
   - Decision controls appear **strictly** when `HUMAN_GATE_REQUIRED` is true.
   - Disappears immediately upon state transition.
4. **Transaction & Security Integrity**:
   - Outbound-only Mac polling.
   - Zero SQLite direct connections from client.
   - Atomic SQLite transition on host.
