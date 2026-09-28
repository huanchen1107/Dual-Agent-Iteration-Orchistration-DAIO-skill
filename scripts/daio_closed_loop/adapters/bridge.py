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
import uuid

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

    @abstractmethod
    async def emit_telemetry(self, work: DAIOWorkItem, telemetry_markdown: str, timeout_seconds: int = 30) -> bool:
        """Dispatches a one-way telemetry message without requesting a decision and without waiting for response."""
        raise NotImplementedError


def normalize_canonical_url(url_str: Optional[str]) -> Optional[str]:
    """Strip any surrounding Markdown link wrapping or angle brackets from URL."""
    if not url_str or not isinstance(url_str, str):
        return None
    clean = url_str.strip()
    m = re.match(r"^\[.*?\]\((https?://[^\s\)]+)\)$", clean)
    if m:
        clean = m.group(1).strip()
    m2 = re.match(r"^<(https?://[^>]+)>$", clean)
    if m2:
        clean = m2.group(1).strip()
    return clean


def extract_chatgpt_identifiers(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract (chatgpt_project_id, conversation_id) tuple from ChatGPT URL."""
    if not url or not isinstance(url, str):
        return None, None
    clean_url = normalize_canonical_url(url) or url
    proj_m = re.search(r'/g/([a-zA-Z0-9\-_]+)', clean_url)
    conv_m = re.search(r'/c/([a-zA-Z0-9\-_]+)', clean_url)
    proj_id = proj_m.group(1) if proj_m else None
    conv_id = conv_m.group(1) if conv_m else None
    return proj_id, conv_id


def resolve_architect_endpoint(
    endpoint: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    project_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Resolve effective architect endpoint by looking up endpoint_key or default_architect_endpoint in registry.
    """
    cfg = dict(config) if config else {}
    if not cfg:
        p_root = Path(project_root).resolve() if project_root else Path.cwd()
        cfg_file = p_root / "_daio" / "daio_config.json"
        if not cfg_file.exists():
            cfg_file = p_root / "daio_config.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    ep = dict(endpoint) if isinstance(endpoint, dict) else {}
    registry = cfg.get("architect_endpoints", {})
    endpoint_key = ep.get("endpoint_key") or (cfg.get("default_architect_endpoint") if not ep else None)

    resolved: Dict[str, Any] = {}
    if endpoint_key and endpoint_key in registry:
        resolved = dict(registry[endpoint_key])
    elif not ep and cfg.get("architect_endpoint"):
        resolved = dict(cfg.get("architect_endpoint"))

    resolved.update(ep)

    if "canonical_url" in resolved and resolved["canonical_url"]:
        resolved["canonical_url"] = normalize_canonical_url(resolved["canonical_url"])

    # If project_id or conversation_id missing, extract from canonical_url
    if resolved.get("canonical_url"):
        c_proj, c_conv = extract_chatgpt_identifiers(resolved["canonical_url"])
        if not resolved.get("chatgpt_project_id") and c_proj:
            resolved["chatgpt_project_id"] = c_proj
        if not resolved.get("project_id") and c_proj:
            resolved["project_id"] = c_proj
        if not resolved.get("conversation_id") and c_conv:
            resolved["conversation_id"] = c_conv

    return resolved


def discover_tab_by_endpoint(
    endpoint: Optional[Dict[str, Any]] = None,
    url_pattern: str = "chatgpt.com",
    cdp_port: int = 9222,
    max_retries: int = 3,
    raw_tabs: Optional[List[Dict[str, Any]]] = None,
    auto_recover_closed_tab: bool = True,
    config: Optional[Dict[str, Any]] = None,
    project_root: Optional[str | Path] = None,
    return_metadata: bool = False,
) -> Tuple[str, str, str] | Tuple[str, str, str, Dict[str, Any]]:
    """
    Discover Chrome tab matching exact Architect Endpoint.
    Enforces 'DAIO-004 EXACT_CONVERSATION' routing policy and fail-closed safety with bounded retry budget.
    Verifies BOTH ChatGPT Project ID and Conversation ID before selection or dispatch.
    If canonical tab is not open, safely opens exact canonical URL on authenticated profile and re-verifies.
    """
    import urllib.request
    import urllib.parse
    import time

    def fetch_tabs() -> List[Dict[str, Any]]:
        try:
            req = urllib.request.urlopen(f"http://localhost:{cdp_port}/json/list", timeout=3)
            return json.loads(req.read().decode("utf-8"))
        except Exception:
            return []

    tabs: List[Dict[str, Any]] = []
    if raw_tabs is not None:
        tabs = raw_tabs
    else:
        for attempt in range(1, max_retries + 1):
            tabs = fetch_tabs()
            if tabs:
                break
            if attempt < max_retries:
                time.sleep(0.5)

    before_ids = [t["id"] for t in tabs if t.get("type") == "page"]

    ep = resolve_architect_endpoint(endpoint=endpoint, config=config, project_root=project_root)
    proj_id = ep.get("chatgpt_project_id") or ep.get("project_id")
    conv_id = ep.get("conversation_id")
    canonical_url = normalize_canonical_url(ep.get("canonical_url"))
    routing_policy = ep.get("routing_policy", "EXACT_CONVERSATION")

    if canonical_url:
        canon_proj, canon_conv = extract_chatgpt_identifiers(canonical_url)
        if not proj_id and canon_proj:
            proj_id = canon_proj
        if not conv_id and canon_conv:
            conv_id = canon_conv

    def find_matching_tab(tab_list: List[Dict[str, Any]]) -> Optional[Tuple[str, str, str]]:
        for t in tab_list:
            if t.get("type") != "page":
                continue
            tab_url = t.get("url", "")
            if "auth/login" in tab_url or "api/auth" in tab_url:
                continue

            tab_proj, tab_conv = extract_chatgpt_identifiers(tab_url)

            # Strict Invariant 1: If BOTH proj_id and conv_id are specified, BOTH must match exactly
            if proj_id and conv_id:
                if tab_proj == proj_id and tab_conv == conv_id:
                    return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")
                continue

            # Strict Invariant 2: If conv_id specified without project_id, conversation must match
            if conv_id and not proj_id:
                if tab_conv == conv_id:
                    return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")
                continue

            # Strict Invariant 3: Project-level routing only when routing_policy allows PROJECT_LEVEL
            if proj_id and not conv_id and routing_policy == "PROJECT_LEVEL":
                if tab_proj == proj_id:
                    return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")
                continue

            # Strict Invariant 4: Direct canonical URL match (if neither ID parsed)
            if canonical_url and canonical_url in tab_url:
                return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")

        return None

    def make_telemetry(selected_id: str, current_tabs: List[Dict[str, Any]]) -> Dict[str, Any]:
        after_ids = [t["id"] for t in current_tabs if t.get("type") == "page"]
        created = list(set(after_ids) - set(before_ids))
        closed = list(set(before_ids) - set(after_ids))
        return {
            "targets_before": before_ids,
            "targets_after": after_ids,
            "target_created_ids": created,
            "target_closed_ids": closed,
            "new_tab_created": len(created) > 0,
            "selected_target_id": selected_id,
            "pinned_target_id": selected_id,
        }

    match = find_matching_tab(tabs)
    if match:
        ws_url, tab_id, tab_title = match
        if return_metadata:
            return ws_url, tab_id, tab_title, make_telemetry(tab_id, tabs)
        return match

    # Auto-recovery: If exact tab is not currently open, safely open canonical URL on Chrome CDP
    target_recovery_url = canonical_url
    if not target_recovery_url and proj_id and conv_id:
        target_recovery_url = f"https://chatgpt.com/g/{proj_id}/c/{conv_id}"

    if auto_recover_closed_tab and target_recovery_url and raw_tabs is None:
        try:
            encoded_url = urllib.parse.quote(target_recovery_url, safe=":/%#?=@[]!$&'()*+,;")
            new_tab_url = f"http://localhost:{cdp_port}/json/new?{encoded_url}"
            req = urllib.request.Request(new_tab_url, method="PUT")
            try:
                urllib.request.urlopen(req, timeout=3)
            except Exception:
                urllib.request.urlopen(new_tab_url, timeout=3)

            # Poll for new tab to register and load
            for _ in range(10):
                time.sleep(0.5)
                refreshed_tabs = fetch_tabs()
                recovered_match = find_matching_tab(refreshed_tabs)
                if recovered_match:
                    ws_url, tab_id, tab_title = recovered_match
                    if return_metadata:
                        return ws_url, tab_id, tab_title, make_telemetry(tab_id, refreshed_tabs)
                    return recovered_match
                tabs = refreshed_tabs
        except Exception as ex:
            logger.warning(f"Could not auto-open canonical tab '{target_recovery_url}': {ex}")

    # If EXACT_CONVERSATION was requested (or IDs were specified), fail closed rather than sending to wrong tab!
    if conv_id or proj_id or routing_policy == "EXACT_CONVERSATION":
        available = [f"[{t.get('title')}] -> {t.get('url')}" for t in tabs if t.get("type") == "page"]
        raise RuntimeError(
            f"DAIO-004 Exact Conversation Routing Failed: Could not find active tab for project_id '{proj_id}', conversation_id '{conv_id}', or canonical_url '{canonical_url}'. "
            f"Fail-closed policy prevented dispatch to unrelated tabs. Available tabs:\n" + "\n".join(available)
        )

    # 4. Fallback pattern match (only if no exact endpoint specified)
    for t in tabs:
        if t.get("type") == "page":
            tab_url = t.get("url", "")
            tab_title = t.get("title", "")
            if url_pattern.lower() in tab_url.lower() or url_pattern.lower() in tab_title.lower():
                ws_url, tab_id = t["webSocketDebuggerUrl"], t["id"]
                if return_metadata:
                    return ws_url, tab_id, tab_title, make_telemetry(tab_id, tabs)
                return ws_url, tab_id, tab_title

    available = [f"[{t.get('title')}] -> {t.get('url')}" for t in tabs if t.get("type") == "page"]
    raise RuntimeError(f"No tab matched pattern '{url_pattern}'. Available tabs:\n" + "\n".join(available))


def probe_architect_endpoint(
    endpoint: Optional[Dict[str, Any]] = None,
    cdp_port: int = 9222,
    raw_tabs: Optional[List[Dict[str, Any]]] = None,
    auto_recover_closed_tab: bool = True,
    config: Optional[Dict[str, Any]] = None,
    project_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    DAIO Endpoint Onboarding & Minimal-Probe Protocol (EOMP).
    Performs non-destructive preflight verification to prove:
    1. CDP reachable
    2. Exact Project ID match
    3. Exact Conversation ID match
    4. Canonical URL identity verified
    5. Session ready (authenticated, non-login page)
    Fails closed if verification does not pass.
    """
    resolved = resolve_architect_endpoint(endpoint=endpoint, config=config, project_root=project_root)
    proj_id = resolved.get("chatgpt_project_id") or resolved.get("project_id")
    conv_id = resolved.get("conversation_id")
    canonical_url = resolved.get("canonical_url")

    try:
        ws_url, tab_id, tab_title = discover_tab_by_endpoint(
            endpoint=resolved,
            cdp_port=cdp_port,
            raw_tabs=raw_tabs,
            auto_recover_closed_tab=auto_recover_closed_tab,
            config=config,
            project_root=project_root,
        )
        return {
            "success": True,
            "status": "VERIFIED",
            "endpoint": resolved,
            "project_id": proj_id,
            "conversation_id": conv_id,
            "canonical_url": canonical_url,
            "tab_id": tab_id,
            "tab_title": tab_title,
            "webSocketDebuggerUrl": ws_url,
            "error": None,
        }
    except Exception as ex:
        return {
            "success": False,
            "status": "PROBE_FAILED",
            "endpoint": resolved,
            "project_id": proj_id,
            "conversation_id": conv_id,
            "canonical_url": canonical_url,
            "tab_id": None,
            "tab_title": None,
            "webSocketDebuggerUrl": None,
            "error": str(ex),
        }


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
        max_discovery_retries: int = 3,
    ) -> None:
        self.endpoint = endpoint or {}
        self.url_pattern = url_pattern
        self.cdp_port = cdp_port
        self.max_discovery_retries = max_discovery_retries

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

        ws_url, tab_id, tab_title, telemetry = discover_tab_by_endpoint(
            endpoint=effective_endpoint,
            url_pattern=self.url_pattern,
            cdp_port=self.cdp_port,
            max_retries=self.max_discovery_retries,
            return_metadata=True,
        )

        nonce = f"DAIO-C1.2-PROBE-{uuid.uuid4().hex[:8]}"
        telemetry["probe_nonce"] = nonce
        logger.info(f"Target Lifecycle Telemetry: {json.dumps(telemetry)}")

        client = UniversalCDPClient(ws_url)
        await client.connect()

        full_prompt = f"[{nonce}]\n\n" + report_markdown + UNIVERSAL_PROMPT_APPENDIX
        try:
            res = await client.send_message(full_prompt, timeout_seconds=timeout_seconds, probe_nonce=nonce)
            if not res or not res.get("success"):
                raise RuntimeError(f"CDP message dispatch failed: {res.get('error') if res else 'Unknown error'}")

            reply_text = res.get("reply", "")
            return parse_decision_from_text(reply_text)
        finally:
            await client.close()

    async def emit_telemetry(self, work: DAIOWorkItem, telemetry_markdown: str, timeout_seconds: int = 30) -> bool:
        """
        Dispatches telemetry. By default, routine telemetry remains local and durable (logged)
        to prevent flooding the Architect chat window.
        """
        logger.info(f"📡 Routine telemetry recorded for work {work.work_id}: {telemetry_markdown[:120]}...")
        if not self.endpoint.get("post_routine_telemetry", False):
            return True

        UniversalCDPClient = self._get_cdp_client_class()
        effective_endpoint = dict(self.endpoint)
        if work.architect_endpoint:
            effective_endpoint.update(work.architect_endpoint)

        try:
            ws_url, tab_id, tab_title = discover_tab_by_endpoint(
                endpoint=effective_endpoint,
                url_pattern=self.url_pattern,
                cdp_port=self.cdp_port,
                max_retries=self.max_discovery_retries,
            )
            client = UniversalCDPClient(ws_url)
            await client.connect()
            try:
                res = await client.post_message_only(telemetry_markdown)
                return bool(res and res.get("success"))
            finally:
                await client.close()
        except Exception as ex:
            logger.warning(f"Failed to dispatch telemetry via CDP bridge: {ex}")
            return False


class MockArchitectBridgeAdapter(ArchitectBridgeAdapter):
    """Mock bridge for deterministic unit testing."""

    def __init__(self, canned_decisions: Optional[List[ArchitectDecision]] = None) -> None:
        self.canned_decisions = canned_decisions or [
            ArchitectDecision(decision="APPROVE", current_phase="M1", instruction="Approved by mock")
        ]
        self.call_history: List[str] = []
        self.telemetry_history: List[str] = []

    async def transmit_review_request(self, work: DAIOWorkItem, report_markdown: str, timeout_seconds: int = 240) -> ArchitectDecision:
        self.call_history.append(report_markdown)
        if self.canned_decisions:
            return self.canned_decisions.pop(0)
        return ArchitectDecision(decision="APPROVE", current_phase=work.current_stage, instruction="Default approve")

    async def emit_telemetry(self, work: DAIOWorkItem, telemetry_markdown: str, timeout_seconds: int = 30) -> bool:
        self.telemetry_history.append(telemetry_markdown)
        return True


class GeminiArchitectBridgeAdapter(ArchitectBridgeAdapter):
    """
    Genuine provider-neutral LLM Architect Bridge using Google Gemini API.
    Consumes engineering report and returns parsed ArchitectDecision.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-pro",
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model_name = model_name

    async def transmit_review_request(self, work: DAIOWorkItem, report_markdown: str, timeout_seconds: int = 240) -> ArchitectDecision:
        if not self.api_key:
            raise RuntimeError("GeminiArchitectBridgeAdapter: GEMINI_API_KEY or GOOGLE_API_KEY is not configured.")

        system_instruction = (
            "You are the Lead System Architect reviewing an automated engineering report.\n"
            "Analyze the changes, verify correctness, and provide an architectural decision.\n"
            "At the end of your review, you MUST output a standard JSON code block:\n"
            "```json\n"
            "{\n"
            '  "decision": "APPROVE",\n'
            f'  "current_phase": "{work.current_stage}",\n'
            f'  "next_phase": "{work.authorized_next_phase or "COMPLETED"}",\n'
            '  "action": "RUN",\n'
            '  "human_approval_required": false,\n'
            '  "instruction": "Summary of architectural review decision"\n'
            "}\n"
            "```\n"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\nEngineering Report:\n{report_markdown}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "text/plain"
            }
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        data = json.dumps(payload).encode("utf-8")
        import urllib.request
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        loop = asyncio.get_event_loop()
        def _call_api():
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))

        resp_data = await loop.run_in_executor(None, _call_api)
        text = resp_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return parse_decision_from_text(text)

    async def emit_telemetry(self, work: DAIOWorkItem, telemetry_markdown: str, timeout_seconds: int = 30) -> bool:
        logger.info(f"📡 Gemini Architect Telemetry recorded for work {work.work_id}: {telemetry_markdown[:120]}...")
        return True

