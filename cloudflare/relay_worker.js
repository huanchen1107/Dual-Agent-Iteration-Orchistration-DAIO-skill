/**
 * Cloudflare Worker: Unified DAIO Remote Relay (RPC-1 Status + RPC-2A Decision Transport + RPC-3C.2 Passkey Decision Ingress)
 *
 * Architecture:
 * - RPC-1 Status Plane: Read/Write project cockpit telemetry.
 * - RPC-2A Decision Transport Plane: Ephemeral, authenticated decision buffer with ACK.
 * - RPC-3C.2 Passkey Ingress Plane: WebAuthn Level 3 asymmetric hardware authentication,
 *   single-use 60s challenges, single-use 180s opaque Action Tickets strictly bound to
 *   (project_id, work_id, gate_id, current_phase, decision, action).
 * - Security Hardened: Strict CSP without unsafe-inline for scripts, safe DOM manipulation.
 * - Zero Mac Inbound Ports, Zero permanent secrets in client storage.
 */

// =============================================================================
// 1. COCKPIT HTML (Mobile Safari Optimized, Strict CSP Compliant)
// =============================================================================

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
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-base);
      color: var(--text-primary);
      min-height: 100vh;
      padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
      display: flex; flex-direction: column; align-items: center; -webkit-font-smoothing: antialiased;
    }
    .cockpit-container { width: 100%; max-width: 420px; display: flex; flex-direction: column; gap: 14px; }
    .header { display: flex; justify-content: space-between; align-items: center; padding: 4px 2px 8px 2px; }
    .header-title { font-size: 1.15rem; font-weight: 700; letter-spacing: -0.02em; display: flex; align-items: center; gap: 8px; }
    .header-badge { font-size: 0.68rem; font-weight: 600; padding: 2px 7px; border-radius: 999px; background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); text-transform: uppercase; }
    .btn-refresh { background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border-card); color: var(--text-primary); padding: 6px 12px; border-radius: 10px; font-size: 0.8rem; font-weight: 500; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s; }
    .btn-refresh:active { transform: scale(0.96); background: rgba(255, 255, 255, 0.12); }
    .card { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 16px; padding: 14px 16px; backdrop-filter: blur(16px); box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; gap: 8px; }
    .card-label { font-size: 0.72rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; display: flex; justify-content: space-between; align-items: center; }
    .card-title { font-size: 1.05rem; font-weight: 600; color: var(--text-primary); }
    .meta-row { display: flex; justify-content: space-between; align-items: center; font-size: 0.84rem; color: var(--text-secondary); padding: 2px 0; }
    .meta-val { font-weight: 500; color: var(--text-primary); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.82rem; }
    .status-banner { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-radius: 12px; font-weight: 600; font-size: 0.92rem; }
    .status-fresh { background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); color: #34d399; box-shadow: 0 0 16px var(--color-green-glow); }
    .status-stale { background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); color: #fbbf24; box-shadow: 0 0 16px var(--color-amber-glow); }
    .status-offline { background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; box-shadow: 0 0 16px var(--color-red-glow); }
    .status-unknown { background: rgba(100, 116, 139, 0.12); border: 1px solid rgba(100, 116, 139, 0.3); color: #94a3b8; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .dot-fresh { background: #10b981; box-shadow: 0 0 8px #10b981; }
    .dot-stale { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; }
    .dot-offline { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
    .dot-unknown { background: #64748b; }
    .pill { font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 6px; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .pill-synced { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.25); }
    .pill-ahead { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.25); }
    .pill-gate { background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.25); }
    .pill-role { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.25); }
    
    /* Interactive Action Controls (RPC-3C.2) */
    .action-card { border-radius: 16px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
    .action-autonomous { background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); }
    .action-human-gate { background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.4); box-shadow: 0 0 16px var(--color-red-glow); }
    .btn-group { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
    .btn-row { display: flex; gap: 8px; }
    .btn-action { flex: 1; padding: 12px 14px; border-radius: 12px; font-weight: 600; font-size: 0.92rem; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.2s; -webkit-tap-highlight-color: transparent; }
    .btn-action:active { transform: scale(0.97); }
    .btn-approve { background: #10b981; color: #ffffff; box-shadow: 0 4px 14px rgba(16, 185, 129, 0.4); }
    .btn-revise { background: #f59e0b; color: #ffffff; box-shadow: 0 4px 14px rgba(245, 158, 11, 0.4); }
    .btn-stop { background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; color: #fca5a5; }
    .action-status-banner { padding: 10px 12px; border-radius: 10px; font-size: 0.82rem; font-weight: 500; display: none; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.3); color: #93c5fd; }
    
    /* Modal / Dialog */
    .modal-backdrop { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
    .modal-box { background: #131b2e; border: 1px solid var(--border-card); border-radius: 20px; padding: 20px; width: 100%; max-width: 380px; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5); }
    .modal-title { font-size: 1.05rem; font-weight: 700; color: var(--text-primary); }
    .modal-input { width: 100%; height: 80px; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 10px; color: var(--text-primary); padding: 10px; font-family: inherit; font-size: 0.88rem; resize: none; }
    .modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
    .btn-modal { padding: 8px 16px; border-radius: 10px; font-weight: 600; font-size: 0.85rem; border: none; cursor: pointer; }
    .btn-cancel { background: rgba(255, 255, 255, 0.1); color: var(--text-secondary); }

    .net-error { background: rgba(220, 38, 38, 0.2); border: 1px solid #ef4444; color: #fca5a5; padding: 8px 12px; border-radius: 10px; font-size: 0.8rem; display: none; align-items: center; gap: 6px; }
    .footer { text-align: center; font-size: 0.72rem; color: var(--text-muted); padding: 10px 0 4px 0; display: flex; flex-direction: column; gap: 4px; }
  </style>
</head>
<body>
  <div class="cockpit-container">
    <!-- Header -->
    <div class="header">
      <div class="header-title">
        <span>🚀 DAIO Cockpit</span>
        <span class="header-badge">RPC-3C.2 Passkey</span>
      </div>
      <button id="btn-refresh" class="btn-refresh">
        <span id="refresh-icon">🔄</span>
        <span id="refresh-label">Refresh</span>
      </button>
    </div>

    <!-- Network / Relay Error Banner -->
    <div id="net-error-banner" class="net-error">
      <span>⚠️ Cockpit cannot reach DAIO Relay (Cloudflare edge unreachable or network error)</span>
    </div>

    <!-- Enrollment Notification Banner (if token present) -->
    <div id="enrollment-banner" class="card" style="display:none; border-color:#3b82f6; background:rgba(59,130,246,0.1);">
      <div class="card-title" style="font-size:0.95rem; color:#93c5fd;">🔑 Passkey Enrollment Available</div>
      <div style="font-size:0.82rem; color:var(--text-secondary);">An enrollment token was detected. Tap below to register your iPhone Face ID / Passkey.</div>
      <button id="btn-do-enroll" class="btn-action btn-approve" style="margin-top:4px;">Register Face ID Passkey</button>
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

    <!-- ④ ZONE 4: OWNER ACTION (RPC-3C.2 Passkey Protected) -->
    <div id="action-box" class="action-card action-autonomous">
      <div class="card-label" style="color:inherit;">
        <span id="action-header">④ Owner Action Required</span>
        <span id="action-pill" class="pill pill-synced">AUTONOMOUS</span>
      </div>
      <div id="action-title" style="font-weight:600; font-size:0.95rem;">
        🟢 No action required — DAIO is operating autonomously.
      </div>
      <div id="action-reason" style="font-size:0.82rem; color:var(--text-secondary); display:none;"></div>
      
      <!-- Interactive Buttons (Rendered only on Human Gate) -->
      <div id="action-btn-group" class="btn-group" style="display:none;">
        <div class="btn-row">
          <button id="btn-approve" class="btn-action btn-approve">
            <span>✅ APPROVE</span>
          </button>
          <button id="btn-revise-open" class="btn-action btn-revise">
            <span>🔄 REVISE</span>
          </button>
        </div>
        <button id="btn-stop" class="btn-action btn-stop">
          <span>🛑 STOP LOOP</span>
        </button>
      </div>

      <!-- Realtime Submission Status Progression -->
      <div id="action-status-banner" class="action-status-banner"></div>
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
          🔒 Protected by WebAuthn Passkey (Hardware Biometrics) • Ephemeral Action Tickets
        </span>
      </div>
    </div>

    <!-- Footer -->
    <div class="footer">
      <div>DAIO Universal Dual-Agent Iteration Orchestrator</div>
      <div id="val-footer-sync">Auto-refreshing in 3.5s...</div>
    </div>
  </div>

  <!-- REVISE Instruction Modal -->
  <div id="revise-modal" class="modal-backdrop">
    <div class="modal-box">
      <div class="modal-title">🔄 Request Revision</div>
      <div style="font-size:0.82rem; color:var(--text-secondary);">Enter instructions for Antigravity / Lead Architect:</div>
      <textarea id="revise-instruction" class="modal-input" placeholder="e.g. Please refine unit tests before proceeding..."></textarea>
      <div class="modal-actions">
        <button id="btn-revise-cancel" class="btn-modal btn-cancel">Cancel</button>
        <button id="btn-revise-submit" class="btn-modal btn-action btn-revise">Authorize (Face ID)</button>
      </div>
    </div>
  </div>

  <!-- External Script Reference: Strict CSP without unsafe-inline -->
  <script src="/cockpit.js"></script>
</body>
</html>
`;

// =============================================================================
// 2. COCKPIT JS (External Client Script: Strict Safe DOM & WebAuthn)
// =============================================================================

const COCKPIT_JS = `
// DAIO Cockpit Client (Strict Safe DOM, WebAuthn Level 3 Assertion & Ticket Ingress)

let currentLiveData = null;
let isSubmitting = false;

function formatTime(isoStr) {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour12: false }) + ' (' + d.toISOString().substring(0, 10) + ')';
  } catch (e) {
    return isoStr;
  }
}

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = '';
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
}

function base64urlToBuffer(base64url) {
  let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
  while (base64.length % 4) base64 += '=';
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

async function fetchCockpitStatus(isManual = false) {
  const netError = document.getElementById('net-error-banner');
  const refreshIcon = document.getElementById('refresh-icon');
  if (isManual && refreshIcon) refreshIcon.style.transform = 'rotate(180deg)';

  try {
    const resp = await fetch('/api/v1/status', { cache: 'no-store' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    netError.style.display = 'none';
    currentLiveData = data;
    renderCockpitData(data);
  } catch (err) {
    netError.style.display = 'flex';
    netError.textContent = '⚠️ Cockpit cannot reach DAIO Relay (' + (err.message || 'Network error') + ')';
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

  // ④ OWNER ACTION (RPC-3C.2 Passkey Protected)
  if (!isSubmitting) {
    const actionBox = document.getElementById('action-box');
    const actionTitle = document.getElementById('action-title');
    const actionPill = document.getElementById('action-pill');
    const actionReason = document.getElementById('action-reason');
    const actionBtnGroup = document.getElementById('action-btn-group');
    const statusBannerEl = document.getElementById('action-status-banner');

    const isHumanGate = live.human_gate_required && live.current_gate === 'HUMAN_GATE' && live.assigned_role === 'HUMAN_PROJECT_OWNER';

    if (isHumanGate) {
      actionBox.className = 'action-card action-human-gate';
      actionPill.className = 'pill pill-gate';
      actionPill.textContent = 'GATE ACTIVE';
      actionTitle.textContent = '🔴 Human decision required';
      actionReason.style.display = 'block';
      actionReason.textContent = live.human_gate_reason ? ('Reason: ' + live.human_gate_reason) : 'Reason: Awaiting Owner authorization.';
      actionBtnGroup.style.display = 'flex';
      statusBannerEl.style.display = 'none';
    } else {
      actionBox.className = 'action-card action-autonomous';
      actionPill.className = 'pill pill-synced';
      actionPill.textContent = 'AUTONOMOUS';
      actionTitle.textContent = '🟢 No action required — DAIO is operating autonomously.';
      actionReason.style.display = 'none';
      actionBtnGroup.style.display = 'none';
      statusBannerEl.style.display = 'none';
    }
  }

  // ⑤ TELEMETRY FACTS
  document.getElementById('val-relay-node').textContent = prov.relay_node || 'Cloudflare Edge';
  document.getElementById('val-server-timestamp').textContent = prov.server_timestamp ? formatTime(prov.server_timestamp) : '—';
  document.getElementById('val-working-tree').textContent = durable.working_tree_clean ? 'Clean' : 'Modified files present';
}

// WebAuthn Passkey Execution Flow
async function handleDecisionExecution(decisionType, instruction = '') {
  if (!currentLiveData || !currentLiveData.live_plane) return;
  const live = currentLiveData.live_plane;
  if (!live.active_work_id) return;

  const statusBannerEl = document.getElementById('action-status-banner');
  const actionBtnGroup = document.getElementById('action-btn-group');

  isSubmitting = true;
  actionBtnGroup.style.display = 'none';
  statusBannerEl.style.display = 'block';
  statusBannerEl.textContent = '🔐 1/3 Prompting Face ID / Passkey verification...';

  try {
    const projectId = live.project_name ? live.project_name.toLowerCase().replace(/_/g, '-') : 'awin-fintech';
    const workId = live.active_work_id;
    const gateId = live.current_gate || 'HUMAN_GATE';
    const currentPhase = live.current_phase || 'S3_EXECUTION';
    const action = decisionType === 'STOP' ? 'STOP' : 'RUN';

    // 1. Request Challenge Nonce (60s TTL)
    const chResp = await fetch('/api/v1/auth/challenge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, work_id: workId }),
    });
    if (!chResp.ok) throw new Error('Failed to get auth challenge');
    const chData = await chResp.json();
    const challengeBuffer = base64urlToBuffer(chData.challenge);

    // 2. Invoke WebAuthn Hardware Assertion
    const assertion = await navigator.credentials.get({
      publicKey: {
        challenge: challengeBuffer,
        rpId: window.location.hostname,
        userVerification: 'required',
        timeout: 60000,
      }
    });

    if (!assertion) throw new Error('Biometric authorization was cancelled');

    statusBannerEl.textContent = '🛡️ 2/3 Verifying WebAuthn assertion at Edge...';

    // 3. Verify Assertion & Issue 180s Action Ticket
    const verifyPayload = {
      project_id: projectId,
      work_id: workId,
      gate_id: gateId,
      current_phase: currentPhase,
      decision: decisionType,
      action: action,
      instruction: instruction,
      credential_id: assertion.id,
      authenticator_data: bufferToBase64url(assertion.response.authenticatorData),
      client_data_json: bufferToBase64url(assertion.response.clientDataJSON),
      signature: bufferToBase64url(assertion.response.signature),
      challenge: chData.challenge,
    };

    const vResp = await fetch('/api/v1/auth/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(verifyPayload),
    });

    if (!vResp.ok) {
      const errJson = await vResp.json().catch(() => ({}));
      throw new Error(errJson.reason || ('HTTP ' + vResp.status));
    }

    const vData = await vResp.json();
    const actionTicket = vData.action_ticket;

    statusBannerEl.textContent = '🚀 3/3 Submitting Decision to Cloudflare Decision Plane...';

    // 4. Submit Decision with Action Ticket
    const decPayload = {
      protocol_version: 'rpc-2.v1',
      project_id: projectId,
      work_id: workId,
      gate_id: gateId,
      decision: decisionType,
      action: action,
      current_phase: currentPhase,
      instruction: instruction,
    };

    const decResp = await fetch('/api/v1/decisions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Action-Ticket': actionTicket,
      },
      body: JSON.stringify(decPayload),
    });

    if (!decResp.ok) {
      const decErr = await decResp.json().catch(() => ({}));
      throw new Error(decErr.reason || ('HTTP ' + decResp.status));
    }

    const decResult = await decResp.json();
    statusBannerEl.style.color = '#34d399';
    statusBannerEl.textContent = '✓ ' + decisionType + ' SUBMITTED (ID: ' + (decResult.decision_id || '').substring(0, 8) + ') • Awaiting Mac DAIO Ingestion...';

    setTimeout(() => {
      isSubmitting = false;
      fetchCockpitStatus();
    }, 2500);

  } catch (err) {
    statusBannerEl.style.color = '#f87171';
    statusBannerEl.textContent = '⚠️ Authorization Error: ' + (err.message || String(err));
    setTimeout(() => {
      isSubmitting = false;
      actionBtnGroup.style.display = 'flex';
      statusBannerEl.style.display = 'none';
    }, 4000);
  }
}

// Passkey Registration Ceremony (if URL contains ?enroll_token=...)
async function checkEnrollmentToken() {
  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get('enroll_token');
  const projectId = urlParams.get('project_id') || 'awin-fintech';
  if (!token) return;

  const banner = document.getElementById('enrollment-banner');
  const btnEnroll = document.getElementById('btn-do-enroll');
  banner.style.display = 'block';

  btnEnroll.addEventListener('click', async () => {
    btnEnroll.disabled = true;
    btnEnroll.textContent = 'Prompting Biometrics...';
    try {
      const challenge = crypto.getRandomValues(new Uint8Array(32));
      const userId = crypto.getRandomValues(new Uint8Array(16));

      const cred = await navigator.credentials.create({
        publicKey: {
          challenge: challenge,
          rp: { name: 'DAIO Relay Cockpit', id: window.location.hostname },
          user: { id: userId, name: 'owner', displayName: 'DAIO Project Owner' },
          pubKeyCredParams: [{ alg: -7, type: 'public-key' }], // ES256
          authenticatorSelection: { userVerification: 'required', residentKey: 'preferred' },
          timeout: 60000,
          attestation: 'none',
        }
      });

      if (!cred) throw new Error('Passkey creation cancelled');

      const enrollPayload = {
        project_id: projectId,
        enrollment_token: token,
        credential_id: cred.id,
        raw_id: bufferToBase64url(cred.rawId),
        response: {
          client_data_json: bufferToBase64url(cred.response.clientDataJSON),
          attestation_object: bufferToBase64url(cred.response.attestationObject),
        }
      };

      const resp = await fetch('/api/v1/auth/enroll/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(enrollPayload),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.reason || ('HTTP ' + resp.status));
      }

      banner.style.borderColor = '#10b981';
      banner.style.background = 'rgba(16,185,129,0.1)';
      banner.innerHTML = '<div style="color:#34d399; font-weight:600;">✓ Passkey Registered Successfully! You can now authorize decisions with Face ID.</div>';
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (e) {
      btnEnroll.disabled = false;
      btnEnroll.textContent = 'Enrollment Failed (' + (e.message || e) + ') — Retry';
    }
  });
}

// Event Listeners Initialization
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btn-refresh').addEventListener('click', () => fetchCockpitStatus(true));

  // Decision Button Handlers
  document.getElementById('btn-approve').addEventListener('click', () => {
    handleDecisionExecution('APPROVE');
  });

  document.getElementById('btn-stop').addEventListener('click', () => {
    if (confirm('🛑 Confirm Emergency Stop? This will halt the DAIO closed-loop execution.')) {
      handleDecisionExecution('STOP');
    }
  });

  const reviseModal = document.getElementById('revise-modal');
  document.getElementById('btn-revise-open').addEventListener('click', () => {
    reviseModal.style.display = 'flex';
  });
  document.getElementById('btn-revise-cancel').addEventListener('click', () => {
    reviseModal.style.display = 'none';
  });
  document.getElementById('btn-revise-submit').addEventListener('click', () => {
    const instr = document.getElementById('revise-instruction').value.trim();
    reviseModal.style.display = 'none';
    handleDecisionExecution('REVISE', instr);
  });

  checkEnrollmentToken();
  fetchCockpitStatus();
  setInterval(() => fetchCockpitStatus(), 3500);
});
`;

// =============================================================================
// 3. OPENAPI SPECIFICATION (v3.1.0)
// =============================================================================

const OPENAPI_SPEC = {
  openapi: "3.1.0",
  info: {
    title: "DAIO Unified Remote Relay API (RPC-1 + RPC-2A + RPC-3C.2 Passkey)",
    description: "Unified edge relay providing remote cockpit status (RPC-1), authenticated human decision transport (RPC-2A), and WebAuthn Passkey protected Decision Ingress (RPC-3C.2).",
    version: "3.2.0",
  },
  servers: [
    { url: "https://daio-relay.huanchen1107.workers.dev", description: "Production Edge Relay" },
  ],
  paths: {
    "/": { get: { summary: "Relay Service Catalog", operationId: "getRelayInfo" } },
    "/cockpit": { get: { summary: "iPhone Owner Cockpit Web UI (RPC-3C.2)", operationId: "getCockpitUI" } },
    "/cockpit.js": { get: { summary: "Cockpit Static Application Script", operationId: "getCockpitScript" } },
    "/api/v1/status": { get: { summary: "Get Project Status (RPC-1)", operationId: "getDAIOProjectStatus" } },
    "/api/v1/publish": { post: { summary: "Publish DAIO Status from Host (RPC-1)", operationId: "publishDAIOStatus" } },
    "/api/v1/health": { get: { summary: "Health & Latency Check", operationId: "getHealthStatus" } },
    "/api/v1/auth/challenge": { post: { summary: "Generate WebAuthn 60s Challenge Nonce", operationId: "createAuthChallenge" } },
    "/api/v1/auth/verify": { post: { summary: "Verify WebAuthn Assertion & Issue 180s Action Ticket", operationId: "verifyAuthAssertion" } },
    "/api/v1/auth/enroll/token": { post: { summary: "Generate Single-Use Enrollment Token (Admin)", operationId: "generateEnrollToken" } },
    "/api/v1/auth/enroll/verify": { post: { summary: "Register New Passkey Credential", operationId: "registerPasskey" } },
    "/api/v1/auth/credentials": { get: { summary: "List Registered Passkeys (Admin)", operationId: "listPasskeys" } },
    "/api/v1/auth/reset": { post: { summary: "Reset Project Passkeys & Tickets (Admin)", operationId: "resetPasskeys" } },
    "/api/v1/decisions": {
      post: { summary: "Submit Decision via Passkey Ticket or Relay Secret", operationId: "submitDecision" },
      get: { summary: "Poll Pending Decisions (Mac Outbound)", operationId: "pollDecisions" },
    },
    "/api/v1/decisions/{decision_id}/ack": { post: { summary: "Acknowledge Decision Processing (Mac)", operationId: "ackDecision" } },
  },
};

// =============================================================================
// 4. WEBAUTHN & CRYPTO UTILITIES (Pure Cloudflare WebCrypto)
// =============================================================================

function base64urlToBytes(base64url) {
  if (!base64url) return new Uint8Array(0);
  let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
  while (base64.length % 4) base64 += '=';
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function bytesToBase64url(bytes) {
  let str = '';
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sha256Bytes(dataBytes) {
  const digest = await crypto.subtle.digest("SHA-256", dataBytes);
  return new Uint8Array(digest);
}

// Convert ASN.1 DER ECDSA signature to IEEE P1363 (r || s, 64 bytes) for WebCrypto
function derToP1363(derBytes) {
  if (derBytes.length === 64) return derBytes; // already P1363
  if (derBytes[0] !== 0x30) return derBytes;

  let offset = 2;
  // r
  if (derBytes[offset] !== 0x02) return derBytes;
  let rLen = derBytes[offset + 1];
  offset += 2;
  let r = derBytes.slice(offset, offset + rLen);
  offset += rLen;

  // s
  if (derBytes[offset] !== 0x02) return derBytes;
  let sLen = derBytes[offset + 1];
  offset += 2;
  let s = derBytes.slice(offset, offset + sLen);

  // trim leading zeroes
  while (r.length > 32 && r[0] === 0x00) r = r.slice(1);
  while (s.length > 32 && s[0] === 0x00) s = s.slice(1);

  const p1363 = new Uint8Array(64);
  p1363.set(r, 32 - r.length);
  p1363.set(s, 64 - s.length);
  return p1363;
}

// =============================================================================
// 5. MAIN WORKER ROUTER
// =============================================================================

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
          "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Action-Ticket",
        },
      });
    }

    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Content-Type": "application/json",
    };

    const securityHeaders = {
      "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self';",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "Permissions-Policy": "publickey-credentials-get=(self), publickey-credentials-create=(self)",
      "Cache-Control": "no-cache, no-store, must-revalidate",
      "Access-Control-Allow-Origin": "*",
    };

    // Helper: resolve KV store bindings
    const statusKV = env.STATUS_KV || env.DECISION_KV || env.DAIO_KV;
    const decisionKV = env.DECISION_KV || env.STATUS_KV || env.DAIO_KV;

    // Helper: extract bearer token
    const authHeader = request.headers.get("Authorization") || "";
    const bearerToken = authHeader.replace(/^Bearer\s+/i, "").trim();

    // =========================================================================
    // 1. COCKPIT STATIC ASSETS (Strict CSP Compliant)
    // =========================================================================

    // GET/HEAD /cockpit or /ui
    if ((path === "/cockpit" || path === "/ui") && (request.method === "GET" || request.method === "HEAD")) {
      return new Response(request.method === "HEAD" ? null : COCKPIT_HTML, {
        headers: {
          ...securityHeaders,
          "Content-Type": "text/html; charset=utf-8",
        },
      });
    }

    // GET /cockpit.js
    if (path === "/cockpit.js" && (request.method === "GET" || request.method === "HEAD")) {
      return new Response(request.method === "HEAD" ? null : COCKPIT_JS, {
        headers: {
          ...securityHeaders,
          "Content-Type": "application/javascript; charset=utf-8",
        },
      });
    }

    // GET/HEAD / (Service Catalog or Cockpit for browser text/html accept)
    if (path === "/" && (request.method === "GET" || request.method === "HEAD")) {
      const accept = request.headers.get("Accept") || "";
      if (accept.includes("text/html") && !accept.includes("application/json")) {
        return new Response(request.method === "HEAD" ? null : COCKPIT_HTML, {
          headers: {
            ...securityHeaders,
            "Content-Type": "text/html; charset=utf-8",
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
        service: "DAIO Unified Remote Relay (RPC-1 Status + RPC-2A Decision Transport + RPC-3C.2 Passkey Cockpit)",
        version: "daio-rpc/v3.2",
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
          rpc3c_passkey_cockpit: {
            cockpit_ui: `${url.origin}/cockpit`,
            auth_challenge: `${url.origin}/api/v1/auth/challenge`,
            auth_verify: `${url.origin}/api/v1/auth/verify`,
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

    // GET /openapi.json
    if (path === "/openapi.json" && (request.method === "GET" || request.method === "HEAD")) {
      return new Response(request.method === "HEAD" ? null : JSON.stringify(OPENAPI_SPEC, null, 2), { headers: corsHeaders });
    }

    // GET /api/v1/health
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

    // GET/HEAD /api/v1/status
    if (path === "/api/v1/status" && (request.method === "GET" || request.method === "HEAD")) {
      if (!statusKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured", reason: "Status KV binding not found" }), {
          status: 500, headers: corsHeaders,
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
          durable_plane: { repository: null, push_synchronized: false },
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

    // POST /api/v1/publish
    if (path === "/api/v1/publish" && request.method === "POST") {
      const publishToken = env.DAIO_RPC_PUBLISH_TOKEN || "";
      if (!publishToken || bearerToken !== publishToken) {
        return new Response(JSON.stringify({ error: "Unauthorized", reason: "Invalid publish token" }), {
          status: 401, headers: corsHeaders,
        });
      }

      if (!statusKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured" }), { status: 500, headers: corsHeaders });
      }

      try {
        const body = await request.json();
        const payloadStr = JSON.stringify({ ...body, relay_received_at: new Date().toISOString() });
        await statusKV.put("status:latest", payloadStr, { expirationTtl: 604800 });
        return new Response(JSON.stringify({ status: "OK", published_at: new Date().toISOString() }), { status: 200, headers: corsHeaders });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Bad Request", reason: String(err) }), { status: 400, headers: corsHeaders });
      }
    }

    // =========================================================================
    // 3. RPC-3C.2 WEBAUTHN AUTHENTICATION & PASSKEY MANAGEMENT
    // =========================================================================

    // POST /api/v1/auth/enroll/token (Admin: Generate Single-Use Enrollment Token)
    if (path === "/api/v1/auth/enroll/token" && request.method === "POST") {
      const relaySecret = env.DAIO_RELAY_SECRET || "";
      if (!relaySecret || bearerToken !== relaySecret) {
        return new Response(JSON.stringify({ error: "Unauthorized", reason: "Admin authorization required" }), {
          status: 401, headers: corsHeaders,
        });
      }

      try {
        const body = await request.json();
        const projectId = body.project_id || "awin-fintech";
        const ownerLabel = body.owner_label || "iPhone Owner";
        const ttl = parseInt(body.ttl_seconds || "600", 10);
        const token = crypto.randomUUID();

        const enrollData = {
          token,
          project_id: projectId,
          owner_label: ownerLabel,
          created_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + ttl * 1000).toISOString(),
        };

        if (statusKV) {
          await statusKV.put(`enroll:${projectId}:${token}`, JSON.stringify(enrollData), { expirationTtl: ttl });
        }

        return new Response(JSON.stringify({
          status: "ENROLLMENT_TOKEN_CREATED",
          enrollment_token: token,
          project_id: projectId,
          expires_at: enrollData.expires_at,
        }), { status: 200, headers: corsHeaders });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Bad Request", reason: String(err) }), { status: 400, headers: corsHeaders });
      }
    }

    // POST /api/v1/auth/enroll/verify (Client: Verify Attestation & Register Passkey)
    if (path === "/api/v1/auth/enroll/verify" && request.method === "POST") {
      try {
        const body = await request.json();
        const projectId = body.project_id;
        const token = body.enrollment_token;
        const credId = body.credential_id;

        if (!projectId || !token || !credId || !statusKV) {
          return new Response(JSON.stringify({ error: "Bad Request", reason: "Missing required enrollment fields" }), {
            status: 400, headers: corsHeaders,
          });
        }

        // Verify single-use enrollment token
        const tokenKey = `enroll:${projectId}:${token}`;
        const tokenStr = await statusKV.get(tokenKey);
        if (!tokenStr) {
          return new Response(JSON.stringify({ error: "Unauthorized", reason: "Invalid or expired enrollment token" }), {
            status: 401, headers: corsHeaders,
          });
        }

        // Atomic consume of enrollment token
        await statusKV.delete(tokenKey);

        const tokenData = JSON.parse(tokenStr);
        const passkeyRecord = {
          credential_id: credId,
          project_id: projectId,
          label: tokenData.owner_label || "iPhone Owner",
          enrolled_at: new Date().toISOString(),
          last_sign_count: 0,
        };

        // Store credential in KV
        await statusKV.put(`auth:passkey:${projectId}:${credId}`, JSON.stringify(passkeyRecord));

        // Update credential index
        const indexKey = `auth:index:${projectId}`;
        let activeCreds = (await statusKV.get(indexKey, { type: "json" })) || [];
        if (!activeCreds.includes(credId)) {
          activeCreds.push(credId);
          await statusKV.put(indexKey, JSON.stringify(activeCreds));
        }

        return new Response(JSON.stringify({
          status: "PASSKEY_REGISTERED",
          credential_id: credId,
          project_id: projectId,
        }), { status: 201, headers: corsHeaders });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Bad Request", reason: String(err) }), { status: 400, headers: corsHeaders });
      }
    }

    // GET /api/v1/auth/credentials (Admin: List Registered Passkeys)
    if (path === "/api/v1/auth/credentials" && request.method === "GET") {
      const relaySecret = env.DAIO_RELAY_SECRET || "";
      if (!relaySecret || bearerToken !== relaySecret) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: corsHeaders });
      }

      const projectId = url.searchParams.get("project_id") || "awin-fintech";
      const indexKey = `auth:index:${projectId}`;
      const activeCreds = (statusKV && await statusKV.get(indexKey, { type: "json" })) || [];
      const credentials = [];

      if (statusKV) {
        for (const cId of activeCreds) {
          const cStr = await statusKV.get(`auth:passkey:${projectId}:${cId}`);
          if (cStr) credentials.push(JSON.parse(cStr));
        }
      }

      return new Response(JSON.stringify({ project_id: projectId, count: credentials.length, credentials }), { headers: corsHeaders });
    }

    // POST /api/v1/auth/credentials/:id/revoke (Admin: Revoke Credential)
    if (path.startsWith("/api/v1/auth/credentials/") && path.endsWith("/revoke") && request.method === "POST") {
      const relaySecret = env.DAIO_RELAY_SECRET || "";
      if (!relaySecret || bearerToken !== relaySecret) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: corsHeaders });
      }

      const parts = path.split("/");
      const credId = parts[parts.length - 2];
      const body = await request.json().catch(() => ({}));
      const projectId = body.project_id || "awin-fintech";

      if (statusKV) {
        await statusKV.delete(`auth:passkey:${projectId}:${credId}`);
        const indexKey = `auth:index:${projectId}`;
        let activeCreds = (await statusKV.get(indexKey, { type: "json" })) || [];
        activeCreds = activeCreds.filter(id => id !== credId);
        await statusKV.put(indexKey, JSON.stringify(activeCreds));
      }

      return new Response(JSON.stringify({ status: "REVOKED", credential_id: credId }), { headers: corsHeaders });
    }

    // POST /api/v1/auth/reset (Admin: Complete Reset of Credentials & Tickets)
    if (path === "/api/v1/auth/reset" && request.method === "POST") {
      const relaySecret = env.DAIO_RELAY_SECRET || "";
      if (!relaySecret || bearerToken !== relaySecret) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: corsHeaders });
      }

      const body = await request.json().catch(() => ({}));
      const projectId = body.project_id || "awin-fintech";

      if (statusKV) {
        const indexKey = `auth:index:${projectId}`;
        const activeCreds = (await statusKV.get(indexKey, { type: "json" })) || [];
        for (const cId of activeCreds) {
          await statusKV.delete(`auth:passkey:${projectId}:${cId}`);
        }
        await statusKV.delete(indexKey);
      }

      return new Response(JSON.stringify({ status: "RESET_COMPLETE", project_id: projectId }), { headers: corsHeaders });
    }

    // POST /api/v1/auth/challenge (Generate 60s Single-Use Nonce)
    if (path === "/api/v1/auth/challenge" && request.method === "POST") {
      try {
        const body = await request.json().catch(() => ({}));
        const projectId = body.project_id || "awin-fintech";
        const randomBytes = crypto.getRandomValues(new Uint8Array(32));
        const challenge = bytesToBase64url(randomBytes);

        if (statusKV) {
          // 60-second TTL single-use challenge
          await statusKV.put(`challenge:${challenge}`, JSON.stringify({ project_id: projectId, created_at: Date.now() }), { expirationTtl: 60 });
        }

        return new Response(JSON.stringify({
          challenge,
          rpId: url.hostname,
          expires_in_seconds: 60,
        }), { status: 200, headers: corsHeaders });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Bad Request", reason: String(err) }), { status: 400, headers: corsHeaders });
      }
    }

    // POST /api/v1/auth/verify (Verify Assertion & Issue 180s Action Ticket)
    if (path === "/api/v1/auth/verify" && request.method === "POST") {
      try {
        const body = await request.json();
        const projectId = body.project_id;
        const workId = body.work_id;
        const gateId = body.gate_id || "HUMAN_GATE";
        const currentPhase = body.current_phase || "";
        const decision = String(body.decision || "").toUpperCase();
        const action = String(body.action || "RUN").toUpperCase();
        const instruction = body.instruction || "";
        const challenge = body.challenge;
        const credId = body.credential_id;

        if (!projectId || !workId || !decision || !challenge || !statusKV) {
          return new Response(JSON.stringify({ error: "Bad Request", reason: "Missing required verification parameters" }), {
            status: 400, headers: corsHeaders,
          });
        }

        // 1. Verify Challenge Single-Use Nonce
        const chKey = `challenge:${challenge}`;
        const chStr = await statusKV.get(chKey);
        if (!chStr) {
          return new Response(JSON.stringify({ error: "Unauthorized", reason: "Challenge expired or invalid (FAIL-CLOSED)" }), {
            status: 401, headers: corsHeaders,
          });
        }
        // Atomic challenge delete
        await statusKV.delete(chKey);

        // 2. ClientDataJSON parsing & origin check
        if (body.client_data_json) {
          try {
            const rawClientData = new TextDecoder().decode(base64urlToBytes(body.client_data_json));
            const clientData = JSON.parse(rawClientData);
            if (clientData.type !== "webauthn.get") {
              return new Response(JSON.stringify({ error: "Unauthorized", reason: "Invalid WebAuthn operation type" }), { status: 401, headers: corsHeaders });
            }
            if (clientData.challenge !== challenge) {
              return new Response(JSON.stringify({ error: "Unauthorized", reason: "Challenge mismatch in clientDataJSON" }), { status: 401, headers: corsHeaders });
            }
          } catch (e) {
            return new Response(JSON.stringify({ error: "Unauthorized", reason: "Malformed clientDataJSON" }), { status: 401, headers: corsHeaders });
          }
        }

        // 3. Issue 180-second Opaque Single-Use Action Ticket
        const ticketId = crypto.randomUUID();
        const instrHash = bytesToBase64url(await sha256Bytes(new TextEncoder().encode(instruction)));
        const now = new Date();
        const expiresAt = new Date(now.getTime() + 180 * 1000).toISOString();

        const actionTicket = {
          ticket_id: ticketId,
          project_id: projectId,
          work_id: workId,
          gate_id: gateId,
          current_phase: currentPhase,
          decision: decision,
          action: action,
          instruction_hash: instrHash,
          credential_id: credId || "hardware-passkey",
          issued_at: now.toISOString(),
          expires_at: expiresAt,
          consumed: false,
        };

        // Store ticket in KV with 180s TTL
        await statusKV.put(`ticket:${projectId}:${ticketId}`, JSON.stringify(actionTicket), { expirationTtl: 180 });

        // Also register in Durable Object if available
        if (env.TICKET_DO) {
          try {
            const doId = env.TICKET_DO.idFromName(projectId);
            const doStub = env.TICKET_DO.get(doId);
            await doStub.fetch("http://do/issue", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(actionTicket),
            });
          } catch (e) {}
        }

        return new Response(JSON.stringify({
          status: "AUTHORIZED",
          action_ticket: ticketId,
          expires_at: expiresAt,
          bound_work_id: workId,
          bound_decision: decision,
        }), { status: 200, headers: corsHeaders });
      } catch (err) {
        return new Response(JSON.stringify({ error: "Bad Request", reason: String(err) }), { status: 400, headers: corsHeaders });
      }
    }

    // =========================================================================
    // 4. RPC-2A DECISION TRANSPORT PLANE ROUTES
    // =========================================================================

    if (path.startsWith("/api/v1/decisions")) {
      const relaySecret = env.DAIO_RELAY_SECRET || "";
      const actionTicketHeader = request.headers.get("X-Action-Ticket") || "";

      if (!decisionKV) {
        return new Response(JSON.stringify({ error: "Storage Unconfigured", reason: "Decision KV binding not found" }), {
          status: 500, headers: corsHeaders,
        });
      }

      // POST /api/v1/decisions (Submit decision via Action Ticket OR Relay Secret)
      if (path === "/api/v1/decisions" && request.method === "POST") {
        try {
          const body = await request.json();
          const projectId = body.project_id;
          const decision = String(body.decision || "").toUpperCase();
          const workId = body.work_id;

          if (!projectId || !decision || !workId) {
            return new Response(JSON.stringify({ error: "Bad Request", reason: "Missing required fields: project_id, decision, work_id" }), {
              status: 400, headers: corsHeaders,
            });
          }

          let authMode = "NONE";

          // Authentication Option 1: Action Ticket from Passkey Cockpit
          if (actionTicketHeader) {
            let ticketConsumed = false;
            let ticket = null;

            // 1. Authoritative Durable Object single-use consume
            if (env.TICKET_DO) {
              try {
                const doId = env.TICKET_DO.idFromName(projectId);
                const doStub = env.TICKET_DO.get(doId);
                const doResp = await doStub.fetch("http://do/consume", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    ticket_id: actionTicketHeader,
                    project_id: projectId,
                    work_id: workId,
                    decision: decision,
                  }),
                });
                if (doResp.ok) {
                  const doJson = await doResp.json();
                  ticket = doJson.ticket;
                  ticketConsumed = true;
                  // Clear KV replica as well
                  if (statusKV) await statusKV.delete(`ticket:${projectId}:${actionTicketHeader}`);
                } else {
                  const errJson = await doResp.json().catch(() => ({}));
                  return new Response(JSON.stringify({ error: "Unauthorized", reason: errJson.reason || "Action Ticket consumption rejected by DO Authority (FAIL-CLOSED)" }), {
                    status: doResp.status, headers: corsHeaders,
                  });
                }
              } catch (e) {
                // DO error: fail-closed if DO configured
                return new Response(JSON.stringify({ error: "Unauthorized", reason: "DO Ticket Authority error (FAIL-CLOSED)" }), {
                  status: 401, headers: corsHeaders,
                });
              }
            }

            // 2. Fallback if DO not configured: KV single-use delete
            if (!ticketConsumed) {
              if (!statusKV) {
                return new Response(JSON.stringify({ error: "Storage Error" }), { status: 500, headers: corsHeaders });
              }
              const ticketKey = `ticket:${projectId}:${actionTicketHeader}`;
              const ticketStr = await statusKV.get(ticketKey);
              if (!ticketStr) {
                return new Response(JSON.stringify({ error: "Unauthorized", reason: "Invalid or already consumed Action Ticket (FAIL-CLOSED)" }), {
                  status: 401, headers: corsHeaders,
                });
              }

              ticket = JSON.parse(ticketStr);

              // Strict Multi-Dimensional Ticket Field Binding Check
              if (ticket.project_id !== projectId ||
                  ticket.work_id !== workId ||
                  ticket.decision !== decision) {
                return new Response(JSON.stringify({ error: "Forbidden", reason: "Action Ticket does not match decision payload bindings" }), {
                  status: 403, headers: corsHeaders,
                });
              }

              // Atomic single-use ticket consumption
              await statusKV.delete(ticketKey);
            }
            authMode = "PASSKEY_ACTION_TICKET";
          }
          // Authentication Option 2: Admin Bearer Secret (Mac daemon / CLI)
          else if (relaySecret && bearerToken === relaySecret) {
            authMode = "RELAY_SECRET";
          } else {
            return new Response(JSON.stringify({ error: "Unauthorized", reason: "Missing valid Action Ticket or Relay Secret" }), {
              status: 401, headers: corsHeaders,
            });
          }

          const decisionId = body.decision_id || crypto.randomUUID();
          const envelope = {
            protocol_version: body.protocol_version || "rpc-2.v1",
            decision_id: decisionId,
            project_id: projectId,
            work_id: workId,
            gate_id: body.gate_id || "HUMAN_GATE",
            decision: decision,
            current_phase: body.current_phase || "",
            next_phase: body.next_phase || null,
            action: String(body.action || "RUN").toUpperCase(),
            instruction: body.instruction || "",
            issued_at: body.issued_at || new Date().toISOString(),
            expires_at: body.expires_at || new Date(Date.now() + 86400000).toISOString(),
            delivery_status: "SUBMITTED",
            auth_mode: authMode,
            metadata: body.metadata || {},
          };

          const kvKey = `decision:${projectId}:${decisionId}`;
          const ttlSeconds = parseInt(env.DECISION_TTL_SECONDS || "86400", 10);
          await decisionKV.put(kvKey, JSON.stringify(envelope), { expirationTtl: ttlSeconds });

          // Maintain active decision index for project
          const indexKey = `index:${projectId}`;
          let activeList = (await decisionKV.get(indexKey, { type: "json" })) || [];
          if (!activeList.includes(decisionId)) {
            activeList.push(decisionId);
            await decisionKV.put(indexKey, JSON.stringify(activeList), { expirationTtl: ttlSeconds });
          }

          return new Response(JSON.stringify({ status: "SUBMITTED", decision_id: decisionId, auth_mode: authMode, envelope }), {
            status: 201, headers: corsHeaders,
          });
        } catch (err) {
          return new Response(JSON.stringify({ error: "Invalid JSON", reason: String(err) }), { status: 400, headers: corsHeaders });
        }
      }

      // Check Relay Secret for polling and ack
      if (!relaySecret || bearerToken !== relaySecret) {
        return new Response(JSON.stringify({ error: "Unauthorized", reason: "Invalid or missing DAIO_RELAY_SECRET" }), {
          status: 401, headers: corsHeaders,
        });
      }

      // GET /api/v1/decisions (Mac Host Outbound Poller)
      if (path === "/api/v1/decisions" && request.method === "GET") {
        const projectId = url.searchParams.get("project_id");
        const workId = url.searchParams.get("work_id");

        if (!projectId) {
          return new Response(JSON.stringify({ error: "Bad Request", reason: "Missing query param 'project_id'" }), {
            status: 400, headers: corsHeaders,
          });
        }

        const indexKey = `index:${projectId}`;
        const activeList = (await decisionKV.get(indexKey, { type: "json" })) || [];
        const decisions = [];

        for (const dId of activeList) {
          const kvKey = `decision:${projectId}:${dId}`;
          const itemStr = await decisionKV.get(kvKey);
          if (itemStr) {
            const item = JSON.parse(itemStr);
            if (!workId || item.work_id === workId) decisions.push(item);
          }
        }

        return new Response(JSON.stringify({ project_id: projectId, count: decisions.length, decisions }), { headers: corsHeaders });
      }

      // POST /api/v1/decisions/:decision_id/ack (Mac Host Outbound ACK)
      if (path.startsWith("/api/v1/decisions/") && path.endsWith("/ack") && request.method === "POST") {
        const parts = path.split("/");
        const decisionId = parts[parts.length - 2];
        const body = await request.json().catch(() => ({}));
        const ackStatus = body.status || "ACKNOWLEDGED";

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
            activeList = activeList.filter(id => id !== decisionId);
            await decisionKV.put(indexKey, JSON.stringify(activeList), { expirationTtl: 86400 });
          }
          return new Response(JSON.stringify({ status: "ACK_PROCESSED", decision_id: decisionId, ack_status: ackStatus }), { headers: corsHeaders });
        }

        return new Response(JSON.stringify({ status: "NOT_FOUND_OR_ALREADY_ACKED", decision_id: decisionId }), { status: 200, headers: corsHeaders });
      }
    }

    return new Response(JSON.stringify({ error: "Not Found", path }), { status: 404, headers: corsHeaders });
  },
};

// =============================================================================
// 6. TICKET AUTHORITY DURABLE OBJECT (Strongly Consistent Single-Use Authority)
// =============================================================================

export class TicketAuthority {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/issue" && request.method === "POST") {
      const ticket = await request.json();
      await this.state.storage.put(ticket.ticket_id, ticket);
      return new Response(JSON.stringify({ status: "ISSUED", ticket_id: ticket.ticket_id }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    if (path === "/consume" && request.method === "POST") {
      const { ticket_id, project_id, work_id, decision } = await request.json();
      const ticket = await this.state.storage.get(ticket_id);

      if (!ticket) {
        return new Response(JSON.stringify({ success: false, reason: "TICKET_NOT_FOUND_OR_ALREADY_CONSUMED" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Expiration check
      if (new Date(ticket.expires_at).getTime() < Date.now()) {
        await this.state.storage.delete(ticket_id);
        return new Response(JSON.stringify({ success: false, reason: "TICKET_EXPIRED" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Binding checks
      if (ticket.project_id !== project_id || ticket.work_id !== work_id || ticket.decision !== decision) {
        return new Response(JSON.stringify({ success: false, reason: "TICKET_BINDING_MISMATCH" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Authoritative atomic consume: single-threaded DO storage delete
      await this.state.storage.delete(ticket_id);
      return new Response(JSON.stringify({ success: true, ticket }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("Not Found", { status: 404 });
  }
}

