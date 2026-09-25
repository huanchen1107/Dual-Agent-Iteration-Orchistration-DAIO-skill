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
    base_sha: str = ""
    head_sha: str = ""
    generated_commit_sha: Optional[str] = None
    diff_files: List[str] = field(default_factory=list)
    target_workspace_diff: List[str] = field(default_factory=list)
    daio_control_plane_diff: List[str] = field(default_factory=list)
    unauthorized_diff: List[str] = field(default_factory=list)
    output: str = ""
    error_message: Optional[str] = None
    scope_violation: bool = False
    proposal: Optional[AgentTaskProposal] = None
    test_regressions: List[str] = field(default_factory=list)
    baseline_failures: List[str] = field(default_factory=list)
    current_failures: List[str] = field(default_factory=list)
    regression_status: str = "ALL_PASSED"

    @property
    def commit_sha(self) -> str:
        """Backward-compatible alias: returns generated_commit_sha or empty string."""
        return self.generated_commit_sha or ""


def extract_pytest_failures(output: str) -> List[str]:
    """
    Extracts failed/error test node identifiers or failure names from pytest output.
    Matches lines like:
      FAILED tests/test_foo.py::test_bar - AssertionError...
      FAILED tests/test_pine_smc_reference.py::test_baseline_manifest_is_reproducible_and_change_024_is_protected
      ERROR tests/test_baz.py::test_init
    """
    import re
    failures = set()
    for line in output.splitlines():
        line = line.strip()
        # Pattern 1: FAILED/ERROR path/to/test.py::test_func[...]
        m = re.match(r'^(?:FAILED|ERROR)\s+([^\s:]+::[^\s\-]+)', line)
        if m:
            clean_node = m.group(1).strip()
            failures.add(clean_node)
            continue
        # Pattern 2: FAILED/ERROR path/to/test.py::test_func
        m2 = re.match(r'^(?:FAILED|ERROR)\s+([^\s]+)', line)
        if m2 and "::" in m2.group(1):
            clean_node = m2.group(1).split()[0].strip()
            failures.add(clean_node)
            continue
        # Pattern 3: Summary lines: FAILED tests/test_pine_smc_reference.py::test_xxx
        m3 = re.match(r'^FAILED\s+([a-zA-Z0-9_\-/\.]+\.py::[a-zA-Z0-9_\[\]\-\.]+)', line)
        if m3:
            clean_node = m3.group(1).strip()
            failures.add(clean_node)
            continue
    return sorted(list(failures))


