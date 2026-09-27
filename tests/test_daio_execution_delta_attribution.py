"""
DAIO-002 Execution Delta Attribution Unit & Integration Tests.
Validates scenarios A through H per canonical DAIO safety contract.
"""

from __future__ import annotations
import asyncio
import os
import shutil
import tempfile
import pytest
from pathlib import Path
import subprocess

from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOGate
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor
from scripts.daio_closed_loop.adapters.agent_contract import (
    EngineeringAgentAdapter,
    AgentTaskRequest,
    AgentTaskProposal,
    ProposedFileEdit,
)


class MockCustomProposalAgent(EngineeringAgentAdapter):
    """Configurable mock agent that returns specific proposed edits."""
    def __init__(self, edits=None, success=True):
        self.edits = edits or []
        self.success = success

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        return AgentTaskProposal(
            work_id=request.work_id,
            success=self.success,
            backend_identity="MOCK_CUSTOM",
            model_name="mock-model",
            reasoning_summary="Mock test proposal",
            proposed_edits=self.edits,
            started_at="2026-09-27T00:00:00Z",
            completed_at="2026-09-27T00:00:01Z",
        )


def setup_temp_repo(p: Path):
    """Initialize clean git repository."""
    subprocess.run(["git", "init"], cwd=str(p), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "DAIO Test"], cwd=str(p), check=True)
    subprocess.run(["git", "config", "user.email", "daio@test.local"], cwd=str(p), check=True)

    # Create initial files
    (p / "app").mkdir(parents=True, exist_ok=True)
    (p / "app" / "main.py").write_text("print('hello')\n")
    (p / "tests").mkdir(parents=True, exist_ok=True)
    (p / "tests" / "test_main.py").write_text("def test_ok(): assert True\n")
    (p / "tests" / "test_existing.py").write_text("def test_exist(): assert True\n")

    subprocess.run(["git", "add", "."], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(p), check=True)


