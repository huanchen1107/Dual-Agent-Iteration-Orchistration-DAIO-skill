"""Regression coverage for the Codex CLI 0.150.1 JSONL response envelope."""

import json

import pytest

from scripts.daio_closed_loop.adapters.codex_cli_agent import CodexCLIAdapter


PROPOSAL = {
    "reasoning_summary": "Apply the requested disposable change.",
    "proposed_edits": [
        {
            "file_path": "answer.py",
            "new_content": "ANSWER = 42\n",
            "description": "Update the disposable answer.",
        }
    ],
}


def _agent_text():
    return f"```json\n{json.dumps(PROPOSAL)}\n```"


def test_existing_top_level_codex_envelope_remains_supported():
    stream = json.dumps({"type": "message", "content": _agent_text()})

    parsed = CodexCLIAdapter()._parse_proposal_from_output(stream)

    assert parsed == PROPOSAL


def test_codex_0150_item_completed_agent_text_is_parsed():
    stream = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "sanitized"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_sanitized", "type": "agent_message", "text": _agent_text()},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {}}),
        ]
    )

    parsed = CodexCLIAdapter()._parse_proposal_from_output(stream)

    assert parsed == PROPOSAL
    assert parsed["proposed_edits"][0]["new_content"] == "ANSWER = 42\n"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "item.completed", "item": "malformed"},
        {"type": "item.completed", "item": {"type": "agent_message"}},
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "text": _agent_text()},
        },
        {"type": "turn.completed", "text": _agent_text()},
    ],
)
def test_malformed_or_non_agent_nested_envelopes_fail_closed(event):
    with pytest.raises(ValueError, match="Could not parse structured proposed_edits"):
        CodexCLIAdapter()._parse_proposal_from_output(json.dumps(event))


def test_unknown_output_remains_fail_closed():
    stream = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "sanitized"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}),
        ]
    )

    with pytest.raises(ValueError, match="Could not parse structured proposed_edits"):
        CodexCLIAdapter()._parse_proposal_from_output(stream)
