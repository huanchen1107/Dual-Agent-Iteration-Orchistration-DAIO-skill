# PoC-0: Remote Reachability Implementation Plan & Experiment Guide

---

## 1. PoC-0 Objective & Acceptance Standard

* **Goal**: Establish the initial vertical connectivity slice from **iPhone ChatGPT** to the **Cloudflare Relay**, verifying remote reachability and structured status parsing before connecting local workstation daemons.
* **Single Acceptance Standard**:
  > **The project owner opens ChatGPT on iPhone, asks *「DAIO 現在狀態？」*, and ChatGPT successfully queries the Cloudflare Relay endpoint and responds with structured Live Plane + Durable Plane status.**

```text
┌────────────────────────┐
│     iPhone Owner       │
│   (ChatGPT / Mobile)   │
└───────────┬────────────┘
            │ 1. "DAIO 現在狀態？"
            │ 2. HTTPS GET /api/v1/status (OpenAPI Action / Tool)
            ▼
┌────────────────────────────────────────────────────────┐
│      Cloudflare Relay Worker (Serverless Edge)         │
│      • /api/v1/status  -> Returns Mock DAIO Payload    │
│      • /openapi.json   -> Provides OpenAPI 3.1 Schema  │
│      • /health         -> Mobile Browser Health Check  │
└────────────────────────────────────────────────────────┘
            │
            │ Returns Canonical Two-Plane Mock Status:
            │ • Live Plane (FRESH, PID, Work Item, Gate)
            │ • Durable Plane (Repo, Commit SHA, Push Sync)
            ▼
┌────────────────────────┐
│     iPhone Owner       │
│   (ChatGPT / Mobile)   │
│                        │
│ "DAIO 目前處於 FRESH   │
│  狀態，正進行 Change   │
│  013，已同步至 664a05e"│
└────────────────────────┘
```

---

## 2. Canonical PoC-0 Mock Data Contract

The Cloudflare Relay returns the canonical DAIO Two-Plane schema:

```json
{
  "live_plane": {
    "freshness": "FRESH",
    "host": "mac-developer-workstation",
    "supervisor_status": "RUNNING",
    "supervisor_pid": 91763,
    "active_work_item": "Change 013 (Auth Gateway)",
    "current_gate": "AUTONOMOUS_ROUND_1",
    "current_role": "Antigravity",
    "human_gate_required": false,
    "heartbeat_age_seconds": 4,
    "last_heartbeat_timestamp": "2026-09-25T12:20:00Z"
  },
  "durable_plane": {
    "repository": "huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill",
    "verified_git_sha": "664a05eb094ff5274d5e8a3cf6b2cf3d890f47a3",
    "git_branch": "main",
    "push_synchronized": true,
    "working_tree_clean": true,
    "latest_completed_change": "Change 012"
  },
  "provenance": {
    "protocol_version": "daio-rpc/v1",
    "relay_node": "cloudflare-edge-poc0",
    "server_timestamp": "2026-09-25T12:20:04Z"
  }
}
```

---

## 3. Cloudflare Worker Implementation (`poc0_worker.js`)

Zero external dependencies. Can be copy-pasted directly into the Cloudflare Dashboard Workers Editor or deployed via Wrangler.

```javascript
/**
 * DAIO Remote Project Cockpit (RPC) - PoC-0 Cloud Relay Worker
 * Protocol: daio-rpc/v1 (Mock Reachability Test)
 */

const MOCK_STATUS_PAYLOAD = {
  live_plane: {
    freshness: "FRESH",
    host: "mac-developer-workstation",
    supervisor_status: "RUNNING",
    supervisor_pid: 91763,
    active_work_item: "Change 013 (Auth Gateway)",
    current_gate: "AUTONOMOUS_ROUND_1",
    current_role: "Antigravity",
    human_gate_required: false,
    heartbeat_age_seconds: 4,
    last_heartbeat_timestamp: new Date().toISOString()
  },
  durable_plane: {
    repository: "huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill",
    verified_git_sha: "664a05eb094ff5274d5e8a3cf6b2cf3d890f47a3",
    git_branch: "main",
    push_synchronized: true,
    working_tree_clean: true,
    latest_completed_change: "Change 012"
  },
  provenance: {
    protocol_version: "daio-rpc/v1",
    relay_node: "cloudflare-edge-poc0",
    server_timestamp: new Date().toISOString()
  }
};

const OPENAPI_SPEC = {
  openapi: "3.1.0",
  info: {
    title: "DAIO Remote Project Cockpit API",
    description: "Remote access adapter for DAIO closed-loop automation control plane.",
    version: "1.0.0"
  },
  servers: [
    {
      url: "https://daio-relay.YOUR_SUBDOMAIN.workers.dev",
      description: "Cloudflare Relay Edge Endpoint"
    }
  ],
  paths: {
    "/api/v1/status": {
      get: {
        operationId: "getDAIOProjectStatus",
        summary: "Get current DAIO live and durable project status",
        description: "Returns live plane execution telemetry and durable plane Git provenance.",
        responses: {
          "200": {
            description: "Successful response containing two-plane status",
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    live_plane: { type: "object" },
                    durable_plane: { type: "object" },
                    provenance: { type: "object" }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
      "Content-Type": "application/json; charset=utf-8"
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    if (url.pathname === "/api/v1/status") {
      const responsePayload = {
        ...MOCK_STATUS_PAYLOAD,
        provenance: {
          ...MOCK_STATUS_PAYLOAD.provenance,
          server_timestamp: new Date().toISOString()
        }
      };
      return new Response(JSON.stringify(responsePayload, null, 2), {
        status: 200,
        headers: corsHeaders
      });
    }

    if (url.pathname === "/openapi.json") {
      const dynamicSpec = {
        ...OPENAPI_SPEC,
        servers: [{ url: url.origin, description: "Active Edge Endpoint" }]
      };
      return new Response(JSON.stringify(dynamicSpec, null, 2), {
        status: 200,
        headers: corsHeaders
      });
    }

    // Health check & browser landing
    return new Response(
      JSON.stringify(
        {
          status: "OK",
          message: "DAIO Remote Project Cockpit (RPC) Cloud Relay is active.",
          endpoints: {
            status: `${url.origin}/api/v1/status`,
            openapi: `${url.origin}/openapi.json`
          }
        },
        null,
        2
      ),
      { status: 200, headers: corsHeaders }
    );
  }
};
```

