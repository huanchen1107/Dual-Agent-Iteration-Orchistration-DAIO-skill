/**
 * Cloudflare Worker: Unified DAIO Remote Relay (RPC-1 Status Plane + RPC-2A Decision Transport)
 *
 * Architecture:
 * - Two logically isolated planes in a single unified worker.
 * - RPC-1 Status Plane: Read/Write project cockpit telemetry.
 * - RPC-2A Decision Transport Plane: Ephemeral, authenticated decision buffer with ACK.
 * - Strict privilege separation between publishing tokens and decision secrets.
 */

const OPENAPI_SPEC = {
  openapi: "3.1.0",
  info: {
    title: "DAIO Unified Remote Relay API (RPC-1 + RPC-2A)",
    description: "Unified edge relay providing remote cockpit status (RPC-1) and authenticated human decision transport (RPC-2A).",
    version: "2.1.0",
  },
  servers: [
    {
      url: "https://daio-relay.huanchen1107.workers.dev",
      description: "Production Edge Relay",
    },
  ],
  paths: {
    "/": {
      get: {
        summary: "Relay Service Information and Catalog",
        operationId: "getRelayInfo",
        responses: { "200": { description: "Service Catalog" } },
      },
    },
    "/api/v1/status": {
      get: {
        summary: "Get Real DAIO Project Status (RPC-1)",
        operationId: "getDAIOProjectStatus",
        responses: {
          "200": { description: "Current two-plane status" },
          "404": { description: "No status published yet" },
        },
      },
    },
    "/api/v1/publish": {
      post: {
        summary: "Publish DAIO Status from Host (RPC-1)",
        operationId: "publishDAIOStatus",
        security: [{ PublishBearerAuth: [] }],
        responses: {
          "200": { description: "Status published successfully" },
          "401": { description: "Unauthorized: Invalid publish token" },
        },
      },
    },
    "/api/v1/health": {
      get: {
        summary: "Health and Latency Check (RPC-2A)",
        operationId: "getHealthStatus",
        responses: { "200": { description: "Health OK" } },
      },
    },
    "/api/v1/decisions": {
      post: {
        summary: "Submit Human Decision Envelope (RPC-2A)",
        operationId: "submitDecision",
        security: [{ RelayBearerAuth: [] }],
        responses: {
          "201": { description: "Decision submitted and buffered" },
          "400": { description: "Malformed envelope" },
          "401": { description: "Unauthorized: Invalid relay secret" },
        },
      },
      get: {
        summary: "Poll Pending Decisions (RPC-2A)",
        operationId: "pollDecisions",
        security: [{ RelayBearerAuth: [] }],
        parameters: [
          { name: "project_id", in: "query", required: true, schema: { type: "string" } },
          { name: "work_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": { description: "Array of unacknowledged decision envelopes" },
          "401": { description: "Unauthorized: Invalid relay secret" },
        },
      },
    },
    "/api/v1/decisions/{decision_id}/ack": {
      post: {
        summary: "Acknowledge Delivery / Dry-Run Processing (RPC-2A)",
        operationId: "acknowledgeDecision",
        security: [{ RelayBearerAuth: [] }],
        responses: {
          "200": { description: "Acknowledgment recorded" },
          "401": { description: "Unauthorized: Invalid relay secret" },
        },
      },
    },
  },
  components: {
    securitySchemes: {
      PublishBearerAuth: {
        type: "http",
        scheme: "bearer",
        description: "Token for RPC-1 status publishing (DAIO_RPC_PUBLISH_TOKEN)",
      },
      RelayBearerAuth: {
        type: "http",
        scheme: "bearer",
        description: "Secret for RPC-2A decision operations (DAIO_RELAY_SECRET)",
      },
    },
  },
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
      });
    }

    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Content-Type": "application/json",
    };

    // Helper: resolve KV store (supports STATUS_KV, DECISION_KV, or shared DAIO_KV)
    const statusKV = env.STATUS_KV || env.DECISION_KV || env.DAIO_KV;
    const decisionKV = env.DECISION_KV || env.STATUS_KV || env.DAIO_KV;

    // Helper: extract bearer token
    const authHeader = request.headers.get("Authorization") || "";
    const bearerToken = authHeader.replace(/^Bearer\s+/i, "").trim();

    // =========================================================================
    // 1. META & CATALOG ROUTES
    // =========================================================================

    // GET / (Service Catalog)
    if (path === "/" && request.method === "GET") {
      let publishedAvailable = false;
      if (statusKV) {
        const latest = await statusKV.get("status:latest");
        publishedAvailable = !!latest;
      }

      return new Response(
        JSON.stringify({
          status: "OK",
          service: "DAIO Unified Remote Relay (RPC-1 Status + RPC-2A Decision Transport)",
          version: "daio-rpc/v2.1",
          published_status_available: publishedAvailable,
          planes: {
            rpc1_status_plane: {
              status_query: `${url.origin}/api/v1/status`,
              publish_endpoint: `${url.origin}/api/v1/publish`,
            },
            rpc2a_decision_plane: {
              health: `${url.origin}/api/v1/health`,
              submit_decision: `${url.origin}/api/v1/decisions`,
              poll_decisions: `${url.origin}/api/v1/decisions?project_id=awin-fintech`,
            },
          },
          endpoints: {
            status_query: `${url.origin}/api/v1/status`,
            publish_endpoint: `${url.origin}/api/v1/publish`,
            openapi_spec: `${url.origin}/openapi.json`,
          },
        }),
        { headers: corsHeaders }
      );
    }

    // GET /openapi.json
    if (path === "/openapi.json" && request.method === "GET") {
      return new Response(JSON.stringify(OPENAPI_SPEC, null, 2), { headers: corsHeaders });
    }

    // GET /api/v1/health (RPC-2A Health)
    if (path === "/api/v1/health" && request.method === "GET") {
      return new Response(
        JSON.stringify({
          status: "OK",
          timestamp: new Date().toISOString(),
          relay: "daio-unified-relay",
        }),
        { headers: corsHeaders }
      );
    }

    // =========================================================================
    // 2. RPC-1 STATUS PLANE ROUTES
    // =========================================================================

    // GET /api/v1/status (Read published status)
    if (path === "/api/v1/status" && request.method === "GET") {
      if (!statusKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured", reason: "Status KV store binding not found" }), {
          status: 500,
          headers: corsHeaders,
        });
      }

      const statusJson = await statusKV.get("status:latest");
      if (!statusJson) {
        return new Response(
          JSON.stringify({
            live_plane: {
              project_name: "DAIO",
              host: "unknown",
              host_status: "UNKNOWN",
              freshness: "UNKNOWN",
              supervisor_running: false,
              heartbeat_age_seconds: null,
              degraded_note: "No status published yet from DAIO host instance.",
            },
            durable_plane: {
              repository: null,
              push_synchronized: false,
            },
            provenance: {
              protocol_version: "daio-rpc/v1",
              relay_node: "cloudflare-edge",
              server_timestamp: new Date().toISOString(),
            },
          }),
          { status: 200, headers: corsHeaders }
        );
      }

      return new Response(statusJson, { headers: corsHeaders });
    }

    // POST /api/v1/publish (Publish status from Mac host)
    if (path === "/api/v1/publish" && request.method === "POST") {
      const publishToken = env.DAIO_RPC_PUBLISH_TOKEN || "";
      if (!publishToken || bearerToken !== publishToken) {
        return new Response(
          JSON.stringify({ error: "Unauthorized", reason: "Invalid or missing DAIO_RPC_PUBLISH_TOKEN" }),
          { status: 401, headers: corsHeaders }
        );
      }

      if (!statusKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured", reason: "Status KV store binding not found" }), {
          status: 500,
          headers: corsHeaders,
        });
      }

      try {
        const body = await request.json();
        const payloadStr = JSON.stringify({
          ...body,
          relay_received_at: new Date().toISOString(),
        });
        // Retain status for 7 days
        await statusKV.put("status:latest", payloadStr, { expirationTtl: 604800 });
        return new Response(JSON.stringify({ status: "OK", published_at: new Date().toISOString() }), {
          status: 200,
          headers: corsHeaders,
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Bad Request", reason: String(err) }), {
          status: 400,
          headers: corsHeaders,
        });
      }
    }

    // =========================================================================
    // 3. RPC-2A DECISION TRANSPORT PLANE ROUTES
    // =========================================================================

    // Gate: Check RPC-2A Secret for all /api/v1/decisions* routes
    if (path.startsWith("/api/v1/decisions")) {
      const relaySecret = env.DAIO_RELAY_SECRET || "";
      if (!relaySecret || bearerToken !== relaySecret) {
        return new Response(
          JSON.stringify({ error: "Unauthorized", reason: "Invalid or missing DAIO_RELAY_SECRET" }),
          { status: 401, headers: corsHeaders }
        );
      }

      if (!decisionKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured", reason: "Decision KV store binding not found" }), {
          status: 500,
          headers: corsHeaders,
        });
      }

      // POST /api/v1/decisions (Submit decision from iPhone / Client)
      if (path === "/api/v1/decisions" && request.method === "POST") {
        try {
          const body = await request.json();
          const decisionId = body.decision_id || crypto.randomUUID();
          const projectId = body.project_id;

          if (!projectId || !body.decision || !body.work_id) {
            return new Response(
              JSON.stringify({ error: "Bad Request", reason: "Missing required fields: project_id, decision, work_id" }),
              { status: 400, headers: corsHeaders }
            );
          }

          const envelope = {
            protocol_version: body.protocol_version || "rpc-2.v1",
            decision_id: decisionId,
            project_id: projectId,
            work_id: body.work_id,
            gate_id: body.gate_id || "HUMAN_GATE",
            decision: String(body.decision).toUpperCase(),
            current_phase: body.current_phase || "",
            next_phase: body.next_phase || null,
            action: String(body.action || "RUN").toUpperCase(),
            instruction: body.instruction || "",
            issued_at: body.issued_at || new Date().toISOString(),
            expires_at: body.expires_at || new Date(Date.now() + 86400000).toISOString(),
            delivery_status: "SUBMITTED",
            metadata: body.metadata || {},
          };

          const kvKey = `decision:${projectId}:${decisionId}`;
          const ttlSeconds = parseInt(env.DECISION_TTL_SECONDS || "86400", 10);
          await decisionKV.put(kvKey, JSON.stringify(envelope), { expirationTtl: ttlSeconds });

          // Maintain active decision index for this project
          const indexKey = `index:${projectId}`;
          let activeList = (await decisionKV.get(indexKey, { type: "json" })) || [];
          if (!activeList.includes(decisionId)) {
            activeList.push(decisionId);
            await decisionKV.put(indexKey, JSON.stringify(activeList), { expirationTtl: ttlSeconds });
          }

          return new Response(
            JSON.stringify({ status: "SUBMITTED", decision_id: decisionId, envelope }),
            { status: 201, headers: corsHeaders }
          );
        } catch (err) {
          return new Response(JSON.stringify({ error: "Invalid JSON", reason: String(err) }), {
            status: 400,
            headers: corsHeaders,
          });
        }
      }

      // GET /api/v1/decisions?project_id=... (Poll from Mac DAIO)
      if (path === "/api/v1/decisions" && request.method === "GET") {
        const projectId = url.searchParams.get("project_id");
        const workId = url.searchParams.get("work_id");

        if (!projectId) {
          return new Response(
            JSON.stringify({ error: "Bad Request", reason: "Missing required query parameter: 'project_id'" }),
            { status: 400, headers: corsHeaders }
          );
        }

        const indexKey = `index:${projectId}`;
        const activeList = (await decisionKV.get(indexKey, { type: "json" })) || [];
        const decisions = [];

        for (const dId of activeList) {
          const kvKey = `decision:${projectId}:${dId}`;
          const itemStr = await decisionKV.get(kvKey);
          if (itemStr) {
            const item = JSON.parse(itemStr);
            if (!workId || item.work_id === workId) {
              decisions.push(item);
            }
          }
        }

        return new Response(
          JSON.stringify({ project_id: projectId, count: decisions.length, decisions }),
          { headers: corsHeaders }
        );
      }

      // POST /api/v1/decisions/:decision_id/ack (Acknowledge from Mac)
      if (path.startsWith("/api/v1/decisions/") && path.endsWith("/ack") && request.method === "POST") {
        const parts = path.split("/");
        const decisionId = parts[parts.length - 2];
        const body = await request.json().catch(() => ({}));
        const ackStatus = body.status || "ACKNOWLEDGED";

        // Find and remove from active index
        const list = await decisionKV.list({ prefix: "decision:" });
        let matchedKey = null;
        let matchedProject = null;

        for (const k of list.keys) {
          if (k.name.endsWith(`:${decisionId}`)) {
            matchedKey = k.name;
            matchedProject = k.name.split(":")[1];
            break;
          }
        }

        if (matchedKey) {
          await decisionKV.delete(matchedKey);
          if (matchedProject) {
            const indexKey = `index:${matchedProject}`;
            let activeList = (await decisionKV.get(indexKey, { type: "json" })) || [];
            activeList = activeList.filter((id) => id !== decisionId);
            await decisionKV.put(indexKey, JSON.stringify(activeList), { expirationTtl: 86400 });
          }
          return new Response(
            JSON.stringify({ status: "ACK_PROCESSED", decision_id: decisionId, ack_status: ackStatus }),
            { headers: corsHeaders }
          );
        }

        return new Response(
          JSON.stringify({ status: "NOT_FOUND_OR_ALREADY_ACKED", decision_id: decisionId }),
          { status: 200, headers: corsHeaders }
        );
      }
    }

    // Default 404
    return new Response(JSON.stringify({ error: "Not Found", path }), { status: 404, headers: corsHeaders });
  },
};
