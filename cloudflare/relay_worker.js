/**
 * Cloudflare Worker: Unified DAIO Remote Relay (RPC-1 Status Plane + RPC-2A Decision Transport)
 *
 * Architecture:
 * - Two logically isolated planes in a single unified worker.
 * - RPC-1 Status Plane: Read/Write project cockpit telemetry.
 * - RPC-2A Decision Transport Plane: Ephemeral, authenticated decision buffer with ACK.
 * - Strict privilege separation between publishing tokens and decision secrets.
 */

const COCKPIT_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="DAIO Cockpit">
  <meta name="theme-color" content="#090d16">
  <title>DAIO Owner Cockpit</title>
  <style>
    :root {
      --bg-base: #090d16;
      --bg-card: rgba(19, 27, 46, 0.85);
      --border-card: rgba(255, 255, 255, 0.08);
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --color-green: #10b981;
      --color-green-glow: rgba(16, 185, 129, 0.25);
      --color-amber: #f59e0b;
      --color-amber-glow: rgba(245, 158, 11, 0.25);
      --color-red: #ef4444;
      --color-red-glow: rgba(239, 68, 68, 0.25);
      --color-blue: #3b82f6;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-base);
      color: var(--text-primary);
      min-height: 100vh;
      padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
      display: flex;
      flex-direction: column;
      align-items: center;
      -webkit-font-smoothing: antialiased;
    }
    .cockpit-container {
      width: 100%;
      max-width: 420px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    /* Header */
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 4px 2px 8px 2px;
    }
    .header-title {
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .header-badge {
      font-size: 0.68rem;
      font-weight: 600;
      padding: 2px 7px;
      border-radius: 999px;
      background: rgba(59, 130, 246, 0.15);
      color: #60a5fa;
      border: 1px solid rgba(59, 130, 246, 0.3);
      text-transform: uppercase;
    }
    .btn-refresh {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border-card);
      color: var(--text-primary);
      padding: 6px 12px;
      border-radius: 10px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn-refresh:active {
      transform: scale(0.96);
      background: rgba(255, 255, 255, 0.12);
    }
    /* Cards */
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      padding: 14px 16px;
      backdrop-filter: blur(16px);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .card-label {
      font-size: 0.72rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .card-title {
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text-primary);
    }
    .meta-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.84rem;
      color: var(--text-secondary);
      padding: 2px 0;
    }
    .meta-val {
      font-weight: 500;
      color: var(--text-primary);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.82rem;
    }
    /* Freshness Badges */
    .status-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 0.92rem;
    }
    .status-fresh {
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      box-shadow: 0 0 16px var(--color-green-glow);
    }
    .status-stale {
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.3);
      color: #fbbf24;
      box-shadow: 0 0 16px var(--color-amber-glow);
    }
    .status-offline {
      background: rgba(239, 68, 68, 0.12);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #f87171;
      box-shadow: 0 0 16px var(--color-red-glow);
    }
    .status-unknown {
      background: rgba(100, 116, 139, 0.12);
      border: 1px solid rgba(100, 116, 139, 0.3);
      color: #94a3b8;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 6px;
    }
    .dot-fresh { background: #10b981; box-shadow: 0 0 8px #10b981; }
    .dot-stale { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; }
    .dot-offline { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
    .dot-unknown { background: #64748b; }
    /* Tag Pills */
    .pill {
      font-size: 0.72rem;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 6px;
      text-transform: uppercase;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .pill-synced { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.25); }
    .pill-ahead { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.25); }
    .pill-gate { background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.25); }
    .pill-role { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.25); }
    /* Action Zone */
    .action-card {
      border-radius: 16px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .action-autonomous {
      background: rgba(16, 185, 129, 0.08);
      border: 1px solid rgba(16, 185, 129, 0.25);
    }
    .action-human-gate {
      background: rgba(239, 68, 68, 0.12);
      border: 1px solid rgba(239, 68, 68, 0.4);
      box-shadow: 0 0 16px var(--color-red-glow);
    }
    .action-notice {
      font-size: 0.76rem;
      color: var(--text-muted);
      font-style: italic;
      margin-top: 4px;
    }
    /* Network Banner */
    .net-error {
      background: rgba(220, 38, 38, 0.2);
      border: 1px solid #ef4444;
      color: #fca5a5;
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 0.8rem;
      display: none;
      align-items: center;
      gap: 6px;
    }
    /* Footer */
    .footer {
      text-align: center;
      font-size: 0.72rem;
      color: var(--text-muted);
      padding: 10px 0 4px 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
  </style>
</head>
<body>
  <div class="cockpit-container">
    <!-- Header -->
    <div class="header">
      <div class="header-title">
        <span>🚀 DAIO Cockpit</span>
        <span class="header-badge">RPC-3B MVP</span>
      </div>
      <button id="btn-refresh" class="btn-refresh" onclick="fetchCockpitStatus(true)">
        <span id="refresh-icon">🔄</span>
        <span id="refresh-label">Refresh</span>
      </button>
    </div>

    <!-- Network / Relay Error Banner -->
    <div id="net-error-banner" class="net-error">
      <span>⚠️ Cockpit cannot reach DAIO Relay (Cloudflare edge unreachable or network error)</span>
    </div>

    <!-- ① ZONE 1: PROJECT -->
    <div class="card" id="zone-project">
      <div class="card-label">
        <span>① Project & Governance</span>
        <span id="val-push-sync" class="pill pill-synced">SYNCED</span>
      </div>
      <div class="card-title" id="val-project-name">Loading...</div>
      <div class="meta-row">
        <span>Repository</span>
        <span class="meta-val" id="val-repo-name">—</span>
      </div>
      <div class="meta-row">
        <span>Git Branch / HEAD</span>
        <span class="meta-val" id="val-git-branch-sha">—</span>
      </div>
    </div>

    <!-- ② ZONE 2: LIVE STATUS -->
    <div class="card" id="zone-status">
      <div class="card-label">② Live Status Plane</div>
      <div id="status-banner" class="status-banner status-unknown">
        <div>
          <span id="status-dot" class="status-dot dot-unknown"></span>
          <span id="val-host-status">INITIALIZING</span>
        </div>
        <span id="val-freshness-text" style="font-size:0.78rem; font-weight:500;">Connecting...</span>
      </div>
      <div class="meta-row">
        <span>Mac Host</span>
        <span class="meta-val" id="val-mac-host">—</span>
      </div>
      <div class="meta-row">
        <span>Supervisor Daemon</span>
        <span class="meta-val" id="val-supervisor-status">—</span>
      </div>
      <div class="meta-row">
        <span>Heartbeat Age</span>
        <span class="meta-val" id="val-heartbeat-age">—</span>
      </div>
      <div class="meta-row">
        <span>Last Status Report</span>
        <span class="meta-val" id="val-collected-at">—</span>
      </div>
    </div>

    <!-- ③ ZONE 3: CURRENT WORK -->
    <div class="card" id="zone-work">
      <div class="card-label">
        <span>③ Current Work Item</span>
        <span id="val-queue-depth" class="pill pill-role">Queue: 0</span>
      </div>
      <div class="card-title" id="val-work-title" style="font-size: 0.95rem;">No Active Work</div>
      <div class="meta-row">
        <span>Work ID</span>
        <span class="meta-val" id="val-work-id">—</span>
      </div>
      <div class="meta-row">
        <span>Stage / Gate</span>
        <span class="meta-val" id="val-stage-gate">—</span>
      </div>
      <div class="meta-row">
        <span>Assigned Role</span>
        <span class="meta-val" id="val-assigned-role">—</span>
      </div>
      <div class="meta-row">
        <span>Work Status</span>
        <span class="meta-val" id="val-work-status">—</span>
      </div>
    </div>

    <!-- ④ ZONE 4: OWNER ACTION (READ-ONLY RPC-3B) -->
    <div id="action-box" class="action-card action-autonomous">
      <div class="card-label" style="color:inherit;">
        <span id="action-header">④ Owner Action Required</span>
        <span id="action-pill" class="pill pill-synced">AUTONOMOUS</span>
      </div>
      <div id="action-title" style="font-weight:600; font-size:0.95rem;">
        🟢 No action required — DAIO is operating autonomously.
      </div>
      <div id="action-reason" style="font-size:0.82rem; color:var(--text-secondary); display:none;"></div>
      <div class="action-notice">🔒 Read-Only Cockpit (RPC-3B): Decision controls will be enabled in RPC-3C.</div>
    </div>

    <!-- ⑤ ZONE 5: TELEMETRY FACTS -->
    <div class="card" id="zone-facts">
      <div class="card-label">⑤ Verified Telemetry Facts</div>
      <div class="meta-row">
        <span>Relay Node</span>
        <span class="meta-val" id="val-relay-node">Cloudflare Edge</span>
      </div>
      <div class="meta-row">
        <span>Server Timestamp</span>
        <span class="meta-val" id="val-server-timestamp">—</span>
      </div>
      <div class="meta-row">
        <span>Git Working Tree</span>
        <span class="meta-val" id="val-working-tree">—</span>
      </div>
      <div class="meta-row" style="margin-top:2px;">
        <span style="font-size:0.72rem; color:var(--text-muted); font-style:italic;">
          ℹ️ Historical decision timeline API will be integrated in RPC-3C/3D.
        </span>
      </div>
    </div>

    <!-- Footer -->
    <div class="footer">
      <div>DAIO Universal Dual-Agent Iteration Orchestrator</div>
      <div id="val-footer-sync">Auto-refreshing in 3.5s...</div>
    </div>
  </div>

  <script>
    let pollTimer = null;
    let countdownSec = 3.5;

    async function fetchCockpitStatus(isManual = false) {
      const netError = document.getElementById('net-error-banner');
      const refreshIcon = document.getElementById('refresh-icon');
      if (isManual && refreshIcon) refreshIcon.style.transform = 'rotate(180deg)';

      try {
        const resp = await fetch('/api/v1/status', { cache: 'no-store' });
        if (!resp.ok) {
          throw new Error('HTTP ' + resp.status);
        }
        const data = await resp.json();
        netError.style.display = 'none';
        renderCockpitData(data);
      } catch (err) {
        netError.style.display = 'flex';
        netError.innerHTML = '<span>⚠️ Cockpit cannot reach DAIO Relay (' + (err.message || 'Network error') + ')</span>';
      } finally {
        if (isManual && refreshIcon) {
          setTimeout(() => { refreshIcon.style.transform = 'none'; }, 300);
        }
      }
    }

    function renderCockpitData(data) {
      const live = data.live_plane || {};
      const durable = data.durable_plane || {};
      const prov = data.provenance || {};

      // ① PROJECT
      document.getElementById('val-project-name').textContent = live.project_name || 'DAIO Project';
      document.getElementById('val-repo-name').textContent = durable.repository || 'Local Project';
      const branch = durable.git_branch || 'main';
      const sha = (durable.local_head_sha || '').substring(0, 7) || 'HEAD';
      document.getElementById('val-git-branch-sha').textContent = branch + ' (' + sha + ')';

      const pushSyncEl = document.getElementById('val-push-sync');
      if (durable.push_synchronized) {
        pushSyncEl.className = 'pill pill-synced';
        pushSyncEl.textContent = '✓ SYNCED';
      } else {
        pushSyncEl.className = 'pill pill-ahead';
        const ahead = durable.ahead_count || 0;
        const dirty = !durable.working_tree_clean ? ' Dirty' : '';
        pushSyncEl.textContent = (ahead > 0 ? ('Ahead ' + ahead) : 'Unsynced') + dirty;
      }

      // ② LIVE STATUS
      const statusBanner = document.getElementById('status-banner');
      const statusDot = document.getElementById('status-dot');
      const hostStatus = document.getElementById('val-host-status');
      const freshnessText = document.getElementById('val-freshness-text');

      const freshness = (live.freshness || 'UNKNOWN').toUpperCase();
      const hStatus = (live.host_status || 'UNKNOWN').toUpperCase();
      const ageSec = live.heartbeat_age_seconds != null ? live.heartbeat_age_seconds.toFixed(1) + 's ago' : 'No heartbeat';

      statusBanner.className = 'status-banner';
      statusDot.className = 'status-dot';

      if (freshness === 'FRESH' && live.supervisor_running) {
        statusBanner.classList.add('status-fresh');
        statusDot.classList.add('dot-fresh');
        hostStatus.textContent = 'ONLINE • FRESH';
        freshnessText.textContent = ageSec;
      } else if (freshness === 'STALE') {
        statusBanner.classList.add('status-stale');
        statusDot.classList.add('dot-stale');
        hostStatus.textContent = 'STALE (' + hStatus + ')';
        freshnessText.textContent = ageSec;
      } else if (freshness === 'OFFLINE' || !live.supervisor_running) {
        statusBanner.classList.add('status-offline');
        statusDot.classList.add('dot-offline');
        hostStatus.textContent = 'HOST OFFLINE';
        freshnessText.textContent = ageSec;
      } else {
        statusBanner.classList.add('status-unknown');
        statusDot.classList.add('dot-unknown');
        hostStatus.textContent = 'UNKNOWN';
        freshnessText.textContent = 'No status';
      }

      document.getElementById('val-mac-host').textContent = live.host || 'unknown';
      document.getElementById('val-supervisor-status').textContent = live.supervisor_running
        ? ('Running (PID ' + (live.supervisor_pid || '—') + ')')
        : 'Stopped / Offline';
      document.getElementById('val-heartbeat-age').textContent = ageSec;
      document.getElementById('val-collected-at').textContent = prov.collected_at ? formatTime(prov.collected_at) : '—';

      // ③ CURRENT WORK
      document.getElementById('val-queue-depth').textContent = 'Queue: ' + (live.queue_depth || 0);
      if (live.active_work_id) {
        document.getElementById('val-work-title').textContent = live.active_work_item || live.active_work_id;
        document.getElementById('val-work-id').textContent = live.active_work_id;
        document.getElementById('val-stage-gate').textContent = (live.current_phase || '—') + ' / ' + (live.current_gate || '—');
        document.getElementById('val-assigned-role').textContent = live.assigned_role || '—';
        document.getElementById('val-work-status').textContent = live.human_gate_required ? 'HUMAN_GATE_REQUIRED' : (live.supervisor_running ? 'IN_PROGRESS' : 'IDLE');
      } else {
        document.getElementById('val-work-title').textContent = 'No Active Work Items';
        document.getElementById('val-work-id').textContent = '—';
        document.getElementById('val-stage-gate').textContent = '—';
        document.getElementById('val-assigned-role').textContent = '—';
        document.getElementById('val-work-status').textContent = 'ALL_COMPLETED / IDLE';
      }

      // ④ OWNER ACTION (READ-ONLY RPC-3B)
      const actionBox = document.getElementById('action-box');
      const actionTitle = document.getElementById('action-title');
      const actionPill = document.getElementById('action-pill');
      const actionReason = document.getElementById('action-reason');

      const isHumanGate = live.human_gate_required && live.current_gate === 'HUMAN_GATE' && live.assigned_role === 'HUMAN_PROJECT_OWNER';

      if (isHumanGate) {
        actionBox.className = 'action-card action-human-gate';
        actionPill.className = 'pill pill-gate';
        actionPill.textContent = 'GATE ACTIVE';
        actionTitle.textContent = '🔴 Human decision required';
        actionReason.style.display = 'block';
        actionReason.textContent = live.human_gate_reason ? ('Reason: ' + live.human_gate_reason) : 'Reason: Awaiting Owner authorization.';
      } else {
        actionBox.className = 'action-card action-autonomous';
        actionPill.className = 'pill pill-synced';
        actionPill.textContent = 'AUTONOMOUS';
        actionTitle.textContent = '🟢 No action required — DAIO is operating autonomously.';
        actionReason.style.display = 'none';
      }

      // ⑤ TELEMETRY FACTS
      document.getElementById('val-relay-node').textContent = prov.relay_node || 'Cloudflare Edge';
      document.getElementById('val-server-timestamp').textContent = prov.server_timestamp ? formatTime(prov.server_timestamp) : '—';
      document.getElementById('val-working-tree').textContent = durable.working_tree_clean ? 'Clean' : 'Modified files present';
    }

    function formatTime(isoStr) {
      try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString([], { hour12: false }) + ' (' + d.toISOString().substring(0, 10) + ')';
      } catch (e) {
        return isoStr;
      }
    }

    // Auto-poll loop
    fetchCockpitStatus();
    setInterval(() => {
      fetchCockpitStatus();
    }, 3500);
  </script>
</body>
</html>
`;

const OPENAPI_SPEC = {
  openapi: "3.1.0",
  info: {
    title: "DAIO Unified Remote Relay API (RPC-1 + RPC-2A + RPC-3B)",
    description: "Unified edge relay providing remote cockpit status (RPC-1), authenticated human decision transport (RPC-2A), and iPhone Owner Cockpit web UI (RPC-3B).",
    version: "3.0.0",
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
    "/cockpit": {
      get: {
        summary: "iPhone Owner Cockpit Web Application (RPC-3B)",
        operationId: "getCockpitUI",
        responses: { "200": { description: "HTML/CSS/JS Cockpit UI" } },
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
    // 1. META, CATALOG & COCKPIT ROUTES
    // =========================================================================

    // GET/HEAD /cockpit or /ui (iPhone Owner Cockpit Web Application)
    if ((path === "/cockpit" || path === "/ui") && (request.method === "GET" || request.method === "HEAD")) {
      return new Response(request.method === "HEAD" ? null : COCKPIT_HTML, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-cache, no-store, must-revalidate",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // GET/HEAD / (Service Catalog or Cockpit for browser text/html accept)
    if (path === "/" && (request.method === "GET" || request.method === "HEAD")) {
      const accept = request.headers.get("Accept") || "";
      if (accept.includes("text/html") && !accept.includes("application/json")) {
        return new Response(request.method === "HEAD" ? null : COCKPIT_HTML, {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
          },
        });
      }

      let publishedAvailable = false;
      if (statusKV) {
        const latest = await statusKV.get("status:latest");
        publishedAvailable = !!latest;
      }

      const catalogBody = JSON.stringify({
        status: "OK",
        service: "DAIO Unified Remote Relay (RPC-1 Status + RPC-2A Decision Transport + RPC-3B Cockpit)",
        version: "daio-rpc/v3.0",
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
          rpc3b_owner_cockpit: {
            cockpit_ui: `${url.origin}/cockpit`,
          },
        },
        endpoints: {
          cockpit_ui: `${url.origin}/cockpit`,
          status_query: `${url.origin}/api/v1/status`,
          publish_endpoint: `${url.origin}/api/v1/publish`,
          openapi_spec: `${url.origin}/openapi.json`,
        },
      });

      return new Response(request.method === "HEAD" ? null : catalogBody, { headers: corsHeaders });
    }

    // GET/HEAD /openapi.json
    if (path === "/openapi.json" && (request.method === "GET" || request.method === "HEAD")) {
      return new Response(request.method === "HEAD" ? null : JSON.stringify(OPENAPI_SPEC, null, 2), { headers: corsHeaders });
    }

    // GET/HEAD /api/v1/health (RPC-2A Health)
    if (path === "/api/v1/health" && (request.method === "GET" || request.method === "HEAD")) {
      const healthBody = JSON.stringify({
        status: "OK",
        timestamp: new Date().toISOString(),
        relay: "daio-unified-relay",
      });
      return new Response(request.method === "HEAD" ? null : healthBody, { headers: corsHeaders });
    }

    // =========================================================================
    // 2. RPC-1 STATUS PLANE ROUTES
    // =========================================================================

    // GET/HEAD /api/v1/status (Read published status)
    if (path === "/api/v1/status" && (request.method === "GET" || request.method === "HEAD")) {
      if (!statusKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured", reason: "Status KV store binding not found" }), {
          status: 500,
          headers: corsHeaders,
        });
      }

      const statusJson = await statusKV.get("status:latest");
      if (!statusJson) {
        const defaultStatus = JSON.stringify({
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
        });
        return new Response(request.method === "HEAD" ? null : defaultStatus, { status: 200, headers: corsHeaders });
      }

      return new Response(request.method === "HEAD" ? null : statusJson, { headers: corsHeaders });
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
