# DAIO Remote Project Cockpit (RPC) Architecture & RPC-1 Planning Checkpoint

---

## 1. Core Architectural Boundary: RPC is an Adapter Over DAIO

```text
Existing DAIO Closed Loop (Automation Control Plane)
        │
        ├── canonical state (SqliteDAIOWorkStore)
        ├── canonical decision ingestion (process_incoming_architect_decision)
        └── canonical events & watchdog (DAIOWatchdog, telemetry events)
        │
        ▼
Remote Project Cockpit (RPC Access Adapter Layer)
        │
        ├── [Capability A] Query Channel        -> RPC-1: Status & Freshness Engine
        ├── [Capability B] Decision Channel     -> Secure Remote Decision Delivery
        └── [Capability C] Notification Channel -> Event & Milestone Alerts
        │
        ▼
iPhone ChatGPT / Remote Project Owner
```

### Inviolable Architectural Principles
> [!IMPORTANT]
> **DAIO already provides the canonical automation control plane.**
> 
> Do **NOT** redesign or duplicate:
> * DAIO Orchestrator & State Machine
> * Supervisor & Worker / Antigravity execution
> * Watchdog & Recovery Epochs
> * Human Gate & Architect Decision Ingestion
> * Test Gate & Git Checkpoint / provenance mechanisms
> 
> **RPC is strictly the remote/mobile access layer** exposing selected existing DAIO capabilities safely to a remote project owner (especially via iPhone ChatGPT).
> 
> * **Prefer**: `RPC → existing DAIO API / state / event`
> * **Never**: `RPC → duplicate DAIO state machine, second task board, or parallel database`

---

## 2. The Three Core RPC Capabilities

### Capability A — Query (`RPC-1 — RPC-ProjectStatus`)
* **Mobile Query**: Project owner asks from iPhone ChatGPT:
  > **「現在專案做到哪裡了？」** 或 **「現在電腦開發到哪？」**
* **Cockpit Adapter Responsibility**:
  * Reads existing DAIO canonical state (`SqliteDAIOWorkStore` + local/remote Git environment).
  * Returns decoupled **Fresh Live Plane** (daemon activity, active work item, current gate, role) and **Durable Plane** (Git commit, verified remote GitHub SHA, push status, closed OpenSpec changes).
  * Enforces **Freshness Evaluation** (`FRESH`, `STALE`, `OFFLINE`, `UNKNOWN`) and human-action requirements.
  * **Zero parallel state**: Never create a second project-state database.

### Capability B — Remote Decision (`RPC-2 — RemoteDecisionDelivery`)
* **Trigger**: Existing DAIO enters `HUMAN_GATE_REQUIRED` (e.g., scope threshold, test gate iteration limit reached, or architectural clarification required).
* **Owner Action**: Project owner reviews gate details on iPhone ChatGPT and replies:
  > **`APPROVE`**, **`REVISE`**, or **`STOP`** (with optional structured instruction).
* **Cockpit Adapter Responsibility**:
  * Verifies remote identity, signature, and replay-protection token.
  * Translates remote response into canonical `ArchitectDecision(decision, current_phase, action, instruction)`.
  * Securely delivers decision directly into the **EXISTING DAIO Architect Decision Ingestion path** (`DAIOClosedLoopOrchestrator.process_incoming_architect_decision()`).
  * **Zero parallel gate**: DAIO's existing Human Gate state machine unlocks and Antigravity execution resumes.

### Capability C — Push / Event Notification (`RPC-3 — EventNotificationRelay`)
* **Trigger**: Existing DAIO emits canonical milestones or watchdog alerts:
  * Meaningful progress checkpoint completed
  * GitHub checkpoint completed & verified (`origin/main`)
  * Tests failed / recovery epoch initiated
  * `HUMAN_GATE_REQUIRED` entered
  * Work item completed / milestone closed
  * Agent stalled / daemon unresponsive
  * Workstation / DAIO host becoming unavailable (heartbeat timeout)
* **Cockpit Adapter Responsibility**:
  * Listens to existing DAIO event telemetry and watchdog state.
  * Relays real-time push alerts to the owner's mobile device (APNs / Webhook / Chatbot Notification).
  * **Zero duplicate watchdog**: Never create a secondary watchdog or event state machine.

---

## 3. End-to-End Acceptance Visions

