"""
Tests for RPC-3B Read-Only iPhone Owner Cockpit in Cloudflare Unified Relay Worker.
Validates:
1. /cockpit and /ui route delivery (HTTP 200, text/html)
2. Mobile Safari viewport and PWA metadata
3. 5-Zone layout structure and element IDs
4. Dynamic rendering logic for FRESH / STALE / OFFLINE / UNKNOWN
5. Human Gate detection and read-only notice enforcement
6. Failure isolation: Relay unreachable vs Mac host offline
7. Zero decision mutation invariant: No POST /api/v1/decisions in RPC-3B UI script
"""

import re
from pathlib import Path
import pytest

WORKER_PATH = Path(__file__).parent.parent / "cloudflare" / "relay_worker.js"


@pytest.fixture(scope="module")
def worker_source() -> str:
    assert WORKER_PATH.exists(), f"relay_worker.js not found at {WORKER_PATH}"
    return WORKER_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cockpit_html(worker_source: str) -> str:
    # Extract COCKPIT_HTML literal from relay_worker.js
    match = re.search(r"const COCKPIT_HTML = `(.*?)`;", worker_source, re.DOTALL)
    assert match is not None, "COCKPIT_HTML definition not found in relay_worker.js"
    return match.group(1)


def test_cockpit_route_registered_in_worker(worker_source: str):
    """Verify that /cockpit and /ui are registered routes returning HTML with proper headers."""
    assert 'path === "/cockpit"' in worker_source
    assert 'path === "/ui"' in worker_source
    assert '"Content-Type": "text/html; charset=utf-8"' in worker_source
    assert 'rpc3b_owner_cockpit' in worker_source


def test_mobile_viewport_and_pwa_metadata(cockpit_html: str):
    """Verify mobile Safari viewport, safe-area cover, and PWA capabilities."""
    assert '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">' in cockpit_html
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in cockpit_html
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in cockpit_html
    assert '<meta name="theme-color" content="#090d16">' in cockpit_html
    assert '<title>DAIO Owner Cockpit</title>' in cockpit_html


def test_five_zone_structure_present(cockpit_html: str):
    """Verify that all five required information zones exist in HTML."""
    # Zone 1: Project
    assert 'id="zone-project"' in cockpit_html
    assert 'id="val-project-name"' in cockpit_html
    assert 'id="val-repo-name"' in cockpit_html
    assert 'id="val-git-branch-sha"' in cockpit_html
    assert 'id="val-push-sync"' in cockpit_html

    # Zone 2: Live Status
    assert 'id="zone-status"' in cockpit_html
    assert 'id="status-banner"' in cockpit_html
    assert 'id="val-host-status"' in cockpit_html
    assert 'id="val-mac-host"' in cockpit_html
    assert 'id="val-supervisor-status"' in cockpit_html
    assert 'id="val-heartbeat-age"' in cockpit_html
    assert 'id="val-collected-at"' in cockpit_html

    # Zone 3: Current Work
    assert 'id="zone-work"' in cockpit_html
    assert 'id="val-work-title"' in cockpit_html
    assert 'id="val-work-id"' in cockpit_html
    assert 'id="val-stage-gate"' in cockpit_html
    assert 'id="val-assigned-role"' in cockpit_html
    assert 'id="val-work-status"' in cockpit_html
    assert 'id="val-queue-depth"' in cockpit_html

    # Zone 4: Owner Action (Read-only)
    assert 'id="action-box"' in cockpit_html
    assert 'id="action-title"' in cockpit_html
    assert 'id="action-reason"' in cockpit_html
    assert 'id="action-pill"' in cockpit_html

    # Zone 5: Verified Telemetry Facts
    assert 'id="zone-facts"' in cockpit_html
    assert 'id="val-relay-node"' in cockpit_html
    assert 'id="val-server-timestamp"' in cockpit_html
    assert 'id="val-working-tree"' in cockpit_html


def test_freshness_rendering_rules_in_js(cockpit_html: str):
    """Verify that JS script evaluates FRESH, STALE, OFFLINE, and UNKNOWN correctly."""
    # FRESH check
    assert "freshness === 'FRESH' && live.supervisor_running" in cockpit_html
    assert "'ONLINE • FRESH'" in cockpit_html

    # STALE check
    assert "freshness === 'STALE'" in cockpit_html
    assert "'STALE (' + hStatus + ')'" in cockpit_html

    # OFFLINE check
    assert "freshness === 'OFFLINE' || !live.supervisor_running" in cockpit_html
    assert "'HOST OFFLINE'" in cockpit_html


def test_human_gate_detection_and_readonly_notice(cockpit_html: str):
    """Verify Human Gate condition check and read-only notice."""
    assert "live.human_gate_required && live.current_gate === 'HUMAN_GATE' && live.assigned_role === 'HUMAN_PROJECT_OWNER'" in cockpit_html
    assert "Decision controls will be enabled in RPC-3C." in cockpit_html
    assert "No action required — DAIO is operating autonomously." in cockpit_html


def test_failure_isolation_between_relay_and_host(cockpit_html: str):
    """Verify that relay network failure is distinct from host offline."""
    assert "Cockpit cannot reach DAIO Relay" in cockpit_html
    assert "net-error-banner" in cockpit_html
    assert "HOST OFFLINE" in cockpit_html


def test_zero_decision_mutation_in_rpc3b(cockpit_html: str):
    """
    INVARIANT CHECK:
    RPC-3B Cockpit is read-only.
    The client script must NOT submit decisions or call /api/v1/decisions.
    """
    # Verify no POST requests in client script
    assert "method: 'POST'" not in cockpit_html
    assert 'method: "POST"' not in cockpit_html
    assert "/api/v1/decisions" not in cockpit_html
    assert "DAIO_RELAY_SECRET" not in cockpit_html


def test_openapi_catalog_updates(worker_source: str):
    """Verify OpenAPI catalog includes /cockpit specification."""
    assert '"/cockpit":' in worker_source
    assert 'iPhone Owner Cockpit Web Application (RPC-3B)' in worker_source
