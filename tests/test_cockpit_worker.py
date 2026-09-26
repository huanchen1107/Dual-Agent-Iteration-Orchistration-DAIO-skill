"""
Tests for RPC-3C.2 WebAuthn Passkey Ingress, Action Tickets, and Hardened CSP in relay_worker.js.
"""

import json
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
    match = re.search(r"const COCKPIT_HTML = `(.*?)`;", worker_source, re.DOTALL)
    assert match is not None, "COCKPIT_HTML not found in relay_worker.js"
    return match.group(1)


@pytest.fixture(scope="module")
def cockpit_js(worker_source: str) -> str:
    match = re.search(r"const COCKPIT_JS = `(.*?)`;", worker_source, re.DOTALL)
    assert match is not None, "COCKPIT_JS not found in relay_worker.js"
    return match.group(1)


def test_hardened_csp_without_unsafe_inline_for_scripts(worker_source: str, cockpit_html: str):
    """
    CRITICAL SECURITY CHECK:
    Verify that CSP headers do NOT permit 'unsafe-inline' for scripts.
    Executable JS must be loaded from same-origin static /cockpit.js route.
    """
    # Check CSP header in worker response headers
    assert "Content-Security-Policy" in worker_source
    assert "script-src 'self';" in worker_source
    assert "script-src 'self' 'unsafe-inline'" not in worker_source

    # Check that HTML includes external script tag rather than inline code
    assert '<script src="/cockpit.js"></script>' in cockpit_html
    # Ensure no inline script blocks with executable logic exist in HTML body
    assert '<script>\n' not in cockpit_html


def test_cockpit_routes_registered(worker_source: str):
    """Verify /cockpit, /ui, and /cockpit.js are properly registered routes."""
    assert 'path === "/cockpit"' in worker_source
    assert 'path === "/cockpit.js"' in worker_source
    assert '"Content-Type": "application/javascript; charset=utf-8"' in worker_source


def test_webauthn_auth_endpoints_registered(worker_source: str):
    """Verify WebAuthn challenge, verify, enrollment, and admin routes."""
    assert 'path === "/api/v1/auth/challenge"' in worker_source
    assert 'path === "/api/v1/auth/verify"' in worker_source
    assert 'path === "/api/v1/auth/enroll/token"' in worker_source
    assert 'path === "/api/v1/auth/enroll/verify"' in worker_source
    assert 'path === "/api/v1/auth/credentials"' in worker_source
    assert 'path === "/api/v1/auth/reset"' in worker_source


def test_action_ticket_binding_and_consumption(worker_source: str):
    """Verify strict multi-dimensional Action Ticket binding check and atomic deletion."""
    # Check X-Action-Ticket header extraction
    assert 'request.headers.get("X-Action-Ticket")' in worker_source
    # Check binding checks
    assert 'ticket.project_id !== projectId' in worker_source
    assert 'ticket.work_id !== workId' in worker_source
    assert 'ticket.decision !== decision' in worker_source
    # Check atomic ticket consumption (deletion from KV)
    assert 'await statusKV.delete(ticketKey)' in worker_source


def test_human_gate_interactive_controls_in_html_and_js(cockpit_html: str, cockpit_js: str):
    """Verify APPROVE, REVISE, and STOP interactive controls and WebAuthn handlers."""
    # HTML buttons
    assert 'id="btn-approve"' in cockpit_html
    assert 'id="btn-revise-open"' in cockpit_html
    assert 'id="btn-stop"' in cockpit_html
    assert 'id="revise-modal"' in cockpit_html

    # JS handlers
    assert "handleDecisionExecution('APPROVE')" in cockpit_js
    assert "handleDecisionExecution('STOP')" in cockpit_js
    assert "handleDecisionExecution('REVISE'" in cockpit_js
    assert "navigator.credentials.get" in cockpit_js
    assert "X-Action-Ticket" in cockpit_js


def test_zero_permanent_secrets_in_cockpit_client(cockpit_html: str, cockpit_js: str):
    """
    CRITICAL INVARIANT CHECK:
    Verify client code does NOT store DAIO_RELAY_SECRET or permanent tokens in browser storage.
    """
    assert "localStorage" not in cockpit_js
    assert "sessionStorage" not in cockpit_js
    assert "DAIO_RELAY_SECRET" not in cockpit_js
    assert "DAIO_RELAY_SECRET" not in cockpit_html


def test_openapi_catalog_updates(worker_source: str):
    """Verify OpenAPI v3.2 catalog documents WebAuthn Passkey endpoints."""
    assert '"/api/v1/auth/challenge":' in worker_source
    assert '"/api/v1/auth/verify":' in worker_source
    assert '"/api/v1/auth/enroll/token":' in worker_source