### Acceptance Vision 1: Unattended Human-Gate Resolution Loop
```text
PC Antigravity (Coding Agent)
       ↓
Existing DAIO Executor & Test Gate
       ↓
HUMAN_GATE_REQUIRED
       ↓
Remote Project Cockpit (RPC Notification Channel)
       ↓
iPhone Push Notification
       ↓
Project Owner in iPhone ChatGPT:
"Approve. Continue."
       ↓
Authenticated Remote Decision Envelope
       ↓
Existing DAIO Decision Ingestion (process_incoming_architect_decision)
       ↓
Antigravity resumes execution
```

### Acceptance Vision 2: Mobile Status & Milestone Inspection
```text
Project Owner on iPhone ChatGPT:
"現在電腦開發到哪？"
       ↓
RPC Query Engine (daio.getProjectStatus)
       ├── Evaluates Live Plane (Heartbeat, PID, Active Work Item, Gate)
       ├── Evaluates Freshness (FRESH / STALE / OFFLINE / UNKNOWN)
       └── Evaluates Durable Plane (Latest verified remote GitHub SHA & OpenSpec change)
       ↓
Cockpit Response:
"📍 [Durable State]: Commit a1b2c3d verified on origin/main (Change 012 complete).
 ⚡ [Live State - FRESH]: Supervisor active (PID 91763), working on Change 013 (Auth Gateway).
 🔒 [Human Gate]: None required. Autonomous iteration in progress."
```

---

## 4. Freshness & Two-Plane Governance Invariants

```text
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

### Freshness State Machine
1. **`FRESH`** (<30s heartbeat): Live execution claims are authoritative.
2. **`STALE`** (30s–180s heartbeat): Host machine under heavy load or brief network delay; report with staleness warning.
3. **`OFFLINE`** (>180s heartbeat / daemon stopped): Host machine asleep, disconnected, or terminated.
4. **`UNKNOWN`** (DB uninitialized / unreadable): Telemetry source unverified.

> [!CRITICAL]
> **Inviolable Invariant**: A previously recorded `RUNNING` state must **NEVER** be presented as currently `RUNNING` when live heartbeat telemetry is `STALE`, `OFFLINE`, or `UNKNOWN`.
>
> **Degraded Behavior**: If the PC is asleep or offline, the response reports `live_state = OFFLINE` with the last observed heartbeat timestamp, and independently reports the last verified durable GitHub commit. GitHub is strictly a Durable Plane / fallback mechanism and must **never** be misrepresented as the Live Plane.

---

## 5. Analysis of Missing Remote-Access Infrastructure

To enable the target mobile loop without violating the DAIO boundary, three specific remote-access bridges are required:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. iPhone → DAIO Query Infrastructure                                   │
│    • Ingress path from iPhone ChatGPT (Custom GPT Action / REST endpoint)│
│    • Query Handler reading DAIO SqliteDAIOWorkStore without locks       │
│    • Two-Plane Formatter assembling Live + Durable status payload       │
│ ─────────────────────────────────────────────────────────────────────── │
│ 2. DAIO → iPhone Notification Infrastructure                            │
│    • Event Tap hooking into DAIO Event telemetry & Watchdog state       │
│    • Outbound Dispatcher transmitting high-priority alerts to mobile    │
│    • Push Service / Webhook Bridge triggering iPhone notifications      │
│ ─────────────────────────────────────────────────────────────────────── │
│ 3. iPhone → DAIO Authorized Human Gate Decision Infrastructure          │
│    • Egress / Ingress Decision Envelope with Cryptographic Signature    │
│    • Token Authentication, Replay Protection (Nonces & Expiry)          │
│    • Direct Ingestion into DAIO's process_incoming_architect_decision  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Conceptual Comparison of Candidate Architecture Families

Because developer workstations are typically behind NAT/firewalls, iPhone ChatGPT cannot connect directly to `http://localhost`. Below is a conceptual comparison of candidate transport families:

