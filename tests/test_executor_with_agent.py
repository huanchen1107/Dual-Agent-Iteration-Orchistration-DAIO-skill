import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole
from scripts.daio_closed_loop.adapters.agent_contract import (
    AgentTaskProposal,
    ProposedFileEdit,
    MockEngineeringAgentAdapter
)
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor

def test_executor_with_agent_proposal_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestAgent"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "agent@test.io"], cwd=tmp_path, check=True, capture_output=True)

        # Baseline
        src = tmp_path / "src"
        tests = tmp_path / "tests"
        src.mkdir(); tests.mkdir()
        (src / "__init__.py").write_text("", encoding="utf-8")
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (src / "math_lib.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
        (tests / "test_math.py").write_text("from src.math_lib import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "chore: baseline"], cwd=tmp_path, check=True, capture_output=True)

        # Configure Agent Mock with proposal
        mock_agent = MockEngineeringAgentAdapter(canned_proposals=[
            AgentTaskProposal(
                work_id="work-agent-01",
                success=True,
                backend_identity="TEST_LLM",
                model_name="mock-coder-v1",
                proposed_edits=[
                    ProposedFileEdit(
                        file_path="src/math_lib.py",
                        new_content="def add(a, b): return a + b\ndef sub(a, b): return a - b\n"
                    ),
                    ProposedFileEdit(
                        file_path="tests/test_math.py",
                        new_content="from src.math_lib import add, sub\ndef test_add(): assert add(1, 2) == 3\ndef test_sub(): assert sub(5, 2) == 3\n"
                    )
                ]
            )
        ])

        executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path), agent_adapter=mock_agent)
        work = DAIOWorkItem(
            work_id="work-agent-01",
            project_root=str(tmp_path),
            change_id="CHG-01",
            requested_action="Add subtract function and test",
            allowed_scope=["src/*", "tests/*"]
        )

        res = executor.execute_task(work, test_command="pytest tests/ -q", commit_message="feat(math): add subtraction")
        assert res.success is True
        assert res.test_passed is True
        assert res.scope_violation is False
        assert len(res.diff_files) == 2
        assert "sub" in (src / "math_lib.py").read_text()
