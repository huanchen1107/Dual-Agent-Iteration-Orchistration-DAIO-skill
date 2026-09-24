"""
Gemini Reference Backend for Generic DAIO Engineering Agent Adapter (Phase S5.2).
Consumes natural-language requested_action and returns structured ProposedFileEdit proposals.
Strictly zero direct disk write or git execution authority.
"""

from __future__ import annotations
import datetime
import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional

from .agent_contract import (
    AgentTaskRequest,
    AgentTaskProposal,
    ProposedFileEdit,
    EngineeringAgentAdapter
)


class GeminiEngineeringAgentAdapter(EngineeringAgentAdapter):
    """
    Genuine reference backend using Google Gemini API.
    Reads credentials dynamically from environment (GEMINI_API_KEY / GOOGLE_API_KEY).
    Fails closed if credentials are unavailable.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-pro",
        api_url_template: str = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model_name = model_name
        self.api_url_template = api_url_template

    def _build_system_prompt(self, request: AgentTaskRequest) -> str:
        context_str = ""
        for path, content in request.context_files.items():
            context_str += f"\n--- File: {path} ---\n{content}\n"

        prompt = f"""You are an autonomous senior software engineer working in project: {request.project_root}.

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

    def _parse_llm_response(self, text: str) -> Dict[str, Any]:
        """Parse structured proposal JSON from raw LLM output."""
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

        raise ValueError("Could not parse structured proposed_edits JSON from Gemini response.")

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # Fail closed if credentials are not configured
        if not self.api_key:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="GEMINI_API",
                model_name=self.model_name,
                error_message="GEMINI_API_KEY or GOOGLE_API_KEY environment variable is missing.",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        prompt_text = self._build_system_prompt(request)
        url = self.api_url_template.format(model=self.model_name, key=self.api_key)

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192
            }
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))

            candidates = resp_json.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Gemini API returned no candidates: {resp_json}")

            raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            parsed_data = self._parse_llm_response(raw_text)

            edits = []
            for item in parsed_data.get("proposed_edits", []):
                edits.append(
                    ProposedFileEdit(
                        file_path=item.get("file_path", "").strip(),
                        new_content=item.get("new_content", ""),
                        description=item.get("description", "")
                    )
                )

            return AgentTaskProposal(
                work_id=request.work_id,
                success=True,
                proposed_edits=edits,
                backend_identity="GEMINI_API",
                model_name=self.model_name,
                reasoning_summary=parsed_data.get("reasoning_summary", ""),
                raw_response=raw_text,
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        except Exception as ex:
            return AgentTaskProposal(
                work_id=request.work_id,
                success=False,
                backend_identity="GEMINI_API",
                model_name=self.model_name,
                error_message=f"Gemini agent execution failed: {str(ex)}",
                started_at=started_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
