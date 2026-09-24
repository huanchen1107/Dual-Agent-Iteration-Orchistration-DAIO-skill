import asyncio
import pytest
from scripts.daio_closed_loop.adapters.agent_contract import AgentTaskRequest
from scripts.daio_closed_loop.adapters.gemini_agent import GeminiEngineeringAgentAdapter
from scripts.daio_closed_loop.adapters.factory import create_engineering_agent_adapter

def test_gemini_agent_build_prompt_and_parse():
    adapter = GeminiEngineeringAgentAdapter(api_key="mock-key", model_name="gemini-2.5-pro")
    
    req = AgentTaskRequest(
        work_id="work-01",
        change_id="CHG-01",
        requested_action="Create string utility function capitalize_words in src/utils.py and test in tests/test_utils.py",
        project_root="/tmp/sandbox",
        allowed_scope=["src/*", "tests/*"],
        frozen_paths=["src/frozen/*"],
        context_files={"src/main.py": "# existing main file\n"}
    )
    
    prompt = adapter._build_system_prompt(req)
    assert "Create string utility function" in prompt
    assert "src/main.py" in prompt
    assert "Allowed Scope Patterns" in prompt
    
    sample_llm_reply = """Here is the proposed implementation:
```json
{
  "reasoning_summary": "Created capitalize_words utility and unit tests.",
  "proposed_edits": [
    {
      "file_path": "src/utils.py",
      "new_content": "def capitalize_words(s: str) -> str:\n    return s.title()\n",
      "description": "String capitalization helper"
    },
    {
      "file_path": "tests/test_utils.py",
      "new_content": "from src.utils import capitalize_words\ndef test_cap(): assert capitalize_words('hello world') == 'Hello World'\n",
      "description": "Unit test for capitalization"
    }
  ]
}
```
"""
    parsed = adapter._parse_llm_response(sample_llm_reply)
    assert parsed["reasoning_summary"] == "Created capitalize_words utility and unit tests."
    assert len(parsed["proposed_edits"]) == 2
    assert parsed["proposed_edits"][0]["file_path"] == "src/utils.py"

def test_gemini_agent_fail_closed_without_credentials():
    async def _run():
        adapter = GeminiEngineeringAgentAdapter(api_key=None)
        req = AgentTaskRequest(
            work_id="work-02",
            change_id="CHG-02",
            requested_action="Arbitrary task",
            project_root="/tmp/sandbox"
        )
        proposal = await adapter.propose_task_solution(req)
        assert proposal.success is False
        assert "GEMINI_API_KEY" in proposal.error_message

    asyncio.run(_run())

def test_factory_instantiation():
    mock_adapter = create_engineering_agent_adapter({"provider": "MOCK"})
    assert mock_adapter.__class__.__name__ == "MockEngineeringAgentAdapter"
    
    gemini_adapter = create_engineering_agent_adapter({"provider": "GEMINI", "api_key": "test-key"})
    assert gemini_adapter.__class__.__name__ == "GeminiEngineeringAgentAdapter"
