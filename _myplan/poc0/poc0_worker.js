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