def is_failure_in_baseline(failure: str, baseline_list: List[str]) -> bool:
    """
    Checks if a given failing test identifier matches any item in the approved baseline failure set.
    Supports exact node ID match, basename match, and bracketed parameter match.
    """
    if failure in baseline_list:
        return True
    for b in baseline_list:
        if b == failure:
            return True
        # Exact suffix match (e.g. baseline has "test_func" or "test_file.py::test_func")
        if failure.endswith(f"::{b}") or b.endswith(f"::{failure}"):
            return True
        # Match base name without parametrization: test_func[param] matches test_func
        if "[" in failure and failure.split("[")[0] == b:
            return True
        if "[" in failure and failure.split("[")[0].endswith(f"::{b}"):
            return True
    return False


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

    @abstractmethod
    async def execute_task_async(
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
        curr_pypath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{self.project_root}:{curr_pypath}".strip(":")
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

    def classify_diff_files(
        self,
        diff_files: List[str],
        allowed_scope: List[str],
        frozen_paths: Optional[List[str]] = None,
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Classifies modified files into:
        1. target_workspace_diff (files belonging to target application source/tests)
        2. daio_control_plane_diff (DAIO runtime state, DB, configs, launcher)
        3. unauthorized_diff (files that violate allowed_scope or touch frozen_paths)
        """
        target_ws: List[str] = []
        control_plane: List[str] = []
        unauthorized: List[str] = []

        daio_control_patterns = [
            "_daio/*", "_daio", ".daio/*", ".daio", "daio",
            "_myplan_*", ".maomao*", "reports/*"
        ]
        frozen_patterns = frozen_paths or [".env*", "secrets/*"]

        for f in diff_files:
            norm_f = f.replace("\\", "/")
            # Check if control plane
            if any(
                fnmatch.fnmatch(norm_f, pat)
                or fnmatch.fnmatch(Path(norm_f).name, pat)
                or norm_f.startswith("_daio/")
                or norm_f.startswith(".daio/")
                for pat in daio_control_patterns
            ):
                control_plane.append(norm_f)
                continue

            target_ws.append(norm_f)

            # Check if in frozen paths
            if any(fnmatch.fnmatch(norm_f, pat) or fnmatch.fnmatch(Path(norm_f).name, pat) for pat in frozen_patterns):
                unauthorized.append(norm_f)
                continue

            # Check allowed scope: empty scope or unmatched pattern -> unauthorized
            if allowed_scope is not None:
                matched = any(fnmatch.fnmatch(norm_f, pat) or fnmatch.fnmatch(Path(norm_f).name, pat) for pat in allowed_scope)
                if not matched:
                    unauthorized.append(norm_f)

        return target_ws, control_plane, unauthorized

    def check_scope_violations(self, work: DAIOWorkItem, diff_files: List[str]) -> bool:
        """Enforce DAIO-002: Ensure modified files stay within allowed_scope."""
        target_ws, control_plane, unauthorized = self.classify_diff_files(
            diff_files,
            work.allowed_scope,
            getattr(work, "frozen_paths", None)
        )
        return len(unauthorized) > 0

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


    async def execute_task_async(
        self,
        work: DAIOWorkItem,
        command: Optional[str] = None,
        test_command: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> ExecutionResult:
        """Asynchronous execution path: directly awaits agent proposal without nested event loops."""
        out_logs = []
        proposal = None
        base_sha = self.get_current_head()

        # Fast-Path / Existing Workspace Check:
        # If requested_action, daio_config.json, or metadata indicates validating existing workspace, bypass agent proposal synthesis.
        action_lower = (work.requested_action or "").lower()

        cfg_validation_only = False
        cfg_path = Path(self.project_root) / "_daio" / "daio_config.json"
        if not cfg_path.exists():
            cfg_path = Path(self.project_root) / "daio_config.json"
        if cfg_path.exists():
            try:
                cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg_validation_only = bool(cfg_data.get("validation_only", False))
            except Exception:
                pass

        is_validation_only = (
            cfg_validation_only
            or bool(work.metadata.get("validation_only"))
            or bool(work.metadata.get("skip_agent_proposal"))
            or "validation" in action_lower
            or "validate existing" in action_lower
            or "validate the existing" in action_lower
            or "do not regenerate" in action_lower
            or "existing workspace" in action_lower
            or "do not invoke agy" in action_lower
            or "do not invoke" in action_lower
        )

        # 1. If an agent adapter is configured and requested_action is provided (and not validation-only), invoke Coding Agent
        if self.agent_adapter and work.requested_action and not is_validation_only:
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

            proposal = await self.agent_adapter.propose_task_solution(req)
            if not proposal.success:
                return ExecutionResult(
                    success=False,
                    test_passed=False,
                    base_sha=base_sha,
                    head_sha=base_sha,
                    generated_commit_sha=None,
                    output=f"Agent proposal failed: {proposal.error_message}",
                    error_message=proposal.error_message,
                    proposal=proposal
                )

            # DAIO Policy Guard: Validate proposed edits before applying
            root_path = Path(self.project_root)
            for edit in proposal.proposed_edits:
                target_file = root_path / edit.file_path
                norm_edit_path = edit.file_path.replace("\\", "/")
                # Check scope: empty allowed_scope or edit not matching pattern is unauthorized
                matched = any(fnmatch.fnmatch(norm_edit_path, pat) or fnmatch.fnmatch(Path(norm_edit_path).name, pat) for pat in (work.allowed_scope or []))
                if not matched:
                    return ExecutionResult(
                        success=False,
                        test_passed=False,
                        base_sha=base_sha,
                        head_sha=base_sha,
                        generated_commit_sha=None,
                        scope_violation=True,
                        unauthorized_diff=[norm_edit_path],
                        error_message=f"Agent proposed edit violates allowed_scope: {edit.file_path}",
                        proposal=proposal
                    )
                # Apply authorized edit
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(edit.new_content, encoding="utf-8")

        elif is_validation_only:
            out_logs.append("FAST_PATH_VALIDATION_ONLY: Skipped coding agent proposal synthesis per existing workspace validation request.")

        elif command:
            code, out = self.run_cmd(command)
            out_logs.append(out)
            if code != 0:
                return ExecutionResult(
                    success=False,
                    test_passed=False,
                    base_sha=base_sha,
                    head_sha=base_sha,
                    generated_commit_sha=None,
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
        target_ws, control_plane, unauthorized = self.classify_diff_files(
            diff_files,
            work.allowed_scope,
            getattr(work, "frozen_paths", None)
        )

        if unauthorized:
            return ExecutionResult(
                success=False,
                test_passed=False,
                base_sha=base_sha,
                head_sha=base_sha,
                generated_commit_sha=None,
                diff_files=diff_files,
                target_workspace_diff=target_ws,
                daio_control_plane_diff=control_plane,
                unauthorized_diff=unauthorized,
                output="\n".join(out_logs),
                error_message=f"DAIO-002 Scope Violation: unauthorized workspace modifications: {unauthorized}",
                scope_violation=True,
                proposal=proposal
            )

        # 3. Run Test Integrity Gate (DAIO-001 / Baseline-Aware)
        test_cmd = test_command or "pytest tests/ -q"
        code, test_out = self.run_cmd(test_cmd)
        out_logs.append(test_out)

        # Retrieve approved baseline test failures and baseline SHA
        baseline_failures: List[str] = []
        baseline_sha: Optional[str] = getattr(work, "base_sha", None) or None

        if hasattr(work, "metadata") and isinstance(work.metadata, dict):
            baseline_failures = work.metadata.get("baseline_test_failures") or work.metadata.get("approved_baseline_failures") or []
            if not baseline_sha:
                baseline_sha = work.metadata.get("baseline_sha")

        if not baseline_failures:
            # Fallback to _daio/daio_config.json
            cfg_path = Path(self.project_root) / "_daio" / "daio_config.json"
            if not cfg_path.exists():
                cfg_path = Path(self.project_root) / "daio_config.json"
            if cfg_path.exists():
                try:
                    cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    baseline_failures = cfg_data.get("baseline_test_failures", [])
                    if not baseline_sha:
                        baseline_sha = cfg_data.get("baseline_sha")
                except Exception:
                    pass

        current_failures = extract_pytest_failures(test_out) if code != 0 else []
        new_regressions = [f for f in current_failures if not is_failure_in_baseline(f, baseline_failures)]

        if code == 0:
            test_passed = True
            regression_status = "ALL_PASSED"
        elif baseline_failures and current_failures and len(new_regressions) == 0:
            test_passed = True
            regression_status = "NO_NEW_REGRESSIONS_PASS"
            msg = (
                f"[DAIO_TEST_GATE] Baseline-aware evaluation passed: {len(current_failures)} current failure(s) "
                f"matched approved baseline failure set (Baseline SHA: {baseline_sha or 'UNSPECIFIED'}). 0 new regressions."
            )
            out_logs.append(msg)
        else:
            test_passed = False
            regression_status = "NEW_REGRESSIONS_FAIL"

        if not test_passed:
            err_detail = (
                f"Test Integrity Gate Failed: {len(new_regressions)} new regression(s) detected: {new_regressions} (exit code {code})"
                if new_regressions
                else f"Test Integrity Gate Failed (exit code {code}):\n{test_out}"
            )
            return ExecutionResult(
                success=False,
                test_passed=False,
                base_sha=base_sha,
                head_sha=base_sha,
                generated_commit_sha=None,
                diff_files=diff_files,
                target_workspace_diff=target_ws,
                daio_control_plane_diff=control_plane,
                unauthorized_diff=[],
                output="\n".join(out_logs),
                error_message=err_detail,
                proposal=proposal,
                test_regressions=new_regressions,
                baseline_failures=baseline_failures,
                current_failures=current_failures,
                regression_status=regression_status,
            )

        # 4. If tests pass, commit deliverable
        # Stage canonical deliverables in target_ws while preserving forensic/evidence files uncommitted
        staged_any = False
        for f in target_ws:
            if (
                "051-daio-root-" in f
                or f.startswith("_myplan")
                or f.startswith("docs/")
                or f.startswith("_daio")
            ):
                continue
            self.run_cmd(f"git add '{f}'")
            staged_any = True

        if staged_any:
            msg = commit_message or f"feat(change051): implement canonical OpenSpec scaffold deliverables for {work.change_id}"
            self.run_cmd(f"git commit -m \"{msg}\"")
        new_head = self.get_current_head()

        return ExecutionResult(
            success=True,
            test_passed=True,
            base_sha=base_sha,
            head_sha=new_head,
            generated_commit_sha=new_head,
            diff_files=diff_files,
            target_workspace_diff=target_ws,
            daio_control_plane_diff=control_plane,
            unauthorized_diff=[],
            output="\n".join(out_logs),
            proposal=proposal,
            test_regressions=[],
            baseline_failures=baseline_failures,
            current_failures=current_failures,
            regression_status=regression_status,
        )

    def execute_task(
        self,
        work: DAIOWorkItem,
        command: Optional[str] = None,
        test_command: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> ExecutionResult:
        """Synchronous wrapper for callers not running an async event loop."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            raise RuntimeError(
                "Cannot call synchronous execute_task() from an active event loop. Use 'await execute_task_async()' instead."
            )

        return loop.run_until_complete(
            self.execute_task_async(
                work=work,
                command=command,
                test_command=test_command,
                commit_message=commit_message,
            )
        )


