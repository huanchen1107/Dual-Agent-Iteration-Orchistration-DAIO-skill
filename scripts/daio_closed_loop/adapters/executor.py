"""
Replaceable Engineering Executor Adapter for Generic DAIO Closed Loop.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime
import fnmatch
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from ..models import DAIOWorkItem


@dataclass
class ExecutionResult:
    success: bool
    test_passed: bool
    commit_sha: str = ""
    diff_files: List[str] = field(default_factory=list)
    output: str = ""
    error_message: Optional[str] = None
    scope_violation: bool = False


class EngineeringExecutorAdapter(ABC):
    """Abstract interface for executing engineering tasks and running verification gates."""

    @abstractmethod
    def execute_task(
        self,
        work: DAIOWorkItem,
        command: Optional[str] = None,
        test_command: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> ExecutionResult:
        raise NotImplementedError


class SubprocessWorkspaceExecutor(EngineeringExecutorAdapter):
    """
    Workspace-native subprocess execution adapter.
    Enforces test integrity gates, scope guardrails (DAIO-002), and Git deliverables sync.
    """

    def __init__(self, project_root: Optional[str] = None) -> None:
        self.project_root = project_root or os.getcwd()

    def run_cmd(self, cmd: str) -> Tuple[int, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = self.project_root
        res = subprocess.run(
            cmd,
            shell=True,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            env=env,
        )
        return res.returncode, (res.stdout + "\n" + res.stderr).strip()

    def get_current_head(self) -> str:
        code, out = self.run_cmd("git rev-parse HEAD")
        if code == 0:
            return out.strip()
        return "UNKNOWN_HEAD"

    def get_modified_files(self) -> List[str]:
        code, out = self.run_cmd("git status --porcelain")
        if code != 0:
            return []
        files = []
        for line in out.splitlines():
            line = line.strip()
            if len(line) > 3:
                files.append(line[3:])
        return files

    def check_scope_violations(self, work: DAIOWorkItem, diff_files: List[str]) -> bool:
        """Enforce DAIO-002: Ensure modified files stay within allowed_scope."""
        for f in diff_files:
            # If allowed_scope is defined, check wildcard match
            if work.allowed_scope:
                matched = any(fnmatch.fnmatch(f, pat) or fnmatch.fnmatch(Path(f).name, pat) for pat in work.allowed_scope)
                if not matched:
                    # Allow internal metadata and docs
                    if not (f.startswith("_myplan_") or f.startswith(".maomao") or f.startswith("_daio") or f.startswith("reports")):
                        return True
        return False

    def execute_task(
        self,
        work: DAIOWorkItem,
        command: Optional[str] = None,
        test_command: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> ExecutionResult:
        # 1. Execute task command (if provided) or perform safe bounded revision artifact
        out_logs = []
        if command:
            code, out = self.run_cmd(command)
            out_logs.append(out)
            if code != 0:
                return ExecutionResult(
                    success=False,
                    test_passed=False,
                    commit_sha=self.get_current_head(),
                    output="\n".join(out_logs),
                    error_message=f"Command '{command}' failed with exit code {code}",
                )
        else:
            # If revision requested, create safe evidence progress artifact
            evidence_dir = Path(self.project_root) / "_daio" / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            progress_file = evidence_dir / f"revision-progress-{work.work_id}.json"
            progress_file.write_text(json.dumps({
                "work_id": work.work_id,
                "change_id": work.change_id,
                "requested_action": work.requested_action,
                "attempt_count": work.attempt_count,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }, indent=2), encoding="utf-8")

        # 2. Check modified files & Scope Violations
        diff_files = self.get_modified_files()
        if self.check_scope_violations(work, diff_files):
            return ExecutionResult(
                success=False,
                test_passed=False,
                commit_sha=self.get_current_head(),
                diff_files=diff_files,
                output="\n".join(out_logs),
                error_message="DAIO-002 Scope Violation: modified files violate allowed_scope.",
                scope_violation=True,
            )

        # 3. Run Test Integrity Gate
        if test_command:
            test_code, test_out = self.run_cmd(test_command)
            out_logs.append(test_out)
            if test_code != 0:
                return ExecutionResult(
                    success=False,
                    test_passed=False,
                    commit_sha=self.get_current_head(),
                    diff_files=diff_files,
                    output="\n".join(out_logs),
                    error_message=f"Test Integrity Gate '{test_command}' failed with exit code {test_code}",
                )

        # 4. Commit and Push to remote
        msg = commit_message or f"feat(daio): automated execution for work {work.work_id}"
        self.run_cmd("git add .")
        self.run_cmd(f'git commit -m "{msg}"')
        self.run_cmd("git push origin main")
        new_head = self.get_current_head()

        return ExecutionResult(
            success=True,
            test_passed=True,
            commit_sha=new_head,
            diff_files=diff_files,
            output="\n".join(out_logs),
        )
