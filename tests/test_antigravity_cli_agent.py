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
    # When agy exists, factory should auto-select AntigravityCLIAdapter by default
    adapter = create_engineering_agent_adapter()
    assert isinstance(adapter, AntigravityCLIAdapter)

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

        mock_json_output = """{
          "status": "SUCCESS",
          "response": "```json\\n{\\n  \\"reasoning_summary\\": \\"Added multiply function\\",\\n  \\"proposed_edits\\": [\\n    {\\n      \\"file_path\\": \\"src/math.py\\",\\n      \\"new_content\\": \\"def add(a, b): return a + b\\\\ndef multiply(a, b): return a * b\\\\n\\",\\n      \\"description\\": \\"Implemented multiply\\"\\n    }\\n  ]\\n}\\n```"
        }"""

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(mock_json_output.encode("utf-8"), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            proposal = await adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "ANTIGRAVITY_CLI"
            assert len(proposal.proposed_edits) == 1
            assert proposal.proposed_edits[0].file_path == "src/math.py"
            assert "def multiply" in proposal.proposed_edits[0].new_content

    asyncio.run(_test())

