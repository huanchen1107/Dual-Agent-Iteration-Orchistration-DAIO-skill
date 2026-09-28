"""
Codex CLI Backend Adapter for Generic DAIO (Phase B4A / daio-agent/v1).
Executes unattended prompts via the official Codex CLI ('codex exec') using local login sessions.
Consumes natural-language requested_action and returns structured ProposedFileEdit proposals.
Strictly zero direct disk write or git execution authority.
"""

from __future__ import annotations
import asyncio
from ..handoff_contract import Outcome
from .backend_outcomes import classify_process_failure
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

logger = logging.getLogger("DAIO_CodexCLI_Adapter")


def find_codex_cli_path() -> Optional[str]:
    """Find the path to the official Codex CLI executable."""
    env_path = os.environ.get("CODEX_CLI_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    which_path = shutil.which("codex")
    if which_path:
        return which_path

    fallback_paths = [
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
        str(Path.home() / ".local" / "bin" / "codex")
    ]
    for fp in fallback_paths:
        if os.path.isfile(fp) and os.access(fp, os.X_OK):
            return fp

    return None


class CodexCLIAdapter(EngineeringAgentAdapter):
    """
    EngineeringAgentAdapter backend powered by the Codex CLI ('codex exec').
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
        self.cli_path = cli_path or find_codex_cli_path()
        self.model_name = model_name or "o3"
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
        """Extract structured JSON proposal from Codex CLI output or JSONL events."""
        # Check for jsonl events containing assistant messages
        for line in reversed(stdout_str.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    if event.get("type") == "item.completed":
                        item = event.get("item")
                        if (
                            isinstance(item, dict)
                            and item.get("type") == "agent_message"
                            and isinstance(item.get("text"), str)
                            and "proposed_edits" in item["text"]
                        ):
                            return self._parse_json_from_text(item["text"])
                    event_type = event.get("type")
                    msg = event.get("content") or event.get("text") or event.get("message")
                    if event_type not in (None, "message", "assistant_message"):
                        msg = None
                    if isinstance(msg, str) and "proposed_edits" in msg:
                        return self._parse_json_from_text(msg)
                    if "proposed_edits" in event and isinstance(event["proposed_edits"], list):
                        return event
            except Exception:
                pass

        # Fallback to direct text search
        return self._parse_json_from_text(stdout_str)

    def _parse_json_from_text(self, text: str) -> Dict[str, Any]:
        """Extract structured JSON proposal from arbitrary text block."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Empty model response received from Codex CLI.")

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

        raise ValueError(f"Could not parse structured proposed_edits JSON from Codex CLI output. Preview: {clean_text[:250]}")

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not self.cli_path:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                outcome=Outcome.BACKEND_UNAVAILABLE,
                backend_identity="CODEX_CLI",
                model_name=self.model_name,
                error_message="Codex CLI executable ('codex') not found on system PATH.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        prompt_text = self._build_prompt(request)
        cmd = [
            self.cli_path,
            "exec",
            prompt_text,
            "--json",
            "--cd", request.project_root,
        ]
        if self.sandbox:
            cmd.extend(["--sandbox", "read-only"])
        if self.model_name and self.model_name != "codex-default":
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
                failure = classify_process_failure(stdout_str, stderr_str, proc.returncode)
                return AgentTaskProposal(
                    work_id=request.work_id,
                    success=False,
                    outcome=failure.outcome,
                    backend_identity="CODEX_CLI",
                    model_name=self.model_name,
                    error_message=(
                        f"Backend execution failed: {failure.outcome.value} "
                        f"(exit={proc.returncode}; diagnostic={failure.sanitized_reason})"
                    ),
                    started_at=started_at,
                    completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    raw_response=""
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
                backend_identity="CODEX_CLI",
                model_name=self.model_name,
                reasoning_summary=parsed.get("reasoning_summary", ""),
                proposed_edits=edits,
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                raw_response=""
            )

        except asyncio.TimeoutError:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="CODEX_CLI",
                model_name=self.model_name,
                error_message=f"Codex CLI execution timed out after {request.timeout_seconds or self.timeout_seconds}s.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
        except Exception as e:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="CODEX_CLI",
                model_name=self.model_name,
                error_message="Codex CLI adapter parse/execution failure",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                raw_response=""
            )
