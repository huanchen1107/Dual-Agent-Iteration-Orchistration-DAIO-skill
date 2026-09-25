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
  * Relays real-time push alerts to the owner's mobile device (APNs / Push Webhook / Chatbot Notification).
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
iPhone Push Notification (NTFY / Telegram / Pushover)
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

## 5. RPC Transport Architecture Decision (ADR-RPC-TRANSPORT-001)

### Architecture Decision Record: ADR-RPC-TRANSPORT-001

* **Status**: **APPROVED BY LEAD ARCHITECT (Implementation Scope: PoC-0 Authorization Only)**
* **Context**: The developer workstation (Mac/PC) runs DAIO and Antigravity behind domestic/corporate NAT and firewalls. The project owner needs secure status queries, instant push notifications, and human gate decision delivery from iPhone ChatGPT without exposing local ports directly to the public internet.
* **Decision**: Adopt a **Lightweight Serverless Cloud Relay (Cloudflare Worker with Outbound WebSocket Hibernation & Push Webhook Dispatch)** as the primary Live Plane communication topology, with **GitHub** serving as the independent Durable Plane / audit fallback.
* **Integration Surface Principle**: Do not hardcode vendor-specific assumptions (e.g. OpenAI Plus/Team Custom Action only). Support standard HTTPS REST OpenAPI 3.1 compatible with ChatGPT Projects, Plugins, Custom GPT Actions, and Web Tools.


```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                              DEPLOYMENT TOPOLOGY                             │
└──────────────────────────────────────────────────────────────────────────────┘

               ┌────────────────────────┐
               │     iPhone Owner       │
               │   (ChatGPT / Push)     │
               └───────┬────────▲───────┘
                       │        │ (Channel C: Push Notification)
               HTTPS   │        │ [NTFY / Telegram / Pushover]
               OpenAPI │        │       ▲
               Action  ▼        │       │ Outbound Webhook
       ┌────────────────┴───────┴──────────────────────────────┐
       │  Cloudflare Worker + Durable Object (Cloud Relay)    │
       │  • /api/v1/status     [HTTPS GET  <- ChatGPT Action]  │
       │  • /api/v1/decision   [HTTPS POST <- ChatGPT Action]  │
       │  • /ws/daio-node      [WSS Ingress <- PC DAIO Daemon] │
       │  • Memory/DO Snapshot (Cached Live State + Freshness) │
       │  • Outbound Alert Dispatcher (Webhook to Push Gateway)│
       └────────────────────────▲──────────────────────────────┘
                                │
                                │ Outbound TLS WebSocket (WSS)
                                │ (Zero inbound firewall / NAT opening)
                                │
       ┌────────────────────────┴──────────────────────────────┐
       │  Developer Workstation (Mac / PC Behind NAT)          │
       │  ┌──────────────────────────────────────────────────┐ │
       │  │ DAIO RPC Agent Adapter (Outbound Client Daemon)  │ │
       │  │ • Maintains persistent WSS to Cloud Relay        │ │
       │  │ • Emits live heartbeat + work state every 15s    │ │
       │  │ • Receives signed decisions -> HMAC verify       │ │
       │  │ • Ingests decision -> DAIO Control Plane         │ │
       │  └───────────────────┬──────────────────────────────┘ │
       │                      │ Canonical API / Local SQLite   │
       │  ┌───────────────────▼──────────────────────────────┐ │
       │  │ Existing DAIO Control Plane                      │ │
       │  │ • Orchestrator / Supervisor / Worker / Gate      │ │
       │  │ • process_incoming_architect_decision()          │ │
       │  └───────────────────┬──────────────────────────────┘ │
       │                      │ Execution Loop                 │
       │  ┌───────────────────▼──────────────────────────────┐ │
       │  │ Antigravity Coding Agent                         │ │
       │  └──────────────────────────────────────────────────┘ │
       └───────────────────────────────────────────────────────┘
                                │
                                │ Git Commit / Push (Verified Provenance)
                                ▼
       ┌───────────────────────────────────────────────────────┐
       │  GitHub Repository (Durable Plane & Audit Fallback)   │
       │  • origin/main (Verified commits)                     │
       │  • OpenSpec Specifications & Change History           │
       └───────────────────────────────────────────────────────┘
```

