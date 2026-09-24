import asyncio
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.daio_closed_loop.adapters.agent_contract import (
    AgentTaskRequest,
    AgentTaskProposal,
    ProposedFileEdit
)
from scripts.daio_closed_loop.adapters.antigravity_cli_agent import (
    AntigravityCLIAdapter,
    find_antigravity_cli_path
)
from scripts.daio_closed_loop.adapters.factory import create_engineering_agent_adapter
from scripts.daio_closed_loop.adapters.gemini_agent import GeminiEngineeringAgentAdapter


def test_find_antigravity_cli_path():
    path = find_antigravity_cli_path()
    assert path is not None
    assert Path(path).exists()
    assert "agy" in path or "antigravity" in path


def test_factory_capability_detection(monkeypatch):
    # When agy exists, factory should auto-select AntigravityCLIAdapter by default or with provider AUTO
    adapter = create_engineering_agent_adapter()
    assert isinstance(adapter, AntigravityCLIAdapter)

    adapter_auto = create_engineering_agent_adapter({"provider": "AUTO"})
    assert isinstance(adapter_auto, AntigravityCLIAdapter)

    # When explicit GEMINI provider requested
    adapter_gemini = create_engineering_agent_adapter({"provider": "GEMINI"})
    assert isinstance(adapter_gemini, GeminiEngineeringAgentAdapter)

    # When agy not available, fallback to Gemini
    monkeypatch.setattr("scripts.daio_closed_loop.adapters.factory.find_antigravity_cli_path", lambda: None)
    adapter_fallback = create_engineering_agent_adapter()
    assert isinstance(adapter_fallback, GeminiEngineeringAgentAdapter)


def test_antigravity_cli_adapter_propose_task_mocked():
    async def _test():
        adapter = AntigravityCLIAdapter(cli_path="/usr/local/bin/agy")
        req = AgentTaskRequest(
            work_id="test-agy-1",
            change_id="CHG_AGY_TEST",
            requested_action="Add multiply function to math.py",
            project_root="/tmp/sandbox",
            allowed_scope=["src/*"],
            frozen_paths=["src/frozen.py"],
            context_files={"src/math.py": "def add(a, b): return a + b\n"}
        )

        mock_json_output = """jetski: info logs here
{
  "conversation_id": "abc-123",
  "status": "SUCCESS",
  "response": "```json\\n{\\n  \\"reasoning_summary\\": \\"Added multiply function\\",\\n  \\"proposed_edits\\": [\\n    {\\n      \\"file_path\\": \\"src/math.py\\",\\n      \\"new_content\\": \\"def add(a, b): return a + b\\\\ndef multiply(a, b): return a * b\\\\n\\",\\n      \\"description\\": \\"Implemented multiply\\"\\n    },\\n    {\\n      \\"file_path\\": \\"tests/test_math.py\\",\\n      \\"new_content\\": \\"def test_multiply(): assert multiply(2, 3) == 6\\\\n\\",\\n      \\"description\\": \\"Test multiply\\"\\n    }\\n  ]\\n}\\n```",
  "duration_seconds": 2.5
}"""

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(mock_json_output.encode("utf-8"), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            proposal = await adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "ANTIGRAVITY_CLI"
            assert len(proposal.proposed_edits) == 2
            assert proposal.proposed_edits[0].file_path == "src/math.py"
            assert "def multiply" in proposal.proposed_edits[0].new_content
            assert proposal.proposed_edits[1].file_path == "tests/test_math.py"

    asyncio.run(_test())


def test_antigravity_cli_adapter_bare_json_and_non_success_handling():
    async def _test():
        adapter = AntigravityCLIAdapter(cli_path="/usr/local/bin/agy")
        req = AgentTaskRequest(
            work_id="test-agy-2",
            change_id="CHG_AGY_TEST",
            requested_action="Do task",
            project_root="/tmp/sandbox"
        )

        # 1. Bare JSON without fences
        bare_output = """{
          "status": "SUCCESS",
          "response": "{\\"reasoning_summary\\": \\"Bare JSON\\", \\"proposed_edits\\": [{\\"file_path\\": \\"a.py\\", \\"new_content\\": \\"# a\\", \\"description\\": \\"a\\"}]}"
        }"""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(bare_output.encode("utf-8"), b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            proposal = await adapter.propose_task_solution(req)
            assert proposal.success is True
            assert len(proposal.proposed_edits) == 1
            assert proposal.proposed_edits[0].file_path == "a.py"

        # 2. Non-success status from CLI (e.g. denied permissions)
        denied_output = """{
          "status": "DENIED",
          "response": "",
          "denied_actions": [{"action": "command", "display_name": "RunCommand"}]
        }"""
        mock_proc.communicate = AsyncMock(return_value=(denied_output.encode("utf-8"), b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            proposal = await adapter.propose_task_solution(req)
            assert proposal.success is False
            assert "non-success status 'DENIED'" in proposal.error_message

        # 3. Malformed inner response
        bad_inner = """{
          "status": "SUCCESS",
          "response": "Here is what I think but no JSON at all."
        }"""
        mock_proc.communicate = AsyncMock(return_value=(bad_inner.encode("utf-8"), b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            proposal = await adapter.propose_task_solution(req)
            assert proposal.success is False

def test_headless_unattended_command_flags_and_no_dangerous_bypass():
    """
    Regression Test:
    Verifies that AntigravityCLIAdapter builds clean headless non-interactive commands:
    1. Passes --print, --output-format json, --disable-slash-commands, --add-dir.
    2. Does NOT pass --dangerously-skip-permissions (preserves DAIO security model).
    3. Executes headlessly via subprocess without IDE GUI prompt dependency.
    """
    captured_cmds = []

    async def _test():
        adapter = AntigravityCLIAdapter(cli_path="/usr/local/bin/agy")
        req = AgentTaskRequest(
            work_id="test-agy-headless",
            change_id="CHG_HEADLESS",
            requested_action="Refactor pipeline",
            project_root="/tmp/sandbox",
            allowed_scope=["src/*", "tests/*"]
        )

        mock_json_output = """{
          "status": "SUCCESS",
          "response": "```json\\n{\\"reasoning_summary\\": \\"ok\\", \\"proposed_edits\\": []}\\n```"
        }"""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(mock_json_output.encode("utf-8"), b""))

        async def fake_subprocess_exec(*args, **kwargs):
            captured_cmds.append(list(args))
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec):
            proposal = await adapter.propose_task_solution(req)
            assert proposal.success is True

        assert len(captured_cmds) == 1
        cmd = captured_cmds[0]
        assert cmd[0] == "/usr/local/bin/agy"
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "--disable-slash-commands" in cmd
        assert "--add-dir" in cmd
        assert "/tmp/sandbox" in cmd
        # Architectural Security Invariant: no dangerous permission bypass flag used
        assert "--dangerously-skip-permissions" not in cmd

    asyncio.run(_test())


