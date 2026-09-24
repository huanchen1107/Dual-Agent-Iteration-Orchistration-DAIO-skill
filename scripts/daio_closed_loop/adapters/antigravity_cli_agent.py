"""
Antigravity CLI Backend Adapter for Generic DAIO (Change 050 / Generic DAIO v2.1).
Executes unattended prompts via the official Antigravity CLI ('agy') to generate
structured ProposedFileEdit proposals.

Strictly preserves the DAIO security model:
- The CLI is invoked to generate proposals.
- Direct disk writes, git commits, scope checks, and test gates are enforced by DAIO.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .agent_contract import (
    AgentTaskRequest,
    AgentTaskProposal,
    ProposedFileEdit,
    EngineeringAgentAdapter
)

logger = logging.getLogger("DAIO_AntigravityCLI_Adapter")


def find_antigravity_cli_path() -> Optional[str]:
    """Find the path to the official Antigravity CLI executable."""
    env_path = os.environ.get("ANTIGRAVITY_CLI_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    which_path = shutil.which("agy") or shutil.which("antigravity")
    if which_path:
        return which_path

    home_local_bin = Path.home() / ".local" / "bin" / "agy"
    if home_local_bin.is_file() and os.access(str(home_local_bin), os.X_OK):
        return str(home_local_bin)

    return None


class AntigravityCLIAdapter(EngineeringAgentAdapter):
    """
    Genuine EngineeringAgentAdapter backend powered by the official Antigravity CLI ('agy').
    Consumes arbitrary natural-language requested_action and returns structured AgentTaskProposal.
    """

    def __init__(
        self,
        cli_path: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.cli_path = cli_path or find_antigravity_cli_path()
        self.model_name = model_name or "antigravity-cli-default"
        self.timeout_seconds = timeout_seconds

    def _build_prompt(self, request: AgentTaskRequest) -> str:
        context_str = ""
        for path, content in request.context_files.items():
            context_str += f"\n--- File: {path} ---\n{content}\n"

        prompt = f"""You are an autonomous senior software engineer working in project root: {request.project_root}.

Task Objective:
{request.requested_action}

Allowed Scope Patterns: {request.allowed_scope}
Frozen / Protected Paths: {request.frozen_paths}

Current Workspace Context:
{context_str if context_str else "(No initial context files provided)"}

Instructions:
1. Determine all necessary file modifications or additions to fulfill the task objective.
2. Only modify or create files that strictly adhere to the Allowed Scope patterns. Do not touch Frozen paths.
3. Output MUST be a valid JSON object matching this schema:
{{
  "reasoning_summary": "Brief summary of implementation decisions",
  "proposed_edits": [
    {{
      "file_path": "path/to/file.py",
      "new_content": "Full new file content string",
      "description": "What this edit does"
    }}
  ]
}}
Ensure the response is wrapped in a ```json code fence.
"""
        return prompt

    def _parse_proposal_from_response(self, text: str) -> Dict[str, Any]:
        """Extract structured JSON proposal from CLI response text."""
        # 1. Look for fenced markdown code block
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            try:
                data = json.loads(fence_match.group(1).strip(), strict=False)
                if isinstance(data, dict) and "proposed_edits" in data:
                    return data
            except Exception:
                pass

        # 2. Look for outermost balanced JSON object
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                candidate = text[start_idx:end_idx + 1]
                data = json.loads(candidate, strict=False)
                if isinstance(data, dict) and "proposed_edits" in data:
                    return data
            except Exception:
                pass

        raise ValueError("Could not parse structured proposed_edits JSON from Antigravity CLI output.")

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not self.cli_path:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="ANTIGRAVITY_CLI",
                model_name=self.model_name,
                error_message="Antigravity CLI executable ('agy') not found on system PATH or ~/.local/bin/agy.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        prompt_text = self._build_prompt(request)
        cmd = [
            self.cli_path,
            "--print", prompt_text,
            "--output-format", "json",
            "--add-dir", request.project_root,
        ]
        if self.model_name and self.model_name != "antigravity-cli-default":
            cmd.extend(["--model", self.model_name])

        try:
            # Execute subprocess asynchronously
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=request.project_root
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(request.timeout_seconds or self.timeout_seconds)
            )

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                return AgentTaskProposal(
                    work_id=request.work_id,
                    success=False,
                    backend_identity="ANTIGRAVITY_CLI",
                    model_name=self.model_name,
                    error_message=f"CLI execution failed with code {proc.returncode}: {stderr_str or stdout_str}",
                    started_at=started_at,
                    completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    raw_response=stdout_str
                )

            # Parse the outer CLI JSON envelope
            cli_envelope = json.loads(stdout_str)
            response_text = cli_envelope.get("response", "")

            parsed = self._parse_proposal_from_response(response_text)
            edits = [
                ProposedFileEdit(
                    file_path=e["file_path"],
                    new_content=e["new_content"],
                    description=e.get("description", ""),
                    is_deletion=e.get("is_deletion", False)
                )
                for e in parsed.get("proposed_edits", [])
            ]

            return AgentTaskProposal(
                work_id=request.work_id,
                success=True,
                backend_identity="ANTIGRAVITY_CLI",
                model_name=self.model_name,
                reasoning_summary=parsed.get("reasoning_summary", ""),
                proposed_edits=edits,
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                raw_response=stdout_str
            )

        except asyncio.TimeoutError:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="ANTIGRAVITY_CLI",
                model_name=self.model_name,
                error_message=f"Antigravity CLI execution timed out after {request.timeout_seconds or self.timeout_seconds}s.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
        except Exception as e:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="ANTIGRAVITY_CLI",
                model_name=self.model_name,
                error_message=f"Antigravity CLI adapter encountered exception: {str(e)}",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