---

### Detailed Analysis of the 15 Architectural Dimensions

#### 1. Candidate Technologies Considered
* **Candidate A (Selected)**: Cloudflare Worker + Durable Objects / WebSocket Hibernation API.
* **Candidate B**: AWS API Gateway (WebSocket + HTTP) + Lambda + DynamoDB.
* **Candidate C**: Dedicated VPS / Container Relay (Go/FastAPI on Fly.io).
* **Candidate D**: Inbound Cloudflare Tunnel / ngrok directly to localhost.
* **Candidate E**: Pure GitHub Issue / Telemetry Polling (Durable fallback only).

#### 2. Real Deployment Topology
* **Edge Cloud**: A single Cloudflare Worker script deployed on edge with a Durable Object holding the live WebSocket connection from the developer's PC.
* **Workstation**: A background asyncio/thread WebSocket client embedded in the DAIO Supervisor process.
* **Mobile**: Custom GPT Action configured in ChatGPT iOS app pointing to the Worker's HTTPS endpoints, coupled with a push notification webhook bridge.

#### 3. iPhone → Relay → DAIO Query Flow (Channel A)
1. Owner in iPhone ChatGPT asks: *「現在專案做到哪裡了？」*
2. ChatGPT executes Custom GPT Action: `GET /api/v1/status` with `Authorization: Bearer <CHATGPT_TOKEN>`.
3. Cloudflare Worker checks the active WebSocket session:
   - If connected and heartbeat is recent ($\le 30\text{s}$): Returns `FRESH` live telemetry snapshot.
   - If heartbeat is delayed ($30\text{s} - 180\text{s}$): Returns `STALE` live telemetry with timestamp.
   - If disconnected or $>180\text{s}$: Returns `OFFLINE` status immediately.
4. Worker returns JSON payload combining **Live Plane** (supervisor PID, active work item, gate, role) and **Durable Plane** (last verified GitHub SHA, push status, latest OpenSpec change).
5. ChatGPT renders a natural language summary to the owner.

#### 4. DAIO → Relay → iPhone Notification Flow (Channel C)
1. DAIO encounters an event requiring attention (`HUMAN_GATE_REQUIRED`, `TEST_GATE_FAILED`, `WORK_ITEM_COMPLETED`, `GITHUB_CHECKPOINT_COMPLETED`, `DAEMON_STALLED`).
2. DAIO RPC adapter pushes the event envelope over the persistent outbound WSS connection to the Cloud Relay.
3. Cloud Relay invokes an outbound Webhook to a mobile push gateway (e.g., NTFY.sh, Pushover, or Telegram Bot API).
4. iPhone displays a real-time lock-screen push banner:
   > 🔔 **DAIO Human Gate Alert**: Scope verification limit reached on Change 013. Open ChatGPT to review and respond.
5. Project owner taps notification or opens ChatGPT to review context and issue decisions.

#### 5. iPhone → Relay → DAIO Human Gate Decision Flow (Channel B)
1. Project owner replies in ChatGPT: *"Approve. Continue with next phase."*
2. ChatGPT executes Custom GPT Action: `POST /api/v1/decision` with payload:
   ```json
   {
     "decision": "APPROVE",
     "action": "ACCEPT",
     "instruction": "Continue with next phase.",
     "gate_id": "gate_ch013_001",
     "nonce": "nonce_7a8f9b2c",
     "timestamp": 1727258400
   }
   ```
