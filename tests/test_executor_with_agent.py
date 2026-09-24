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


def test_executor_async_inside_event_loop():
    """Verify execute_task_async runs seamlessly inside an already-active event loop without RuntimeError."""
    import asyncio

    async def _run_async_test():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "AsyncTester"], cwd=tmp_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "async@test.io"], cwd=tmp_path, check=True, capture_output=True)

            src = tmp_path / "src"
            tests = tmp_path / "tests"
            src.mkdir(); tests.mkdir()
            (src / "__init__.py").write_text("", encoding="utf-8")
            (tests / "__init__.py").write_text("", encoding="utf-8")
            (src / "service.py").write_text("def run(): return 1\n", encoding="utf-8")
            (tests / "test_service.py").write_text("from src.service import run\ndef test_run(): assert run() == 1\n", encoding="utf-8")

            subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "chore: baseline"], cwd=tmp_path, check=True, capture_output=True)

            mock_agent = MockEngineeringAgentAdapter(canned_proposals=[
                AgentTaskProposal(
                    work_id="work-async-01",
                    success=True,
                    backend_identity="TEST_ASYNC_LLM",
                    model_name="mock-async-v1",
                    proposed_edits=[
                        ProposedFileEdit(
                            file_path="src/service.py",
                            new_content="def run(): return 2\n"
                        ),
                        ProposedFileEdit(
                            file_path="tests/test_service.py",
                            new_content="from src.service import run\ndef test_run(): assert run() == 2\n"
                        )
                    ]
                )
            ])

            executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path), agent_adapter=mock_agent)
            work = DAIOWorkItem(
                work_id="work-async-01",
                project_root=str(tmp_path),
                change_id="CHG-ASYNC-01",
                requested_action="Update service return to 2",
                allowed_scope=["src/*", "tests/*"]
            )

            # Await execute_task_async directly inside the running loop
            res = await executor.execute_task_async(work, test_command="pytest tests/ -q", commit_message="feat(service): return 2")
            assert res.success is True
            assert res.test_passed is True
            assert res.scope_violation is False
            assert "return 2" in (src / "service.py").read_text()
            assert res.generated_commit_sha is not None
            assert res.head_sha == res.generated_commit_sha
            assert res.base_sha != ""

    asyncio.run(_run_async_test())


def test_executor_control_plane_classification_and_sha_semantics():
    """Verify pre-existing and created DAIO control plane files do not cause scope violations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.io"], cwd=tmp_path, check=True, capture_output=True)

        src = tmp_path / "src"
        tests = tmp_path / "tests"
        daio_dir = tmp_path / "_daio"
        src.mkdir(); tests.mkdir(); daio_dir.mkdir()

        (src / "__init__.py").write_text("", encoding="utf-8")
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (src / "calc.py").write_text("def val(): return 10\n", encoding="utf-8")
        (tests / "test_calc.py").write_text("from src.calc import val\ndef test_val(): assert val() == 10\n", encoding="utf-8")
        (daio_dir / "daio_config.json").write_text("{}", encoding="utf-8")
        (tmp_path / "daio").write_text("#!/bin/sh\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "chore: baseline with DAIO"], cwd=tmp_path, check=True, capture_output=True)
        init_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()

        # Simulate DAIO SQLite runtime creation
        (daio_dir / "daio_work.db").write_text("sqlite mock", encoding="utf-8")

        mock_agent = MockEngineeringAgentAdapter(canned_proposals=[
            AgentTaskProposal(
                work_id="work-cp-01",
                success=True,
                backend_identity="TEST_LLM",
                model_name="mock-v1",
                proposed_edits=[
                    ProposedFileEdit(file_path="src/calc.py", new_content="def val(): return 20\n"),
                    ProposedFileEdit(file_path="tests/test_calc.py", new_content="from src.calc import val\ndef test_val(): assert val() == 20\n")
                ]
            )
        ])

        executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path), agent_adapter=mock_agent)
        work = DAIOWorkItem(
            work_id="work-cp-01",
            project_root=str(tmp_path),
            change_id="CHG-CP-01",
            requested_action="Update val to 20",
            allowed_scope=["src/*", "tests/*"],
            base_sha=init_sha
        )

        res = executor.execute_task(work, test_command="pytest tests/ -q", commit_message="feat(calc): update val")
        assert res.success is True
        assert res.test_passed is True
        assert res.scope_violation is False
        assert set(res.target_workspace_diff) == {"src/calc.py", "tests/test_calc.py"}
        assert "_daio/daio_work.db" in res.daio_control_plane_diff
        assert len(res.unauthorized_diff) == 0
        assert res.generated_commit_sha is not None
        assert res.generated_commit_sha != init_sha


def test_executor_scope_violation_nulls_generated_commit_sha():
    """Verify unauthorized edits fail closed and set generated_commit_sha = None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.io"], cwd=tmp_path, check=True, capture_output=True)

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "chore: init"], cwd=tmp_path, check=True, capture_output=True)

        mock_agent = MockEngineeringAgentAdapter(canned_proposals=[
            AgentTaskProposal(
                work_id="work-violation-01",
                success=True,
                backend_identity="TEST_LLM",
                proposed_edits=[
                    ProposedFileEdit(file_path="secrets/password.txt", new_content="compromised\n")
                ]
            )
        ])

        executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path), agent_adapter=mock_agent)
        work = DAIOWorkItem(
            work_id="work-violation-01",
            project_root=str(tmp_path),
            change_id="CHG-V-01",
            requested_action="Touch secret",
            allowed_scope=["src/*"]
        )

        res = executor.execute_task(work)
        assert res.success is False
        assert res.scope_violation is True
        assert res.generated_commit_sha is None
        assert res.commit_sha == ""
        assert "secrets/password.txt" in res.unauthorized_diff


def test_executor_test_failure_nulls_generated_commit_sha():
    """Verify failing tests prevent git commit and set generated_commit_sha = None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.io"], cwd=tmp_path, check=True, capture_output=True)

        src = tmp_path / "src"
        tests = tmp_path / "tests"
        src.mkdir(); tests.mkdir()
        (src / "math_broken.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
        (tests / "test_math_broken.py").write_text("from src.math_broken import add\ndef test_add(): assert add(1, 1) == 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "chore: init"], cwd=tmp_path, check=True, capture_output=True)

        mock_agent = MockEngineeringAgentAdapter(canned_proposals=[
            AgentTaskProposal(
                work_id="work-broken-01",
                success=True,
                backend_identity="TEST_LLM",
                proposed_edits=[
                    # Introduces bug
                    ProposedFileEdit(file_path="src/math_broken.py", new_content="def add(a, b): return 999\n")
                ]
            )
        ])

        executor = SubprocessWorkspaceExecutor(project_root=str(tmp_path), agent_adapter=mock_agent)
        work = DAIOWorkItem(
            work_id="work-broken-01",
            project_root=str(tmp_path),
            change_id="CHG-B-01",
            requested_action="Break math",
            allowed_scope=["src/*", "tests/*"]
        )

        res = executor.execute_task(work, test_command="pytest tests/ -q")
        assert res.success is False
        assert res.test_passed is False
        assert res.generated_commit_sha is None
        assert res.commit_sha == ""