---

## 4. OpenAPI 3.1 Action Specification for ChatGPT

To connect ChatGPT (via Custom GPT Action, ChatGPT Project Tool, or Plugin) copy this specification into ChatGPT:

```yaml
openapi: 3.1.0
info:
  title: DAIO Remote Project Cockpit API
  description: Remote access adapter for querying DAIO live and durable project status.
  version: 1.0.0
servers:
  - url: https://daio-relay.YOUR_SUBDOMAIN.workers.dev
paths:
  /api/v1/status:
    get:
      operationId: getDAIOProjectStatus
      summary: Retrieve current DAIO Live and Durable status
      description: Returns decoupled live execution plane (freshness, supervisor, gate) and durable plane (git commit, verified SHA).
      responses:
        '200':
          description: Successful status payload
          content:
            application/json:
              schema:
                type: object
                properties:
                  live_plane:
                    type: object
                    properties:
                      freshness:
                        type: string
                        example: FRESH
                      host:
                        type: string
                        example: mac-developer-workstation
                      supervisor_status:
                        type: string
                        example: RUNNING
                      supervisor_pid:
                        type: integer
                        example: 91763
                      active_work_item:
                        type: string
                        example: Change 013 (Auth Gateway)
                      current_gate:
                        type: string
                        example: AUTONOMOUS_ROUND_1
                      current_role:
                        type: string
                        example: Antigravity
                      human_gate_required:
                        type: boolean
                        example: false
                      heartbeat_age_seconds:
                        type: integer
                        example: 4
                  durable_plane:
                    type: object
                    properties:
                      repository:
                        type: string
                        example: huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill
                      verified_git_sha:
                        type: string
                        example: 664a05eb094ff5274d5e8a3cf6b2cf3d890f47a3
                      push_synchronized:
                        type: boolean
                        example: true
                      latest_completed_change:
                        type: string
                        example: Change 012
```

---

## 5. Step-by-Step 5-Minute Verification Walkthrough

### Step 1: Deploy Worker on Cloudflare (Zero Terminal Install Required)
1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com/) $\rightarrow$ **Compute (Workers & Pages)**.
2. Click **Create Application** $\rightarrow$ **Create Worker** $\rightarrow$ Name it `daio-relay` $\rightarrow$ Click **Deploy**.
3. Click **Edit code** (in-browser editor).
4. Replace the sample code with [`_myplan/poc0/poc0_worker.js`](file:///Users/huanchen/.gemini/antigravity-ide/brain/6c38cf78-aa72-4a88-bfbd-8236872d54ba/scratch/Dual-Agent-Iteration-Orchistration-DAIO-skill/_myplan/poc0/poc0_worker.js).
5. Click **Save and Deploy**. Copy your worker URL (e.g., `https://daio-relay.<your-name>.workers.dev`).

### Step 2: Validate via iPhone Safari
1. On your iPhone, open `https://daio-relay.<your-name>.workers.dev/api/v1/status`.
2. Confirm the JSON returns `live_plane` (status: `FRESH`) and `durable_plane` (git_sha: `664a05e`).

### Step 3: Configure ChatGPT Integration
1. In ChatGPT (GPT Builder or Custom Action settings):
   * Add Action $\rightarrow$ Import OpenAPI Schema $\rightarrow$ Paste the YAML / JSON above (replace `url` with your Worker URL).
   * Authentication: None (for PoC-0 initial reachability test).
2. Save GPT.

### Step 4: Execute iPhone Mobile Prompt
1. Open the configured ChatGPT chat on your iPhone.
2. Type:
   > **「DAIO 現在狀態？」** 或 **「現在電腦開發到哪？」**
3. ChatGPT invokes `getDAIOProjectStatus` and replies:
   > *「目前 DAIO 狀態為 **FRESH**，由 Antigravity 執行中（Supervisor PID 91763），正在進行 Change 013 (Auth Gateway)。Git 遠端已同步至 `664a05e`，上一完成變更為 Change 012。」*

---

## 6. Next Milestones (Post PoC-0 Approval)

* **PoC-1**: Mac DAIO $\rightarrow$ Outbound TLS WSS $\rightarrow$ Cloudflare Relay.
* **PoC-2**: iPhone ChatGPT queries **real** workstation DAIO status in real time.
* **PoC-3**: iPhone ChatGPT delivers authenticated `APPROVE` / `REVISE` decision to workstation `process_incoming_architect_decision()`.
* **PoC-4**: Workstation DAIO pushes real-time lock screen alerts to iPhone.
