"""Contract checks for the ChatGPT-callable Native Dispatch action."""

from pathlib import Path


WORKER = Path(__file__).parents[1] / "cloudflare" / "relay_worker.js"


def test_dispatch_work_openapi_action_is_callable_and_typed():
    source = WORKER.read_text(encoding="utf-8")
    assert 'operationId: "dispatch_work"' in source
    assert '"#/components/schemas/DispatchWorkRequest"' in source
    assert 'required: ["action_ticket", "change_id", "requested_action", "client_idempotency_key"]' in source
    assert '"/api/v1/dispatch/ticket"' in source


def test_chatgpt_body_ticket_uses_the_same_fail_closed_authority_path():
    source = WORKER.read_text(encoding="utf-8")
    assert 'String(body.action_ticket || "").trim()' in source
    assert 'const suppliedActionTicket = actionTicketHeader ||' in source
    assert 'Verified WebAuthn Action Ticket required' in source
    assert 'action !== "dispatch_work"' in source
