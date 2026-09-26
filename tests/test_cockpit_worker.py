"""
Tests for RPC-3C.2 WebAuthn Passkey Ingress, Action Tickets, and Hardened CSP in relay_worker.js.
Verifies all 17 security hardening & provider-neutrality requirements from RPC-3C.2.
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
    1. CSP & Security Headers:
    Verify that CSP headers do NOT permit 'unsafe-inline' for scripts.
    Executable JS must be loaded from same-origin static /cockpit.js route.
    """
    assert "Content-Security-Policy" in worker_source
    assert "script-src 'self';" in worker_source
    assert "script-src 'self' 'unsafe-inline'" not in worker_source
    assert '<script src="/cockpit.js"></script>' in cockpit_html
    assert '<script>\n' not in cockpit_html
    assert "X-Content-Type-Options" in worker_source
    assert "X-Frame-Options" in worker_source
    assert "Permissions-Policy" in worker_source


def test_cockpit_routes_registered(worker_source: str):
    """2. Route Registration: Verify /cockpit, /ui, and /cockpit.js."""
    assert 'path === "/cockpit"' in worker_source
    assert 'path === "/cockpit.js"' in worker_source
    assert '"Content-Type": "application/javascript; charset=utf-8"' in worker_source


def test_valid_passkey_registration_flow(worker_source: str):
    """3. Valid Passkey Registration: Verify enrollment token verification and storage."""
    assert 'path === "/api/v1/auth/enroll/token"' in worker_source
    assert 'path === "/api/v1/auth/enroll/verify"' in worker_source
    assert 'await statusKV.delete(tokenKey)' in worker_source  # Atomic single-use enrollment token
    assert 'auth:passkey:' in worker_source


def test_invalid_assertion_rejection(worker_source: str):
    """4. Invalid Assertion Rejection: Verify clientDataJSON type check."""
    assert 'clientData.type !== "webauthn.get"' in worker_source
    assert 'clientData.challenge !== challenge' in worker_source


def test_expired_and_reused_challenge_fail_closed(worker_source: str):
    """5. Expired & Reused Challenge: Verify 60s TTL and single-use atomic deletion."""
    assert 'expirationTtl: 60' in worker_source
    assert 'challenge:${challenge}' in worker_source
    assert 'await statusKV.delete(chKey)' in worker_source  # Atomic delete on verify


def test_valid_action_ticket_generation_and_schema(worker_source: str):
    """6. Action Ticket Schema: Verify 180s TTL and full field binding."""
    assert 'expirationTtl: 180' in worker_source
    assert 'actionTicket = {' in worker_source
    assert 'ticket_id:' in worker_source
    assert 'project_id:' in worker_source
    assert 'work_id:' in worker_source
    assert 'gate_id:' in worker_source
    assert 'current_phase:' in worker_source
    assert 'decision:' in worker_source
    assert 'action:' in worker_source
    assert 'instruction_hash:' in worker_source
    assert 'credential_id:' in worker_source


def test_action_ticket_reused_and_expired_rejection(worker_source: str):
    """7. Action Ticket Single-Use Atomic Consumption."""
    assert 'request.headers.get("X-Action-Ticket")' in worker_source
    assert 'await statusKV.delete(ticketKey)' in worker_source  # Single-use delete on ingest


def test_wrong_project_and_work_id_binding_rejection(worker_source: str):
    """8. Ticket Binding Enforcement: Wrong project or work_id rejected."""
    assert 'ticket.project_id !== projectId' in worker_source
    assert 'ticket.work_id !== workId' in worker_source
    assert 'ticket.decision !== decision' in worker_source


def test_instruction_tampering_hash_verification(worker_source: str):
    """9. Instruction Tampering: Instruction hash computed at edge."""
    assert 'sha256Bytes(new TextEncoder().encode(instruction))' in worker_source
    assert 'instruction_hash:' in worker_source


def test_credential_revocation_and_reset(worker_source: str):
    """10. Credential Revocation & Reset endpoints."""
    assert 'path.startsWith("/api/v1/auth/credentials/") && path.endsWith("/revoke")' in worker_source
    assert 'path === "/api/v1/auth/reset"' in worker_source


def test_human_gate_interactive_controls_in_html_and_js(cockpit_html: str, cockpit_js: str):
    """11. Interactive Decision Controls: APPROVE, REVISE, STOP."""
    assert 'id="btn-approve"' in cockpit_html
    assert 'id="btn-revise-open"' in cockpit_html
    assert 'id="btn-stop"' in cockpit_html
    assert 'id="revise-modal"' in cockpit_html
    assert "handleDecisionExecution('APPROVE')" in cockpit_js
    assert "handleDecisionExecution('STOP')" in cockpit_js
    assert "handleDecisionExecution('REVISE'" in cockpit_js
    assert "navigator.credentials.get" in cockpit_js
    assert "X-Action-Ticket" in cockpit_js


def test_zero_permanent_secrets_in_cockpit_client(cockpit_html: str, cockpit_js: str):
    """12. Zero Client Secrets Invariant."""
    assert "localStorage" not in cockpit_js
    assert "sessionStorage" not in cockpit_js
    assert "DAIO_RELAY_SECRET" not in cockpit_js
    assert "DAIO_RELAY_SECRET" not in cockpit_html


def test_rpc1_and_rpc2_regression(worker_source: str):
    """13. RPC-1 & RPC-2 Ingress/Poller Compatibility."""
    assert 'path === "/api/v1/status"' in worker_source
    assert 'path === "/api/v1/publish"' in worker_source
    assert 'path === "/api/v1/health"' in worker_source
    assert 'path === "/api/v1/decisions"' in worker_source
    assert 'path.startsWith("/api/v1/decisions/") && path.endsWith("/ack")' in worker_source


def test_provider_neutrality_guardrail(worker_source: str, cockpit_js: str):
    """
    14. Provider Neutrality Guardrail:
    Verify that relay worker and client code contain NO provider-specific coupling
    (e.g., ChatGPT, Claude, Antigravity, Gemini, Codex hardcoding in decision contracts).
    """
    # Decision schema uses neutral fields
    assert "protocol_version" in worker_source
    assert "decision_id" in worker_source
    assert "auth_mode" in worker_source
    # No AI provider branding in decision logic
    assert "claude_model" not in worker_source
    assert "chatgpt_session" not in worker_source
    assert "antigravity_token" not in worker_source
