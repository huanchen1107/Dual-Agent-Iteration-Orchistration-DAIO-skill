/**
 * DAIO Remote Project Cockpit (RPC-1) - Cloud Relay Worker
 * Protocol: daio-rpc/v1 (Real Outbound Status Relay)
 */

let memoryStore = {
  payload: null,
  publishedAtMs: 0
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
      url: "https://daio-relay.huanchen1107.workers.dev",
      description: "Production Cloud Relay Endpoint"
    }
  ],
  paths: {
    "/api/v1/status": {
      get: {
        operationId: "getDAIOProjectStatus",
        summary: "Get current real DAIO live and durable project status",
        description: "Returns live plane execution telemetry (with freshness enforcement) and durable plane Git provenance.",
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
    },
    "/api/v1/publish": {
      post: {
        operationId: "publishDAIOStatus",
        summary: "Publish real Two-Plane DAIO status from Mac/PC",
        description: "Authenticated endpoint accepting real status updates from DAIO host instance.",
        security: [{ BearerAuth: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["live_plane", "durable_plane"],
                properties: {
                  live_plane: { type: "object" },
                  durable_plane: { type: "object" },
                  provenance: { type: "object" }
                }
              }
            }
          }
        },
        responses: {
          "200": { description: "Status published successfully" },
          "401": { description: "Unauthorized publisher token" }
        }
      }
    }
  },
  components: {
    securitySchemes: {
      BearerAuth: {
        type: "http",
        scheme: "bearer"
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

    // -------------------------------------------------------------
    // Channel A (Write): Authenticated Publication from Mac/PC DAIO
    // -------------------------------------------------------------
    if (url.pathname === "/api/v1/publish" || (url.pathname === "/api/v1/status" && request.method === "POST")) {
      const expectedToken = (env && env.DAIO_RPC_PUBLISH_TOKEN) ? env.DAIO_RPC_PUBLISH_TOKEN.trim() : "";

      // 1. Fail Closed: Reject publication if relay secret is not configured
      if (!expectedToken) {
        return new Response(
          JSON.stringify(
            { error: "Server Configuration Error: DAIO_RPC_PUBLISH_TOKEN is not configured on Cloudflare Relay. Publication is disabled (fail-closed)." },
            null,
            2
          ),
          { status: 503, headers: corsHeaders }
        );
      }

      // 2. Enforce Bearer Token authentication
      const authHeader = request.headers.get("Authorization") || "";
      const tokenMatch = authHeader.match(/^Bearer\s+(.+)$/i);
      const incomingToken = tokenMatch ? tokenMatch[1].trim() : "";

      if (!incomingToken || incomingToken !== expectedToken) {
        return new Response(
          JSON.stringify({ error: "Unauthorized: Invalid or missing publisher Bearer token." }, null, 2),
          { status: 401, headers: corsHeaders }
        );
      }


      try {
        const body = await request.json();
        if (!body || !body.live_plane || !body.durable_plane) {
          return new Response(
            JSON.stringify({ error: "Invalid payload: missing live_plane or durable_plane." }, null, 2),
            { status: 400, headers: corsHeaders }
          );
        }

        memoryStore.payload = body;
        memoryStore.publishedAtMs = Date.now();

        // If KV storage is bound, persist for multi-region consistency
        if (env.DAIO_KV) {
          await env.DAIO_KV.put("latest_status", JSON.stringify(body));
          await env.DAIO_KV.put("published_at_ms", String(memoryStore.publishedAtMs));
        }

        return new Response(
          JSON.stringify(
            {
              status: "PUBLISHED",
              published_at: new Date().toISOString(),
              project: body.live_plane.project_name || "unknown",
              verified_git_sha: body.durable_plane.local_head_sha || "unknown"
            },
            null,
            2
          ),
          { status: 200, headers: corsHeaders }
        );
      } catch (err) {
        return new Response(
          JSON.stringify({ error: `Failed to parse status payload: ${err.message}` }, null, 2),
          { status: 400, headers: corsHeaders }
        );
      }
    }

    // -------------------------------------------------------------
    // Channel A (Read): Public / ChatGPT Query for Real Status
    // -------------------------------------------------------------
    if (url.pathname === "/api/v1/status" && request.method === "GET") {
      let payload = memoryStore.payload;
      let publishedAtMs = memoryStore.publishedAtMs;

      // If in-memory is empty but KV is bound, recover from KV
      if (!payload && env.DAIO_KV) {
        const kvStatus = await env.DAIO_KV.get("latest_status");
        const kvPubAt = await env.DAIO_KV.get("published_at_ms");
        if (kvStatus) {
          payload = JSON.parse(kvStatus);
          publishedAtMs = parseInt(kvPubAt || "0", 10);
        }
      }

      // If still empty (no publication yet), return truthful UNKNOWN status
      if (!payload) {
        return new Response(
          JSON.stringify(
            {
              live_plane: {
                project_name: "DAIO",
                host: "unknown",
                host_status: "UNKNOWN",
                freshness: "UNKNOWN",
                supervisor_running: false,
                heartbeat_age_seconds: null,
                degraded_note: "No status published yet from DAIO host instance."
              },
              durable_plane: {
                repository: null,
                push_synchronized: false
              },
              provenance: {
                protocol_version: "daio-rpc/v1",
                relay_node: "cloudflare-edge",
                server_timestamp: new Date().toISOString()
              }
            },
            null,
            2
          ),
          { status: 200, headers: corsHeaders }
        );
      }

      // Re-evaluate freshness dynamically based on elapsed time since publication
      const elapsedSec = (Date.now() - publishedAtMs) / 1000.0;
      const baseAge = payload.live_plane.heartbeat_age_seconds || 0;
      const totalAge = Math.round(baseAge + elapsedSec);

      // Deep clone payload to avoid mutating stored raw payload
      const responsePayload = JSON.parse(JSON.stringify(payload));
      responsePayload.live_plane.heartbeat_age_seconds = totalAge;

      // Invariant: Historical RUNNING must NEVER be returned as RUNNING when expired!
      if (totalAge > 180 || elapsedSec > 180) {
        responsePayload.live_plane.freshness = "OFFLINE";
        responsePayload.live_plane.host_status = "OFFLINE";
        responsePayload.live_plane.supervisor_running = false;
        responsePayload.live_plane.degraded_note = `Host heartbeat expired (${totalAge}s ago). Execution offline.`;
      } else if (totalAge >= 30 || elapsedSec >= 30) {
        responsePayload.live_plane.freshness = "STALE";
        responsePayload.live_plane.degraded_note = `Heartbeat stale (${totalAge}s ago). Live execution unconfirmed.`;
      }

      // Update provenance
      responsePayload.provenance = {
        ...(responsePayload.provenance || {}),
        relay_timestamp: new Date().toISOString(),
        relay_node: "cloudflare-edge",
        transit_age_seconds: Math.round(elapsedSec)
      };

      return new Response(JSON.stringify(responsePayload, null, 2), {
        status: 200,
        headers: corsHeaders
      });
    }

    // -------------------------------------------------------------
    // OpenAPI Specification
    // -------------------------------------------------------------
    if (url.pathname === "/openapi.json") {
      const dynamicSpec = {
        ...OPENAPI_SPEC,
        servers: [{ url: url.origin, description: "Active Edge Relay" }]
      };
      return new Response(JSON.stringify(dynamicSpec, null, 2), {
        status: 200,
        headers: corsHeaders
      });
    }

    // -------------------------------------------------------------
    // Health check & browser landing
    // -------------------------------------------------------------
    return new Response(
      JSON.stringify(
        {
          status: "OK",
          service: "DAIO Remote Project Cockpit (RPC-1) Cloud Relay",
          version: "daio-rpc/v1",
          published_status_available: Boolean(memoryStore.payload),
          endpoints: {
            status_query: `${url.origin}/api/v1/status`,
            publish_endpoint: `${url.origin}/api/v1/publish`,
            openapi_spec: `${url.origin}/openapi.json`
          }
        },
        null,
        2
      ),
      { status: 200, headers: corsHeaders }
    );
  }
};