| Architecture Candidate Family | Architectural Mechanism | Primary Strength | Primary Limitation / Risk |
|---|---|---|---|
| **1. Secure Outbound Relay** | PC maintains an outbound persistent TLS connection (e.g. WebSocket / SSE client) to an authenticated cloud message broker. | 100% NAT traversal with 0 router/firewall opening; sub-second live query & instant push notifications. | Requires hosting or maintaining a lightweight relay broker. |
| **2. Authenticated Cloud Relay (Serverless)** | Serverless queue/KV store (e.g. Cloudflare Worker / AWS API Gateway + DynamoDB) holding short-lived telemetry snapshots & decision queues. | Serverless, zero persistent server maintenance, excellent scalability, and fine-grained token authentication. | Small polling latency (1–5s) unless paired with WebSockets. |
| **3. Secure Inbound Tunnel** | Encrypted tunnel forwarding public HTTPS requests to localhost (e.g. Cloudflare Tunnel, Tailscale Funnel, ngrok). | Direct REST/JSON-RPC query execution against the local DAIO daemon. | Direct inbound exposure surface; requires strict bearer token guardrails and depends on third-party daemon stability. |
| **4. Private Mesh / VPN** | Direct encrypted peer-to-peer overlay network (e.g. Tailscale / WireGuard) connecting PC and mobile device. | Enterprise-grade point-to-point encryption, zero public port exposure. | iPhone ChatGPT Web/App backend cannot join the user's private Tailscale mesh directly without intermediate gateway. |
| **5. Durable GitHub Fallback Channel** | Asynchronous telemetry dispatch via ephemeral GitHub branch (`daio-telemetry`), issue comments, or release assets. | Zero new infrastructure, zero external vendor accounts, built directly on existing GitHub auth. | 30–60s latency, rate limit budgeting; suitable for durable fallback and notifications, **not** real-time sub-second live streaming. |

---

## 7. Comprehensive 15-Criteria Evaluation Matrix

$$\text{Rating Scale: } \mathbf{5} = \text{Optimal / Native},\ \mathbf{3} = \text{Acceptable with Mitigations},\ \mathbf{1} = \text{Significant Blocker / Infeasible}$$

| # | Architectural Evaluation Criterion | 1. Outbound WebSocket Relay | 2. Serverless Cloud Relay | 3. Secure Tunnel (Cloudflare/ngrok) | 4. Private Mesh (Tailscale) | 5. Durable GitHub Fallback |
|:---:|---|:---:|:---:|:---:|:---:|:---:|
| **1** | **NAT Traversal** | 5 | 5 | 5 | 4 | 5 |
| **2** | **Zero Inbound Router Config** | 5 | 5 | 5 | 5 | 5 |
| **3** | **Authentication** (Bearer/HMAC) | 5 | 5 | 4 | 5 | 5 |
| **4** | **Authorization & RBAC** | 5 | 5 | 4 | 4 | 4 |
| **5** | **Replay Protection (Nonces/Timestamps)** | 5 | 5 | 4 | 5 | 4 |
| **6** | **Decision Integrity (Signature Verification)** | 5 | 5 | 4 | 5 | 4 |
| **7** | **Freshness Guarantees (Sub-30s)** | 5 | 4 | 5 | 5 | 2 |
| **8** | **Offline / Degraded Detection** | 5 | 5 | 3 | 3 | 4 |
| **9** | **Push Notification Capability** | 5 | 5 | 2 | 1 | 3 |
| **10** | **iPhone Usability (ChatGPT Action / Mobile)** | 5 | 5 | 4 | 2 | 4 |
| **11** | **ChatGPT Custom Action Feasibility** | 5 | 5 | 4 | 1 | 4 |
| **12** | **Operational Complexity (Setup overhead)** | 3 | 4 | 3 | 2 | 5 |
| **13** | **Secret Management (Keys/Tokens)** | 4 | 4 | 3 | 4 | 5 |
| **14** | **Auditability & Provenance Logging** | 5 | 5 | 4 | 4 | 5 |
| **15** | **Vendor Independence** | 4 | 3 | 2 | 2 | 4 |

---

## 8. Open Architecture Decision for Lead Architect Review

> [!IMPORTANT]
> **Key Architecture Question**:
> **Which transport topology should be selected for the primary iPhone $\leftrightarrow$ DAIO communication channel?**
>
> * **Option 1 (Recommended Hybrid)**:
>   * **Primary Live Channel**: Lightweight Serverless / Outbound Relay (Candidate 1/2) for live status, sub-second decision delivery, and instant push notifications.
>   * **Secondary Durable Fallback**: GitHub checkpoint verification (Candidate 5) for persistent milestone audits and offline status validation.
> * **Option 2 (Tunnel-Centric)**: Cloudflare Tunnel directly proxying a hardened local DAIO HTTP endpoint with Custom GPT Action authentication.
> * **Option 3 (GitHub-Only)**: Zero-infrastructure asynchronous GitHub Issue / Telemetry branch polling (high latency, zero hosting).

---

## 9. Checkpoint Status & Git Coordinates

* **Canonical Repository**: `huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill`
* **Status**: **`ARCHITECTURAL_BOUNDARY_ESTABLISHED_AWAITING_LEAD_ARCHITECT_REVIEW`**
* **Action**: **STOPPED BEFORE IMPLEMENTATION**.