3. Cloud Relay verifies bearer token, validates timestamp freshness ($\le 60\text{s}$), and checks nonce uniqueness.
4. Cloud Relay delivers the decision envelope over the active WebSocket channel to the PC DAIO daemon.
5. PC DAIO adapter verifies HMAC signature, validates gate state, and invokes:
   `DAIOClosedLoopOrchestrator.process_incoming_architect_decision(decision)`
6. Existing DAIO state machine unlocks, updates local SQLite store, logs provenance, and Antigravity execution resumes.

#### 6. Authentication & Authorization Model
* **ChatGPT ↔ Cloud Relay**: Authenticated via standard `Bearer <CHATGPT_ACCESS_TOKEN>` set in the Custom GPT Action configuration.
* **PC DAIO ↔ Cloud Relay**: Authenticated via mutual TLS / Pre-Shared Secret Token (`DAIO_NODE_TOKEN`) during WebSocket handshake.
* **Decision Signature & Nonce**: Remote decisions include an HMAC-SHA256 signature calculated over `(gate_id, decision, nonce, timestamp)` ensuring decision integrity and non-repudiation.
* **Role-Based Access Control (RBAC)**: Remote API is strictly restricted to:
  * `read:status` (Read-only status inspection)
  * `write:decision` (Constrained decision values: `APPROVE`, `REVISE`, `STOP`).
  * **No remote shell execution or file editing endpoints exist.**

#### 7. Freshness & Offline Model
* Live Heartbeat Interval: **15 seconds**.
* Freshness Boundaries:
  * `FRESH`: Heartbeat age $\le 30\text{s}$
  * `STALE`: Heartbeat age $30\text{s} < \Delta t \le 180\text{s}$
  * `OFFLINE`: Heartbeat age $> 180\text{s}$ or TCP session terminated.
* Fail-Closed Invariant: Cloud Relay will never report `RUNNING` if the WebSocket connection is severed or heartbeat age $>180\text{s}$.

#### 8. Failure & Degraded Modes
* **PC Asleep / Power Off / Network Disconnected**: Cloud Relay serves cached `OFFLINE` status + last verified durable GitHub commit SHA.
* **Relay Service Outage**: DAIO continues local autonomous execution uninterrupted. Human gates pause locally and wait for manual CLI resolution.
* **Replay Attack / Stale Message**: Cloud Relay and PC DAIO enforce a strict 60-second validity window and deduplicate nonces in a memory cache.
* **GitHub Rate Limit / Outage**: Local Git environment remains primary; remote GitHub verification operates with exponential backoff.

#### 9. Operational Complexity
* **Zero Host Server Maintenance**: Cloudflare Workers run serverless with automatic scaling, zero OS patching, and global edge routing.
* **Zero Workstation Port Forwarding**: Pure outbound connection initiated from the PC.
* **Setup Overhead**: Under 15 minutes to configure Worker + OpenAI Action.

#### 10. Estimated External Services & Accounts Required
1. **Cloudflare Account** (Free tier covers 100k requests/day and WebSocket hibernation).
2. **OpenAI ChatGPT Plus / Team Account** (Required for Custom GPT Actions).
3. **Mobile Push Service** (Free tier NTFY.sh / Pushover / Telegram Bot Webhook).
4. **GitHub Account** (Existing project repository for Durable Plane).

#### 11. Security Risks & Mitigations

| Threat Vector | Severity | Mitigating Architectural Control |
|---|:---:|---|
| **Public Ingress Attack on Workstation** | High | **Eliminated**: Workstation opens **zero inbound ports**. All connections are outbound TLS WebSockets. |
| **Unauthorized Remote Decision Ingestion** | High | **Bearer token + HMAC signature + Nonce + 60s expiration**. Replays and forged tokens rejected at relay. |
| **Command Injection / Scope Creep** | Critical | **Strict Schema Enforcement**: Remote decision endpoint only accepts enum `APPROVE`/`REVISE`/`STOP` and string instructions. No shell execution. |
| **False Execution State Claims** | Medium | **Two-Plane Freshness Engine**: Disconnected status returns `OFFLINE` with durable Git fallback. |
| **Secret Leaks** | Medium | Workstation secrets stay in local environment; Cloudflare secrets stored in encrypted Worker Secrets (`wrangler secret`). |

