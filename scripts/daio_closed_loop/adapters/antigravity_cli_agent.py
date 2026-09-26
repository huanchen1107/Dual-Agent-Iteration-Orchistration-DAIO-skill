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
        timeout_seconds: int = 300,
        unattended: bool = True,
        sandbox: bool = True,
    ) -> None:
        self.cli_path = cli_path or find_antigravity_cli_path()
        self.model_name = model_name or "antigravity-cli-default"
        self.timeout_seconds = timeout_seconds
        self.unattended = unattended
        self.sandbox = sandbox

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
1. You are in pure proposal generation mode. Do NOT invoke, call, or attempt to execute tools or commands.
2. Determine all necessary file modifications or additions to fulfill the task objective.
3. Only modify or create files that strictly adhere to the Allowed Scope patterns. Do not touch Frozen paths.
4. Output MUST be a valid JSON object matching this schema:
```json
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
```
Ensure the entire response is wrapped in a ```json code fence.
"""
        return prompt

    def _extract_outer_envelope(self, stdout_str: str) -> Dict[str, Any]:
        """Extract the outer JSON envelope from CLI stdout, handling potential prefix/suffix logs."""
        # Try direct parse
        try:
            return json.loads(stdout_str.strip())
        except Exception:
            pass

        # Look for the outermost balanced JSON object in stdout
        start_idx = stdout_str.find("{")
        end_idx = stdout_str.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = stdout_str[start_idx:end_idx + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass

        raise ValueError(f"Could not locate valid outer JSON envelope in CLI stdout: {stdout_str[:300]}")

    def _parse_proposal_from_response(self, text: str) -> Dict[str, Any]:
        """Extract structured JSON proposal from CLI response text."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Empty model response received from Antigravity CLI.")

        # 1. Look for fenced markdown code block
        fence_matches = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", clean_text, re.DOTALL)
        for fence_content in reversed(fence_matches):
            try:
                data = json.loads(fence_content.strip(), strict=False)
                if isinstance(data, dict) and "proposed_edits" in data and isinstance(data["proposed_edits"], list):
                    return data
            except Exception:
                continue

        # 2. Look for outermost balanced JSON object
        start_idx = clean_text.find("{")
        end_idx = clean_text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = clean_text[start_idx:end_idx + 1]
            try:
                data = json.loads(candidate, strict=False)
                if isinstance(data, dict) and "proposed_edits" in data and isinstance(data["proposed_edits"], list):
                    return data
            except Exception:
                pass

        raise ValueError(
            f"Could not parse structured proposed_edits JSON from Antigravity CLI output. Response preview: {clean_text[:250]}"
        )

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
        cmd = [self.cli_path]
        if self.sandbox:
            cmd.append("--sandbox")
        if self.unattended:
            cmd.append("--dangerously-skip-permissions")
        cmd.extend([
            "--print", prompt_text,
            "--output-format", "json",
            "--disable-slash-commands",
            "--add-dir", request.project_root,
        ])
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
                    error_message=f"CLI execution failed with exit code {proc.returncode}: {stderr_str or stdout_str[:300]}",
                    started_at=started_at,
                    completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    raw_response=stdout_str
                )

            # 1. Parse outer CLI JSON envelope
            cli_envelope = self._extract_outer_envelope(stdout_str)
            cli_status = cli_envelope.get("status", "UNKNOWN")

            if cli_status != "SUCCESS":
                denied = cli_envelope.get("denied_actions", [])
                err_msg = f"CLI returned non-success status '{cli_status}'"
                if denied:
                    err_msg += f" with denied actions: {denied}"
                return AgentTaskProposal(
                    work_id=request.work_id,
                    success=False,
                    backend_identity="ANTIGRAVITY_CLI",
                    model_name=self.model_name,
                    error_message=err_msg,
                    started_at=started_at,
                    completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    raw_response=stdout_str
                )

            response_text = cli_envelope.get("response", "")

            # 2. Parse inner structured proposal from response payload
            parsed = self._parse_proposal_from_response(response_text)
            raw_edits = parsed.get("proposed_edits", [])
            if not isinstance(raw_edits, list):
                raise ValueError(f"Expected 'proposed_edits' to be a list, got {type(raw_edits).__name__}")

            edits = []
            for e in raw_edits:
                if not isinstance(e, dict) or "file_path" not in e or "new_content" not in e:
                    raise ValueError(f"Malformed edit object in proposed_edits: {e}")
                edits.append(
                    ProposedFileEdit(
                        file_path=e["file_path"],
                        new_content=e["new_content"],
                        description=e.get("description", ""),
                        is_deletion=e.get("is_deletion", False)
                    )
                )

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
                error_message=f"Antigravity CLI adapter parse/execution failure: {str(e)}",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                raw_response=locals().get("stdout_str", "")
            )

