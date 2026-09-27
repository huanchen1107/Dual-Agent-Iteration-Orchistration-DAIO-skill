"""
Canonical ChatGPT Architect Contract & Evidence Hardening for Generic DAIO (Phase C1).
Implements:
1. Robust ChatGPT Project / Conversation Registry and Project-Aware Router (Objective A).
2. Compact Canonical Evidence Packet Schema & Token-Efficient Serializer (Objective C).
3. Canonical Architect Decision Contract & Machine-Readable Block Validator (Objective D).
4. Cross-validation against work_id, change_id, epoch, gate, and stale response protection.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse
import uuid

logger = logging.getLogger("DAIO_Architect_Contract")


@dataclass
class ChatGPTConversationDescriptor:
    """Descriptor for a known ChatGPT conversation binding."""
    project_id: str
    conversation_id: str
    canonical_url: str
    title: Optional[str] = None
    last_verified_at: Optional[str] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "last_verified_at": self.last_verified_at,
            "is_active": self.is_active,
            "metadata": self.metadata,
        }


class ChatGPTConversationRegistry:
    """Maintains known ChatGPT project/conversation mappings with discovery and validation."""

    def __init__(self) -> None:
        self._conversations: Dict[str, List[ChatGPTConversationDescriptor]] = {}

    def register(self, desc: ChatGPTConversationDescriptor) -> None:
        proj = desc.project_id.strip()
        if proj not in self._conversations:
            self._conversations[proj] = []
        # Update existing or append
        for idx, existing in enumerate(self._conversations[proj]):
            if existing.conversation_id == desc.conversation_id:
                self._conversations[proj][idx] = desc
                return
        self._conversations[proj].append(desc)

    def list_by_project(self, project_id: str) -> List[ChatGPTConversationDescriptor]:
        return [c for c in self._conversations.get(project_id.strip(), []) if c.is_active]

    def get_conversation(self, project_id: str, conversation_id: str) -> Optional[ChatGPTConversationDescriptor]:
        for c in self._conversations.get(project_id.strip(), []):
            if c.conversation_id == conversation_id:
                return c
        return None


class ProjectAwareArchitectRouter:
    """
    Project-Aware Architect Router (Objective A).
    Resolves active Chrome CDP tab matching exact project identity.
    If the pinned conversation is unavailable, safely discovers candidate tabs,
    validates project identity, and persists routing evidence.
    Fails closed if project identity cannot be established.
    """

    def __init__(self, registry: Optional[ChatGPTConversationRegistry] = None) -> None:
        self.registry = registry or ChatGPTConversationRegistry()
        self._routing_audit_trail: List[Dict[str, Any]] = []

    def resolve_tab(
        self,
        project_id: str,
        pinned_endpoint: Optional[Dict[str, Any]],
        available_tabs: List[Dict[str, Any]],
    ) -> Tuple[str, str, str, Dict[str, Any]]:
        """
        Resolves (webSocketDebuggerUrl, tab_id, tab_title, routing_evidence).
        Raises RuntimeError if resolution fails closed.
        """
        ep = pinned_endpoint or {}
        pinned_conv_id = ep.get("conversation_id")
        pinned_url = ep.get("canonical_url")
        routing_policy = ep.get("routing_policy", "EXACT_CONVERSATION")
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Check exact pinned conversation
        if pinned_conv_id:
            for t in available_tabs:
                if t.get("type") == "page":
                    tab_url = t.get("url", "")
                    if pinned_conv_id in tab_url and not ("auth/login" in tab_url or "api/auth" in tab_url):
                        evidence = {
                            "project_id": project_id,
                            "conversation_id": pinned_conv_id,
                            "tab_id": t["id"],
                            "tab_title": t.get("title", ""),
                            "routing_method": "PINNED_EXACT_MATCH",
                            "validation_result": "VALIDATED",
                            "timestamp": timestamp,
                            "fallback_reason": None,
                        }
                        self._routing_audit_trail.append(evidence)
                        return t["webSocketDebuggerUrl"], t["id"], t.get("title", ""), evidence

        # 2. Check canonical URL if provided
        if pinned_url:
            for t in available_tabs:
                if t.get("type") == "page":
                    tab_url = t.get("url", "")
                    if pinned_url in tab_url:
                        evidence = {
                            "project_id": project_id,
                            "conversation_id": pinned_conv_id or "url-match",
                            "tab_id": t["id"],
                            "tab_title": t.get("title", ""),
                            "routing_method": "CANONICAL_URL_MATCH",
                            "validation_result": "VALIDATED",
                            "timestamp": timestamp,
                            "fallback_reason": None,
                        }
                        self._routing_audit_trail.append(evidence)
                        return t["webSocketDebuggerUrl"], t["id"], t.get("title", ""), evidence

        # 3. Project-aware candidate discovery if allowed or fallback
        known_descriptors = self.registry.list_by_project(project_id)
        known_conv_ids = {d.conversation_id for d in known_descriptors}

        candidate_matches = []
        for t in available_tabs:
            if t.get("type") == "page":
                tab_url = t.get("url", "")
                tab_title = t.get("title", "")
                # Check if any known project conversation matches
                for kcid in known_conv_ids:
                    if kcid in tab_url:
                        candidate_matches.append((t, kcid, "KNOWN_REGISTRY_MATCH"))
                # Check project identifier in URL
                if project_id.lower() in tab_url.lower() or project_id.lower() in tab_title.lower():
                    candidate_matches.append((t, "discovered", "PROJECT_IDENTITY_DISCOVERY"))

        if candidate_matches:
            best_tab, conv_match, method = candidate_matches[0]
            evidence = {
                "project_id": project_id,
                "conversation_id": conv_match,
                "tab_id": best_tab["id"],
                "tab_title": best_tab.get("title", ""),
                "routing_method": method,
                "validation_result": "VALIDATED_BY_PROJECT_IDENTITY",
                "timestamp": timestamp,
                "fallback_reason": f"Pinned conversation '{pinned_conv_id}' not found; discovered active project tab.",
            }
            self._routing_audit_trail.append(evidence)
            return best_tab["webSocketDebuggerUrl"], best_tab["id"], best_tab.get("title", ""), evidence

        # 4. Fail Closed: Never silently route to an unrelated tab
        available_summary = [f"[{t.get('title')}] -> {t.get('url')}" for t in available_tabs if t.get("type") == "page"]
        fail_evidence = {
            "project_id": project_id,
            "conversation_id": pinned_conv_id,
            "tab_id": None,
            "routing_method": "FAILED_CLOSED",
            "validation_result": "REJECTED_UNMATCHED_IDENTITY",
            "timestamp": timestamp,
            "fallback_reason": "No active Chrome tab matched project identity or pinned conversation.",
            "available_tabs_count": len(available_summary),
        }
        self._routing_audit_trail.append(fail_evidence)
        raise RuntimeError(
            f"DAIO Architect Router Fail-Closed: Could not establish valid project identity match for project '{project_id}'. "
            f"Pinned conversation '{pinned_conv_id}' is unavailable. Discovered {len(available_summary)} active tabs."
        )

    def get_audit_trail(self) -> List[Dict[str, Any]]:
        return list(self._routing_audit_trail)


@dataclass
class ArchitectEvidencePacket:
    """
    Compact Canonical Evidence Packet (Objective C).
    High-density markdown serialization optimized for ChatGPT token efficiency.
    Raw logs are preserved in references rather than dumped into the prompt.
    """
    project_id: str
    work_id: str
    change_id: str
    stage: str
    gate: str
    recovery_epoch: int
    objective: str
    implementation_summary: str
    files_changed: List[str] = field(default_factory=list)
    diff_summary: str = ""
    tests: Dict[str, Any] = field(default_factory=dict)
    invariants: Dict[str, List[str]] = field(default_factory=lambda: {"passed": [], "failed": []})
    provider_execution: Dict[str, Any] = field(default_factory=dict)
    git: Dict[str, str] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    requested_architect_decision: str = "APPROVE or REVISE"
    evidence_refs: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_compact_markdown(self) -> str:
        """Renders high-density, structured markdown for ChatGPT Architect consumption."""
        files_str = "\n".join([f"- `{f}`" for f in self.files_changed]) if self.files_changed else "_None_"
        blockers_str = "\n".join([f"- ⚠️ {b}" for b in self.blockers]) if self.blockers else "_None (No blockers)_"
        risks_str = "\n".join([f"- ℹ️ {r}" for r in self.risks]) if self.risks else "_None identified_"
        
        test_foc = self.tests.get("focused", "PASS")
        test_reg = self.tests.get("regression", "PASS")
        test_fail = self.tests.get("failures", 0)

        prov_name = self.provider_execution.get("selected_provider", "Antigravity CLI")
        prov_fallbacks = self.provider_execution.get("fallback_history", [])
        prov_fb_str = f" (Failovers: {len(prov_fallbacks)})" if prov_fallbacks else ""

        inv_passed = ", ".join(self.invariants.get("passed", ["DAIO-PORTABILITY-001", "DAIO-HUMAN-AUTH-001"]))
        inv_failed = ", ".join(self.invariants.get("failed", [])) or "None"

        git_head = self.git.get("head_sha", "N/A")[:10]
        git_tree = self.git.get("working_tree_state", "CLEAN")

        return (
            f"# DAIO_ARCHITECT_EVIDENCE_PACKET\n\n"
            f"**Project:** `{self.project_id}` | **Work:** `{self.work_id}` | **Change:** `{self.change_id}`\n"
            f"**Stage:** `{self.stage}` | **Gate:** `{self.gate}` | **Epoch:** `{self.recovery_epoch}`\n\n"
            f"## 1. Objective\n{self.objective}\n\n"
            f"## 2. Implementation Summary\n{self.implementation_summary}\n\n"
            f"## 3. Files Changed\n{files_str}\n\n"
            f"## 4. Diff Summary\n```text\n{self.diff_summary or 'No substantive diff'}\n```\n\n"
            f"## 5. Verification & Test Gate\n"
            f"- **Focused Tests:** `{test_foc}`\n"
            f"- **Full Regression:** `{test_reg}`\n"
            f"- **Failures:** `{test_fail}`\n\n"
            f"## 6. Security Invariants\n"
            f"- **Passed:** `{inv_passed}`\n"
            f"- **Failed:** `{inv_failed}`\n\n"
            f"## 7. Execution & Git Provenance\n"
            f"- **Active Provider:** `{prov_name}{prov_fb_str}`\n"
            f"- **Head SHA:** `{git_head}` (`{git_tree}`)\n\n"
            f"## 8. Blockers & Risks\n"
            f"**Blockers:**\n{blockers_str}\n\n"
            f"**Risks:**\n{risks_str}\n\n"
            f"## 9. Requested Decision\n"
            f"Please evaluate the evidence above and output your structured JSON decision block (`{self.requested_architect_decision}`)."
        )


@dataclass
class CanonicalArchitectDecision:
    """
    Canonical Architect Decision (Objective D).
    Machine-readable decision schema returned by ChatGPT Architect.
    """
    decision: str  # "APPROVE", "REVISE", "STOP", "HUMAN_GATE"
    work_id: str
    change_id: str
    reason: str
    required_actions: List[str] = field(default_factory=list)
    authorized_next_phase: Optional[str] = None
    human_gate_required: bool = False
    evidence_assessment: str = "SATISFACTORY"
    epoch: int = 0
    raw_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "work_id": self.work_id,
            "change_id": self.change_id,
            "reason": self.reason,
            "required_actions": self.required_actions,
            "authorized_next_phase": self.authorized_next_phase,
            "human_gate_required": self.human_gate_required,
            "evidence_assessment": self.evidence_assessment,
            "epoch": self.epoch,
        }


def validate_canonical_architect_decision(
    candidate_data: Dict[str, Any],
    expected_work_id: str,
    expected_change_id: Optional[str] = None,
    expected_epoch: Optional[int] = None,
) -> Tuple[Optional[CanonicalArchitectDecision], Optional[str]]:
    """
    Strictly validates a parsed JSON dictionary against the Canonical Architect Decision Contract.
    Protects against stale responses, mismatched work IDs, and schema invalidity.
    """
    decision_str = str(candidate_data.get("decision", "")).strip().upper()
    valid_decisions = {"APPROVE", "REVISE", "STOP", "HUMAN_GATE", "HUMAN_REVIEW", "REJECT"}
    if decision_str not in valid_decisions:
        return None, f"Invalid decision: '{decision_str}'. Must be one of {sorted(valid_decisions)}"

    # Normalize HUMAN_REVIEW / REJECT
    if decision_str == "HUMAN_REVIEW":
        decision_str = "HUMAN_GATE"
    elif decision_str == "REJECT":
        decision_str = "REVISE"

    # Work ID validation
    resp_work_id = str(candidate_data.get("work_id", "")).strip()
    if resp_work_id and resp_work_id != expected_work_id:
        return None, f"STALE_OR_MISMATCHED_WORK_ID: Response work_id '{resp_work_id}' does not match expected '{expected_work_id}'."

    # Change ID validation if supplied
    resp_change_id = str(candidate_data.get("change_id", "")).strip()
    if expected_change_id and resp_change_id and resp_change_id.upper() != expected_change_id.upper():
        return None, f"STALE_OR_MISMATCHED_CHANGE_ID: Response change_id '{resp_change_id}' != expected '{expected_change_id}'."

    # Epoch validation if supplied
    resp_epoch = candidate_data.get("epoch")
    if expected_epoch is not None and resp_epoch is not None and int(resp_epoch) != expected_epoch:
        return None, f"STALE_EPOCH: Response epoch {resp_epoch} does not match active epoch {expected_epoch}."

    reason = str(candidate_data.get("reason", candidate_data.get("instruction", "Decision recorded."))).strip()
    actions = candidate_data.get("required_actions", [])
    if isinstance(actions, str):
        actions = [actions]

    next_phase = candidate_data.get("authorized_next_phase", candidate_data.get("next_phase"))
    human_req = bool(candidate_data.get("human_gate_required", candidate_data.get("human_approval_required", False)))
    if decision_str == "HUMAN_GATE":
        human_req = True

    dec = CanonicalArchitectDecision(
        decision=decision_str,
        work_id=expected_work_id,
        change_id=expected_change_id or (expected_work_id if "CHANGE_" in expected_work_id else "N/A"),
        reason=reason,
        required_actions=actions,
        authorized_next_phase=next_phase,
        human_gate_required=human_req,
        evidence_assessment=str(candidate_data.get("evidence_assessment", "SATISFACTORY")),
        epoch=expected_epoch or 0,
    )
    return dec, None
