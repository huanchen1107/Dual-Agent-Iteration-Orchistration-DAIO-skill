"""
OpenCode CLI Backend Adapter for Generic DAIO (Phase B4B / daio-agent/v1).
Executes unattended prompts via the OpenCode CLI ('opencode run') using delegated provider credentials.
Consumes natural-language requested_action and returns structured ProposedFileEdit proposals.
Strictly zero direct disk write or git execution authority.
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

logger = logging.getLogger("DAIO_OpenCodeCLI_Adapter")


def find_opencode_cli_path() -> Optional[str]:
    """Find the path to the official OpenCode CLI executable."""
    env_path = os.environ.get("OPENCODE_CLI_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    which_path = shutil.which("opencode")
    if which_path:
        return which_path

    fallback_paths = [
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        "/opt/homebrew/bin/opencode",
        str(Path.home() / ".local" / "bin" / "opencode"),
        "/usr/local/bin/opencode"
    ]
    for fp in fallback_paths:
        if os.path.isfile(fp) and os.access(fp, os.X_OK):
            return fp

    return None


class OpenCodeCLIAdapter(EngineeringAgentAdapter):
    """
    EngineeringAgentAdapter backend powered by the OpenCode CLI ('opencode run').
    Operates with PROVIDER_DEPENDENT delegated credentials without DAIO requiring static API keys.
    """

    def __init__(
        self,
        cli_path: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: int = 300,
        unattended: bool = True,
        sandbox: bool = True,
    ) -> None:
        self.cli_path = cli_path or find_opencode_cli_path()
        self.model_name = model_name or "opencode-default"
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

    def _parse_proposal_from_output(self, stdout_str: str) -> Dict[str, Any]:
        """Extract structured JSON proposal from OpenCode output or JSON events."""
        # 1. Check for JSON events or lines in reverse
        for line in reversed(stdout_str.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    # Check text/content/message fields
                    for k in ("content", "message", "text", "response", "data"):
                        val = event.get(k)
                        if isinstance(val, str) and "proposed_edits" in val:
                            return self._parse_json_from_text(val)
                    if "proposed_edits" in event and isinstance(event["proposed_edits"], list):
                        return event
            except Exception:
                pass

        # 2. Fallback to direct regex/fence parsing from raw output
        return self._parse_json_from_text(stdout_str)

    def _parse_json_from_text(self, text: str) -> Dict[str, Any]:
        """Extract structured JSON proposal from text block."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Empty model response received from OpenCode CLI.")

        fence_matches = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", clean_text, re.DOTALL)
        for fence_content in reversed(fence_matches):
            try:
                data = json.loads(fence_content.strip(), strict=False)
                if isinstance(data, dict) and "proposed_edits" in data and isinstance(data["proposed_edits"], list):
                    return data
            except Exception:
                continue

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

        raise ValueError(f"Could not parse structured proposed_edits JSON from OpenCode CLI output. Preview: {clean_text[:250]}")

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not self.cli_path:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="OPENCODE_CLI",
                model_name=self.model_name,
                error_message="OpenCode CLI executable ('opencode') not found on system PATH.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        prompt_text = self._build_prompt(request)
        cmd = [
            self.cli_path,
            "run",
            prompt_text,
            "--format", "json",
            "--dir", request.project_root,
        ]
        if self.unattended:
            cmd.append("--dangerously-skip-permissions")
        if self.model_name and self.model_name != "opencode-default":
            cmd.extend(["-m", self.model_name])

        try:
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
                    backend_identity="OPENCODE_CLI",
                    model_name=self.model_name,
                    error_message=f"OpenCode CLI failed with exit code {proc.returncode}: {stderr_str or stdout_str[:300]}",
                    started_at=started_at,
                    completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    raw_response=stdout_str
                )

            parsed = self._parse_proposal_from_output(stdout_str)
            raw_edits = parsed.get("proposed_edits", [])
            edits = []
            for e in raw_edits:
                if isinstance(e, dict) and "file_path" in e and "new_content" in e:
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
                backend_identity="OPENCODE_CLI",
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
                backend_identity="OPENCODE_CLI",
                model_name=self.model_name,
                error_message=f"OpenCode CLI execution timed out after {request.timeout_seconds or self.timeout_seconds}s.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
        except Exception as e:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="OPENCODE_CLI",
                model_name=self.model_name,
                error_message=f"OpenCode CLI adapter parse/execution failure: {str(e)}",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                raw_response=locals().get("stdout_str", "")
            )
