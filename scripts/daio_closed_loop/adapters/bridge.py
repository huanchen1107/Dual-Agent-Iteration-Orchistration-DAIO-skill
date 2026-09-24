"""
Architect Bridge Adapters for DAIO Closed Loop (Change 050 Milestone 3 & Generic DAIO v2.1).
Connects to external Web LLM / ChatGPT Project tab via Chrome CDP WebSocket.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from ..models import ArchitectDecision, DAIOWorkItem

logger = logging.getLogger("DAIO_Bridge_Adapter")

UNIVERSAL_PROMPT_APPENDIX = """

---
### 【系統指令：請架構師於回覆末尾輸出標準 JSON 控制區塊】
請在完成專業評析後，務必於回覆的最下方提供如下標準 JSON 格式（以 ```json ``` 包裹），以供 DAIO Orchestrator 自動解析狀態並推進下一階段：
```json
{
  "decision": "APPROVE", 
  "current_phase": "CURRENT_PHASE",
  "next_phase": "NEXT_PHASE",
  "action": "RUN",
  "human_approval_required": false,
  "instruction": "簡述下一步任務重點"
}
```
可選之 decision 值：`APPROVE`（進入下一階段）、`REVISE`（修改重送）、`REJECT`（重作）、`HUMAN_REVIEW`（需人工裁決）、`STOP`（終止閉環）。
"""


VALID_ARCHITECT_DECISIONS = {"APPROVE", "REVISE", "REJECT", "HUMAN_REVIEW", "STOP"}


def extract_all_json_candidates(text: str) -> List[str]:
    """Extract all syntactically complete JSON object substrings from text."""
    candidates = []
    seen = set()

    # 1. Fenced markdown code blocks (handles any language token e.g. ```json:response)
    fence_pattern = r"```[a-zA-Z0-9_\-\:]*[^\n]*\n(.*?)```"
    for block in re.findall(fence_pattern, text, re.DOTALL):
        clean_block = block.strip()
        if clean_block.startswith("{") and clean_block.endswith("}"):
            if clean_block not in seen:
                candidates.append(clean_block)
                seen.add(clean_block)

    # 2. Balanced brace scanner across entire text
    in_string = False
    escape = False
    brace_depth = 0
    start_idx = -1

    for i, ch in enumerate(text):
        if ch == '"' and not escape:
            in_string = not in_string
        elif ch == '\\' and in_string:
            escape = not escape
            continue
        elif not in_string:
            if ch == '{':
                if brace_depth == 0:
                    start_idx = i
                brace_depth += 1
            elif ch == '}':
                if brace_depth > 0:
                    brace_depth -= 1
                    if brace_depth == 0 and start_idx != -1:
                        candidate = text[start_idx : i + 1].strip()
                        if candidate not in seen:
                            candidates.append(candidate)
                            seen.add(candidate)
                        start_idx = -1
        escape = False

    return candidates


def validate_and_build_decision(candidate_str: str, full_raw_text: str) -> Tuple[Optional[ArchitectDecision], Optional[str]]:
    """Validate a candidate JSON string against the ArchitectDecision contract."""
    try:
        data = json.loads(candidate_str, strict=False)
    except Exception as e:
        return None, f"JSON parse error: {str(e)}"

    if not isinstance(data, dict):
        return None, "Root JSON entity is not an object"

    # Validate decision
    raw_decision = str(data.get("decision", "")).strip().upper()
    if raw_decision not in VALID_ARCHITECT_DECISIONS:
        return None, f"Invalid or missing decision: '{raw_decision}' (must be one of {sorted(VALID_ARCHITECT_DECISIONS)})"

    # Validate required fields
    current_phase = str(data.get("current_phase", "")).strip()
    if not current_phase:
        return None, "Missing or empty 'current_phase'"

    instruction = str(data.get("instruction", "")).strip()

    # Optional / defaulted fields
    next_phase = data.get("next_phase")
    if next_phase is not None:
        next_phase = str(next_phase).strip()

    action = str(data.get("action", "RUN")).strip().upper() or "RUN"

    raw_human_req = data.get("human_approval_required", False)
    if isinstance(raw_human_req, str):
        human_approval_required = raw_human_req.lower() in ("true", "1", "yes")
    else:
        human_approval_required = bool(raw_human_req)

    decision = ArchitectDecision(
        decision=raw_decision,
        current_phase=current_phase,
        next_phase=next_phase,
        action=action,
        human_approval_required=human_approval_required,
        instruction=instruction,
        raw_text=full_raw_text,
    )
    return decision, None


def parse_decision_from_text(response_text: str) -> ArchitectDecision:
    """
    Robustly parse structured ArchitectDecision block from LLM response text.
    Extracts all candidates, validates them against schema, and selects the final valid block.
    Fails closed with detailed diagnostic context if no valid block is found.
    """
    if not response_text or not response_text.strip():
        raise ValueError("Cannot parse ArchitectDecision from empty response text.")

    candidates = extract_all_json_candidates(response_text)
    valid_decisions: List[Tuple[ArchitectDecision, str]] = []
    rejection_reasons: List[str] = []

    for idx, cand in enumerate(candidates):
        dec, err = validate_and_build_decision(cand, response_text)
        if dec is not None:
            valid_decisions.append((dec, cand))
        else:
            rejection_reasons.append(f"Candidate #{idx + 1}: {err} (preview: {cand[:80]}...)")

    if valid_decisions:
        # Prefer the final valid control block in the response as requested
        selected_decision, selected_json = valid_decisions[-1]
        logger.info(
            f"Successfully parsed ArchitectDecision: {selected_decision.decision} "
            f"(Total candidates discovered: {len(candidates)}, Valid: {len(valid_decisions)}, "
            f"Selected candidate index: {len(valid_decisions)})"
        )
        return selected_decision

    # Construct rich diagnostic error report
    preview_head = response_text[:200].replace("\n", " ")
    preview_tail = response_text[-200:].replace("\n", " ")
    reasons_str = "; ".join(rejection_reasons) if rejection_reasons else "No JSON candidate structures found"

    raise ValueError(
        f"Could not parse structured ArchitectDecision block from response text. "
        f"[Diagnostics: Response length={len(response_text)}, Discovered candidates={len(candidates)}, "
        f"Validation failures={reasons_str}, Preview head='{preview_head}...', Preview tail='...{preview_tail}']"
    )



class ArchitectBridgeAdapter(ABC):
    """Abstract interface for transmitting review requests to external Architect and receiving decisions."""

    @abstractmethod
    async def transmit_review_request(self, work: DAIOWorkItem, report_markdown: str, timeout_seconds: int = 240) -> ArchitectDecision:
        raise NotImplementedError


def discover_tab_by_endpoint(
    endpoint: Optional[Dict[str, Any]] = None,
    url_pattern: str = "chatgpt.com",
    cdp_port: int = 9222,
) -> Tuple[str, str, str]:
    """
    Discover Chrome tab matching exact Architect Endpoint.
    Enforces 'EXACT_CONVERSATION' routing policy and fail-closed safety.
    """
    import urllib.request
    try:
        req = urllib.request.urlopen(f"http://localhost:{cdp_port}/json/list", timeout=5)
        tabs = json.loads(req.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Could not connect to Chrome CDP at port {cdp_port}. Is Chrome running with --remote-debugging-port={cdp_port}? Error: {e}")

    ep = endpoint or {}
    proj_id = ep.get("project_id")
    conv_id = ep.get("conversation_id")
    canonical_url = ep.get("canonical_url")
    routing_policy = ep.get("routing_policy", "EXACT_CONVERSATION")

    # 1. Match on exact conversation_id
    if conv_id:
        for t in tabs:
            if t.get("type") == "page":
                tab_url = t.get("url", "")
                if conv_id in tab_url and not ("auth/login" in tab_url or "api/auth" in tab_url):
                    return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")

    # 2. Match on canonical_url
    if canonical_url:
        for t in tabs:
            if t.get("type") == "page":
                tab_url = t.get("url", "")
                if canonical_url in tab_url:
                    return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")

    # 3. Match on project_id if routing_policy allows PROJECT_LEVEL
    if proj_id and routing_policy == "PROJECT_LEVEL":
        for t in tabs:
            if t.get("type") == "page" and proj_id in t.get("url", ""):
                return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")

    # If EXACT_CONVERSATION was requested, fail closed rather than sending to wrong tab!
    if conv_id or routing_policy == "EXACT_CONVERSATION":
        available = [f"[{t.get('title')}] -> {t.get('url')}" for t in tabs if t.get("type") == "page"]
        raise RuntimeError(
            f"DAIO-004 Exact Conversation Routing Failed: Could not find active tab for conversation_id '{conv_id}' or canonical_url '{canonical_url}'. "
            f"Fail-closed policy prevented dispatch to unrelated tabs. Available tabs:\n" + "\n".join(available)
        )

    # 4. Fallback pattern match (only if no exact endpoint specified)
    for t in tabs:
        if t.get("type") == "page":
            tab_url = t.get("url", "")
            tab_title = t.get("title", "")
            if url_pattern.lower() in tab_url.lower() or url_pattern.lower() in tab_title.lower():
                return t["webSocketDebuggerUrl"], t["id"], tab_title

    available = [f"[{t.get('title')}] -> {t.get('url')}" for t in tabs if t.get("type") == "page"]
    raise RuntimeError(f"No tab matched pattern '{url_pattern}'. Available tabs:\n" + "\n".join(available))


class ChromeCDPBridgeAdapter(ArchitectBridgeAdapter):
    """
    Live Chrome CDP WebSocket Bridge Adapter with Conversation-Aware Routing.
    Communicates with specific ChatGPT Project conversation on port 9222.
    """

    def __init__(
        self,
        endpoint: Optional[Dict[str, Any]] = None,
        url_pattern: str = "chatgpt.com",
        cdp_port: int = 9222,
    ) -> None:
        self.endpoint = endpoint or {}
        self.url_pattern = url_pattern
        self.cdp_port = cdp_port

    def _get_cdp_client_class(self):
        """Robustly import UniversalCDPClient across module and standalone packaging layouts."""
        try:
            from ...daio_bridge import UniversalCDPClient
            return UniversalCDPClient
        except (ImportError, ValueError):
            pass

        try:
            from scripts.daio_bridge import UniversalCDPClient
            return UniversalCDPClient
        except (ImportError, ValueError):
            pass

        import sys
        scripts_dir = str(Path(__file__).resolve().parent.parent.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from daio_bridge import UniversalCDPClient
        return UniversalCDPClient

    async def transmit_review_request(self, work: DAIOWorkItem, report_markdown: str, timeout_seconds: int = 240) -> ArchitectDecision:
        UniversalCDPClient = self._get_cdp_client_class()

        # Combine work item endpoint with adapter endpoint
        effective_endpoint = dict(self.endpoint)
        if work.architect_endpoint:
            effective_endpoint.update(work.architect_endpoint)

        ws_url, tab_id, tab_title = discover_tab_by_endpoint(
            endpoint=effective_endpoint,
            url_pattern=self.url_pattern,
            cdp_port=self.cdp_port,
        )
        client = UniversalCDPClient(ws_url)
        await client.connect()

        full_prompt = report_markdown + UNIVERSAL_PROMPT_APPENDIX
        try:
            res = await client.send_message(full_prompt, timeout_seconds=timeout_seconds)
            if not res or not res.get("success"):
                raise RuntimeError(f"CDP message dispatch failed: {res.get('error') if res else 'Unknown error'}")

            reply_text = res.get("reply", "")
            return parse_decision_from_text(reply_text)
        finally:
            await client.close()


class MockArchitectBridgeAdapter(ArchitectBridgeAdapter):
    """Mock bridge for deterministic unit testing."""

    def __init__(self, canned_decisions: Optional[List[ArchitectDecision]] = None) -> None:
        self.canned_decisions = canned_decisions or [
            ArchitectDecision(decision="APPROVE", current_phase="M1", instruction="Approved by mock")
        ]
        self.call_history: List[str] = []

    async def transmit_review_request(self, work: DAIOWorkItem, report_markdown: str, timeout_seconds: int = 240) -> ArchitectDecision:
        self.call_history.append(report_markdown)
        if self.canned_decisions:
            return self.canned_decisions.pop(0)
        return ArchitectDecision(decision="APPROVE", current_phase=work.current_stage, instruction="Default approve")
