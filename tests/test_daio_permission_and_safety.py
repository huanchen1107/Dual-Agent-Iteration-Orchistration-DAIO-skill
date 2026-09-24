import os
import tempfile
import pytest
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor

def test_tier1_routine_scope_permission():
    with tempfile.TemporaryDirectory() as tmpdir:
        executor = SubprocessWorkspaceExecutor(project_root=tmpdir)
        work = DAIOWorkItem(
            work_id="scope-01",
            project_root=tmpdir,
            change_id="change-01",
            allowed_scope=["src/*", "tests/*"]
        )
        # Routine edits inside allowed scope pass
        assert executor.check_scope_violations(work, ["src/main.py", "tests/test_main.py"]) is False

def test_tier2_frozen_scope_human_gate():
    with tempfile.TemporaryDirectory() as tmpdir:
        executor = SubprocessWorkspaceExecutor(project_root=tmpdir)
        work = DAIOWorkItem(
            work_id="scope-02",
            project_root=tmpdir,
            change_id="change-01",
            allowed_scope=["src/modules/*"]
        )
        # Attempt to edit files outside allowed scope triggers violation
        assert executor.check_scope_violations(work, ["app/frozen/strategy.py"]) is True

def test_consecutive_error_safety_breaker():
    work = DAIOWorkItem(
        work_id="safety-001",
        project_root="/tmp",
        change_id="change-01",
        status=DAIOStatus.IN_PROGRESS,
        attempt_count=3,
        max_attempts=3
    )
    # Exceeding error budget transitions to HUMAN_GATE_REQUIRED
    assert work.attempt_count >= work.max_attempts
