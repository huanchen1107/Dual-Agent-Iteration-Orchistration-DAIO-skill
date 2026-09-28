"""Bounded diagnostic classification tests for canonical Codex CLI execution."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from scripts.daio_closed_loop.adapters.agent_contract import AgentTaskRequest
from scripts.daio_closed_loop.adapters.codex_cli_agent import CodexCLIAdapter
from scripts.daio_closed_loop.handoff_contract import CAPACITY_OUTCOMES, Outcome


PROPOSAL_TEXT = json.dumps(
    {
        "reasoning_summary": "Disposable change.",
        "proposed_edits": [
            {"file_path": "answer.py", "new_content": "ANSWER = 42\n", "description": "Update answer."}
        ],
    }
)


def run_adapter(stdout, stderr=b"", returncode=0):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate.return_value = (
        stdout.encode() if isinstance(stdout, str) else stdout,
        stderr.encode() if isinstance(stderr, str) else stderr,
    )
    request = AgentTaskRequest(
        "diagnostic-work",
        "C1.4",
        "Update the disposable answer.",
        "/tmp",
        allowed_scope=["answer.py"],
    )

    async def invoke():
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            return await CodexCLIAdapter(cli_path="/fake/codex", model_name="codex-default").propose_task_solution(request)

    return asyncio.run(invoke())


def test_successful_stdout_normal_exit_preserves_success():
    proposal = run_adapter(json.dumps({"type": "message", "content": PROPOSAL_TEXT}))

    assert proposal.success is True
    assert proposal.proposed_edits[0].new_content == "ANSWER = 42\n"


def test_codex_0150_nested_stdout_preserves_success():
    stdout = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": PROPOSAL_TEXT}}
    )

    proposal = run_adapter(stdout)

    assert proposal.success is True
    assert proposal.proposed_edits[0].file_path == "answer.py"


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("Error: usage limit reached for this account", Outcome.CAPACITY_EXHAUSTED),
        ("Error: rate limit exceeded; retry later", Outcome.RATE_LIMITED),
        ("Error: service temporarily unavailable", Outcome.TEMPORARILY_UNAVAILABLE),
        ("Error: not logged in; please run codex login", Outcome.AUTHENTICATION_REQUIRED),
        ("Error: unsupported model", Outcome.INCOMPATIBLE),
    ],
)
def test_explicit_stderr_diagnostics_are_typed(diagnostic, expected):
    proposal = run_adapter("", diagnostic, returncode=1)

    assert proposal.success is False
    assert proposal.outcome == expected
    assert proposal.raw_response == ""


def test_unknown_stderr_remains_fail_closed_and_sanitized():
    proposal = run_adapter("", "opaque failure secret-token-123", returncode=9)

    assert proposal.success is False
    assert proposal.outcome == Outcome.UNKNOWN_FAILURE
    assert proposal.error_message == (
        "Backend execution failed: UNKNOWN_FAILURE "
        "(exit=9; diagnostic=UNRECOGNIZED_PROVIDER_DIAGNOSTIC)"
    )
    assert "secret-token-123" not in proposal.error_message
    assert proposal.raw_response == ""


def test_agent_like_stderr_never_becomes_success():
    proposal = run_adapter("", PROPOSAL_TEXT, returncode=1)

    assert proposal.success is False
    assert proposal.outcome == Outcome.UNKNOWN_FAILURE
    assert proposal.proposed_edits == []


def test_malformed_stdout_with_diagnostic_stderr_does_not_bypass_failure():
    proposal = run_adapter("{malformed proposal", "service unavailable", returncode=1)

    assert proposal.success is False
    assert proposal.outcome == Outcome.TEMPORARILY_UNAVAILABLE
    assert proposal.proposed_edits == []


def test_sensitive_json_diagnostic_is_not_persisted():
    stderr = json.dumps(
        {"error": {"code": "RATE_LIMITED", "message": "Bearer secret-token-123"}}
    )

    proposal = run_adapter("", stderr, returncode=1)

    assert proposal.outcome == Outcome.RATE_LIMITED
    assert "secret-token-123" not in proposal.error_message
    assert "Bearer" not in proposal.error_message


def test_capacity_diagnostics_enter_existing_handoff_outcome_set():
    assert {
        Outcome.CAPACITY_EXHAUSTED,
        Outcome.RATE_LIMITED,
        Outcome.TEMPORARILY_UNAVAILABLE,
    } <= CAPACITY_OUTCOMES
    assert Outcome.INCOMPATIBLE not in CAPACITY_OUTCOMES
