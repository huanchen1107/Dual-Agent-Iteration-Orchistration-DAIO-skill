"""
Gemini CLI Backend Adapter for Generic DAIO (Phase B4A / daio-agent/v1).
Executes unattended prompts via the official Gemini CLI ('gemini') using local login sessions.
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

logger = logging.getLogger("DAIO_GeminiCLI_Adapter")


def find_gemini_cli_path() -> Optional[str]:
    """Find the path to the official Gemini CLI executable."""
    env_path = os.environ.get("GEMINI_CLI_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    which_path = shutil.which("gemini")
    if which_path:
        return which_path

    fallback_paths = [
        "/opt/homebrew/bin/gemini",
        "/usr/local/bin/gemini",
        str(Path.home() / ".local" / "bin" / "gemini")
    ]
    for fp in fallback_paths:
        if os.path.isfile(fp) and os.access(fp, os.X_OK):
            return fp

    return None


class GeminiCLIAdapter(EngineeringAgentAdapter):
    """
    EngineeringAgentAdapter backend powered by the Gemini CLI ('gemini').
    Uses existing authenticated local CLI sessions (login-first) without requiring API keys.
    """

    def __init__(
        self,
        cli_path: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: int = 300,
        unattended: bool = True,
        sandbox: bool = True,
    ) -> None:
        self.cli_path = cli_path or find_gemini_cli_path()
        self.model_name = model_name or "gemini-2.5-pro"
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
        """Extract outer JSON envelope from Gemini CLI stdout if formatted as JSON."""
        try:
            return json.loads(stdout_str.strip())
        except Exception:
            pass

        start_idx = stdout_str.find("{")
        end_idx = stdout_str.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = stdout_str[start_idx:end_idx + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass

        return {"response": stdout_str}

    def _parse_proposal_from_response(self, text: str) -> Dict[str, Any]:
        """Extract structured JSON proposal from response text."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Empty model response received from Gemini CLI.")

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
            f"Could not parse structured proposed_edits JSON from Gemini CLI output. Preview: {clean_text[:250]}"
        )

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not self.cli_path:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="GEMINI_CLI",
                model_name=self.model_name,
                error_message="Gemini CLI executable ('gemini') not found on system PATH.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        prompt_text = self._build_prompt(request)
        cmd = [
            self.cli_path,
            "-p", prompt_text,
            "-o", "json",
            "--approval-mode", "yolo" if self.unattended else "default",
        ]
        if self.sandbox:
            cmd.append("-s")
        if self.model_name and self.model_name != "gemini-default":
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
                    backend_identity="GEMINI_CLI",
                    model_name=self.model_name,
                    error_message=f"Gemini CLI failed with exit code {proc.returncode}: {stderr_str or stdout_str[:300]}",
                    started_at=started_at,
                    completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    raw_response=stdout_str
                )

            # Extract outer envelope and response text
            envelope = self._extract_outer_envelope(stdout_str)
            response_text = envelope.get("response", stdout_str)
            if isinstance(response_text, dict):
                parsed = response_text
            else:
                parsed = self._parse_proposal_from_response(str(response_text))

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
                backend_identity="GEMINI_CLI",
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
                backend_identity="GEMINI_CLI",
                model_name=self.model_name,
                error_message=f"Gemini CLI execution timed out after {request.timeout_seconds or self.timeout_seconds}s.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
        except Exception as e:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="GEMINI_CLI",
                model_name=self.model_name,
                error_message=f"Gemini CLI adapter parse/execution failure: {str(e)}",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                raw_response=locals().get("stdout_str", "")
            )