def test_scenario_a_clean_workspace_authorized_new_file(tmp_path: Path):
    """Scenario A: Clean workspace + authorized new file -> PASS."""
    setup_temp_repo(tmp_path)
    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="_daio/evidence/c1_2_acceptance.json",
            new_content='{"status": "PASS"}',
            description="Add acceptance evidence"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="work-a",
        project_root=str(tmp_path),
        change_id="change-a",
        requested_action="Create acceptance evidence",
        allowed_scope=["_daio/evidence/*"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is True
    assert res.scope_violation is False
    assert len(res.unauthorized_diff) == 0
    assert "_daio/evidence/c1_2_acceptance.json" in res.diff_files


def test_scenario_b_clean_workspace_unauthorized_new_file(tmp_path: Path):
    """Scenario B: Clean workspace + unauthorized new file -> DAIO-002."""
    setup_temp_repo(tmp_path)
    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="tests/unauthorized_test.py",
            new_content='def test_bad(): pass',
            description="Unauthorized test addition"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="work-b",
        project_root=str(tmp_path),
        change_id="change-b",
        requested_action="Create unauthorized test",
        allowed_scope=["_daio/evidence/*"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is False
    assert res.scope_violation is True
    assert "tests/unauthorized_test.py" in res.unauthorized_diff


def test_scenario_c_preexisting_dirty_unauthorized_untouched_not_attributed(tmp_path: Path):
    """Scenario C: Pre-existing dirty unauthorized file untouched by provider -> NOT attributed."""
    setup_temp_repo(tmp_path)
    # Create pre-existing dirty modification in an unauthorized file
    dirty_file = tmp_path / "tests" / "test_existing.py"
    dirty_file.write_text("def test_exist(): # PRE_EXISTING_DIRTY\n    assert True\n")

    # Verify workspace is dirty before execution
    executor_check = SubprocessWorkspaceExecutor(str(tmp_path))
    assert "tests/test_existing.py" in executor_check.get_modified_files()

    # Agent only edits authorized file
    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="_daio/evidence/c1_2_acceptance.json",
            new_content='{"status": "PASS"}',
            description="Add acceptance evidence"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="work-c",
        project_root=str(tmp_path),
        change_id="change-c",
        requested_action="Create acceptance evidence",
        allowed_scope=["_daio/evidence/*"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is True
    assert res.scope_violation is False
    assert "tests/test_existing.py" not in res.diff_files
    assert "tests/test_existing.py" not in res.unauthorized_diff


def test_scenario_d_preexisting_dirty_unauthorized_modified_again_attributed(tmp_path: Path):
    """Scenario D: Pre-existing dirty unauthorized file modified again by provider -> DAIO-002."""
    setup_temp_repo(tmp_path)
    # Pre-existing dirty modification
    dirty_file = tmp_path / "tests" / "test_existing.py"
    dirty_file.write_text("def test_exist(): # PRE_EXISTING_DIRTY_V1\n    assert True\n")

    # Agent attempts to mutate that same dirty unauthorized file further
    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="tests/test_existing.py",
            new_content='def test_exist(): # MUTATED_BY_AGENT_V2\n    assert True\n',
            description="Mutate dirty file"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="work-d",
        project_root=str(tmp_path),
        change_id="change-d",
        requested_action="Mutate test file",
        allowed_scope=["_daio/evidence/*"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is False
    assert res.scope_violation is True
    assert "tests/test_existing.py" in res.unauthorized_diff


def test_scenario_e_preexisting_untracked_untouched_not_attributed(tmp_path: Path):
    """Scenario E: Pre-existing untracked file untouched -> NOT attributed."""
    setup_temp_repo(tmp_path)
    # Pre-existing untracked marker file
    marker = tmp_path / "c1_compliance_marker.txt"
    marker.write_text("OLD_MARKER_CONTENT\n")

    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="_daio/evidence/c1_2_acceptance.json",
            new_content='{"status": "PASS"}',
            description="Add acceptance evidence"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="work-e",
        project_root=str(tmp_path),
        change_id="change-e",
        requested_action="Create acceptance evidence",
        allowed_scope=["_daio/evidence/*"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is True
    assert res.scope_violation is False
    assert "c1_compliance_marker.txt" not in res.diff_files
    assert "c1_compliance_marker.txt" not in res.unauthorized_diff


def test_scenario_f_preexisting_untracked_modified_attributed(tmp_path: Path):
    """Scenario F: Pre-existing untracked file modified by provider -> DAIO-002."""
    setup_temp_repo(tmp_path)
    marker = tmp_path / "c1_compliance_marker.txt"
    marker.write_text("OLD_MARKER_CONTENT\n")

    # Agent mutates the untracked file which is not in allowed_scope
    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="c1_compliance_marker.txt",
            new_content='NEW_MUTATED_CONTENT\n',
            description="Mutate marker"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="work-f",
        project_root=str(tmp_path),
        change_id="change-f",
        requested_action="Mutate marker",
        allowed_scope=["_daio/evidence/*"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is False
    assert res.scope_violation is True
    assert "c1_compliance_marker.txt" in res.unauthorized_diff


def test_scenario_g_authorized_mutation_with_unrelated_dirty_files_pass(tmp_path: Path):
    """Scenario G: Authorized evidence file mutation + unrelated pre-existing dirty files untouched -> PASS (Exact C1.2 reproduction)."""
    setup_temp_repo(tmp_path)
    # 1. Pre-existing dirty tracked file (simulates tests/test_daio_rpc_approval.py)
    dirty_tracked = tmp_path / "tests" / "test_existing.py"
    dirty_tracked.write_text("def test_exist(): # PRE_EXISTING_DIRTY_RPC\n    assert True\n")

    # 2. Pre-existing untracked file (simulates c1_compliance_marker.txt)
    dirty_untracked = tmp_path / "c1_compliance_marker.txt"
    dirty_untracked.write_text("PHASE: C1.1 PRE_EXISTING\n")

    # 3. Agent generates only authorized evidence file
    agent = MockCustomProposalAgent(edits=[
        ProposedFileEdit(
            file_path="_daio/evidence/c1_2_blackbox_acceptance.json",
            new_content='{"acceptance_test": "c1_2_blackbox_acceptance", "status": "PASS"}',
            description="C1.2 Blackbox Acceptance Evidence"
        )
    ])
    executor = SubprocessWorkspaceExecutor(str(tmp_path), agent_adapter=agent)
    work = DAIOWorkItem(
        work_id="daio-root-c1-2-blackbox-acceptance-003",
        project_root=str(tmp_path),
        change_id="c1.2-blackbox-acceptance-retry-003",
        requested_action="Verify DAIO runtime environment in read-only mode and emit _daio/evidence/c1_2_blackbox_acceptance.json",
        allowed_scope=["_daio/evidence/c1_2_blackbox_acceptance.json"],
    )

    res = asyncio.run(executor.execute_task_async(work, test_command="pytest tests/ -q"))
    assert res.success is True
    assert res.scope_violation is False
    assert len(res.unauthorized_diff) == 0
    assert "_daio/evidence/c1_2_blackbox_acceptance.json" in res.diff_files
    assert "tests/test_existing.py" not in res.diff_files
    assert "c1_compliance_marker.txt" not in res.diff_files