#### 12. Recommended Technology Stack
* **Cloud Relay**: Cloudflare Worker (TypeScript) with Durable Object & WebSocket Hibernation.
* **Mobile Ingress**: Custom GPT Action with OpenAPI 3.1 specification.
* **Mobile Push Gateway**: NTFY / Telegram Bot Webhook / Pushover.
* **Workstation Adapter**: Python `asyncio` / `websockets` outbound client in `scripts/daio_closed_loop/adapters/rpc_relay_adapter.py`.
* **Durable Plane**: Git CLI + GitHub REST API.

#### 13. Alternatives Rejected and Why
* **Inbound Cloudflare Tunnel / ngrok**: Rejected because it requires exposing an ingress port on localhost, lacks serverless message buffering when PC is offline, and increases workstation exposure.
* **AWS API Gateway + Lambda**: Rejected due to high configuration friction (IAM policies, VPCs, cold starts) compared to single-command Cloudflare Worker deployment.
* **Tailscale Private Mesh**: Rejected because iPhone ChatGPT cloud servers cannot join private peer-to-peer Tailscale overlay networks without an intermediate public gateway.
* **Pure GitHub-Only Transport**: Rejected as primary Live Plane due to 30–60s polling latency and rate limits; retained strictly as Durable Plane / audit fallback.

#### 14. Minimal Proof-of-Concept Roadmap
* **[PoC-0 — Remote Reachability (CURRENT FOCUS)]**: Stand up Cloudflare Worker with mock JSON status. Connect iPhone ChatGPT and verify natural-language status query (*「DAIO 現在狀態？」*). See [`_myplan/POC_0_REMOTE_REACHABILITY_PLAN.md`](file:///Users/huanchen/.gemini/antigravity-ide/brain/6c38cf78-aa72-4a88-bfbd-8236872d54ba/scratch/Dual-Agent-Iteration-Orchistration-DAIO-skill/_myplan/POC_0_REMOTE_REACHABILITY_PLAN.md).
* **[PoC-1 — Outbound WSS Sync]**: Run local workstation Python client emitting real-time heartbeat to Worker; verify instant online/offline freshness transition.
* **[PoC-2 — Live DAIO Status Query]**: Query **real** workstation DAIO status from iPhone ChatGPT in real time.
* **[PoC-3 — Human Gate Decision Delivery]**: Trigger `HUMAN_GATE_REQUIRED` locally; respond `APPROVE` from iPhone ChatGPT; verify delivery into DAIO `process_incoming_architect_decision()`.
* **[PoC-4 — Push Alert Dispatch]**: Trigger milestone event on PC; verify instant lock-screen push notification on iPhone via Webhook.

#### 15. Implementation Boundary for Future OpenSpec Change
* **Confined Modules**:
  * `scripts/daio_closed_loop/adapters/rpc/` (New outbound relay adapter and status aggregator).
  * `scripts/daio_closed_loop/models.py` (Add `LivePlaneDTO`, `DurablePlaneDTO`, `CockpitStatusResponse`, `FreshnessEnum`).
  * `_myplan/` (Architecture, PoC artifacts, and test plans).
* **Strict Non-Interference**: Zero modification to DAIO state machine, watchdog, recovery epochs, test gates, supervisor core, or downstream business logic.

---

## 6. Checkpoint Status & Git Coordinates

* **Canonical Repository**: `huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill`
* **Status**: **`POC_0_PLAN_ESTABLISHED_READY_FOR_VERIFICATION`**
* **Action**: **PoC-0 Artifacts Provided, Awaiting Owner Reachability Test**.

