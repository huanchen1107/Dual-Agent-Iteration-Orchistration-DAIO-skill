"""
Replaceable Engineering Executor Adapter for Generic DAIO Closed Loop.
Implements Two-Tier Policy Enforcement and Pluggable Coding Agent Integration.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
import datetime
import fnmatch
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from ..models import DAIOWorkItem
from .agent_contract import (
    AgentTaskRequest,
    AgentTaskProposal,
    ProposedFileEdit,
    EngineeringAgentAdapter,
    MockEngineeringAgentAdapter
)


@dataclass
class ExecutionResult:
    success: bool
    test_passed: bool
    commit_sha: str = ""
    diff_files: List[str] = field(default_factory=list)
    output: str = ""
    error_message: Optional[str] = None
    scope_violation: bool = False
    proposal: Optional[AgentTaskProposal] = None


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

    def __init__(self, project_root: Optional[str] = None, agent_adapter: Optional[EngineeringAgentAdapter] = None) -> None:
        self.project_root = project_root or os.getcwd()
        self.agent_adapter = agent_adapter

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
            clean = line.strip()
            if not clean:
                continue
            parts = clean.split(maxsplit=1)
            if len(parts) == 2:
                files.append(parts[1].strip())
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

    def _gather_context_files(self, allowed_scope: List[str]) -> Dict[str, str]:
        """Read existing files in allowed_scope to provide context to the agent."""
        context = {}
        root = Path(self.project_root)
        for pattern in allowed_scope:
            for p in root.glob(pattern):
                if p.is_file() and not any(p.match(fp) for fp in [".env*", "secrets/*", "*/.git/*"]):
                    try:
                        rel = str(p.relative_to(root))
                        context[rel] = p.read_text(encoding="utf-8")
                    except Exception:
                        continue
        return context

    def execute_task(
        self,
        work: DAIOWorkItem,
        command: Optional[str] = None,
        test_command: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> ExecutionResult:
        out_logs = []
        proposal = None

        # 1. If an agent adapter is configured and requested_action is provided, invoke Coding Agent
        if self.agent_adapter and work.requested_action:
            context_files = self._gather_context_files(work.allowed_scope)
            req = AgentTaskRequest(
                work_id=work.work_id,
                change_id=work.change_id,
                requested_action=work.requested_action,
                project_root=self.project_root,
                allowed_scope=work.allowed_scope,
                frozen_paths=getattr(work, "frozen_paths", ["src/frozen/*", ".env", "secrets/*"]),
                context_files=context_files,
            )
            # Run async agent proposal
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            proposal = loop.run_until_complete(self.agent_adapter.propose_task_solution(req))
            if not proposal.success:
                return ExecutionResult(
                    success=False,
                    test_passed=False,
                    commit_sha=self.get_current_head(),
                    output=f"Agent proposal failed: {proposal.error_message}",
                    error_message=proposal.error_message,
                    proposal=proposal
                )

            # DAIO Policy Guard: Validate proposed edits before applying
            root_path = Path(self.project_root)
            for edit in proposal.proposed_edits:
                target_file = root_path / edit.file_path
                # Check scope
                if work.allowed_scope and not any(fnmatch.fnmatch(edit.file_path, pat) for pat in work.allowed_scope):
                    return ExecutionResult(
                        success=False,
                        test_passed=False,
                        commit_sha=self.get_current_head(),
                        scope_violation=True,
                        error_message=f"Agent proposed edit violates allowed_scope: {edit.file_path}",
                        proposal=proposal
                    )
                # Apply authorized edit
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(edit.new_content, encoding="utf-8")

        elif command:
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
            # Fallback progress artifact
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
                proposal=proposal
            )

        # 3. Run Test Integrity Gate (DAIO-001)
        test_cmd = test_command or "pytest tests/ -q"
        code, test_out = self.run_cmd(test_cmd)
        out_logs.append(test_out)
        test_passed = (code == 0)

        if not test_passed:
            return ExecutionResult(
                success=False,
                test_passed=False,
                commit_sha=self.get_current_head(),
                diff_files=diff_files,
                output="\n".join(out_logs),
                error_message=f"Test Integrity Gate Failed (exit code {code}):\n{test_out}",
                proposal=proposal
            )

        # 4. If tests pass, commit deliverable
        self.run_cmd("git add .")
        msg = commit_message or f"feat(daio): automated execution for {work.change_id}"
        self.run_cmd(f"git commit -m '{msg}'")
        head_sha = self.get_current_head()

        return ExecutionResult(
            success=True,
            test_passed=True,
            commit_sha=head_sha,
            diff_files=diff_files,
            output="\n".join(out_logs),
            proposal=proposal
        )
