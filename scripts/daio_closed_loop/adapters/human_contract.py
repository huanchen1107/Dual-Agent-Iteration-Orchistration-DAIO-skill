"""
Canonical Human Command, Interaction & Channel Federation Contract for Generic DAIO (Phase B6).
Implements:
1. HumanCommand schema & natural language normalization boundary.
2. HumanInteractionRequest & HumanInteractionResponse schemas.
3. Risk Classification & Authentication Level models.
4. Human Channel Adapter contract, Registry & Router.
5. Cross-Channel Continuity & Conversation Reference Mapping.
6. Exactly-Once Human Decision Invariant.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime
from enum import Enum
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

logger = logging.getLogger("DAIO_Human_Channel")


class HumanChannelType(str, Enum):
    """Supported human communication channels in the Human Channel Federation."""
    CHATGPT = "CHATGPT"
    COCKPIT = "COCKPIT"
    TELEGRAM = "TELEGRAM"
    LINE = "LINE"
    MESSENGER = "MESSENGER"
    DISCORD = "DISCORD"
    CUSTOM = "CUSTOM"


class HumanCommandIntent(str, Enum):
    """Normalized human command intents."""
    START_WORK = "START_WORK"
    CONTINUE_WORK = "CONTINUE_WORK"
    PAUSE_WORK = "PAUSE_WORK"
    RESUME_WORK = "RESUME_WORK"
    STOP_WORK = "STOP_WORK"
    GET_STATUS = "GET_STATUS"
    GET_EVIDENCE = "GET_EVIDENCE"
    GET_BLOCKERS = "GET_BLOCKERS"
    SELECT_PROVIDER = "SELECT_PROVIDER"
    RETRY_PROVIDER = "RETRY_PROVIDER"
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"
    ACKNOWLEDGE = "ACKNOWLEDGE"


class HumanRiskClass(str, Enum):
    """Normalized risk classification for human commands and interactions."""
    READ_ONLY = "READ_ONLY"
    ROUTINE_ENGINEERING = "ROUTINE_ENGINEERING"
    WORKFLOW_CONTROL = "WORKFLOW_CONTROL"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
    FINANCIAL_OR_PRODUCTION = "FINANCIAL_OR_PRODUCTION"


class HumanAuthLevel(str, Enum):
    """Normalized authentication level of a human interaction response."""
    UNVERIFIED = "UNVERIFIED"
    CHANNEL_AUTHENTICATED = "CHANNEL_AUTHENTICATED"
    ACCOUNT_AUTHENTICATED = "ACCOUNT_AUTHENTICATED"
    STRONG_AUTHENTICATED = "STRONG_AUTHENTICATED"


class HumanInteractionType(str, Enum):
    """Types of human interaction requests sent from DAIO to human."""
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    CHOICE = "CHOICE"
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    INFORMATION = "INFORMATION"


class DeliveryStatus(str, Enum):
    """Delivery state of a human notification / interaction."""
    DELIVERY_PENDING = "DELIVERY_PENDING"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"


class DecisionStatus(str, Enum):
    """Lifecycle state of a human decision."""
    DECISION_PENDING = "DECISION_PENDING"
    DECISION_RECEIVED = "DECISION_RECEIVED"
    DECISION_VERIFIED = "DECISION_VERIFIED"
    DECISION_APPLIED = "DECISION_APPLIED"
    DECISION_REJECTED = "DECISION_REJECTED"


class HumanChannelState(str, Enum):
    """Operational state of a channel in the registry."""
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DISCOVERED = "DISCOVERED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class HumanCommand:
    """
    Canonical provider-neutral Human Command schema (Human -> DAIO).
    Converts user commands across ChatGPT, Telegram, LINE, etc. into normalized intents.
    """
    command_id: str
    actor_id: str = "project_owner"
    project_id: str = "default"
    source_channel: HumanChannelType = HumanChannelType.CHATGPT
    conversation_reference: Optional[str] = None
    intent: HumanCommandIntent = HumanCommandIntent.GET_STATUS
    target_work_id: Optional[str] = None
    target_change_id: Optional[str] = None
    requested_action: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    preferred_provider: Optional[str] = None
    stop_condition: Optional[str] = None
    risk_class: HumanRiskClass = HumanRiskClass.ROUTINE_ENGINEERING
    requires_strong_auth: bool = False
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "actor_id": self.actor_id,
            "project_id": self.project_id,
            "source_channel": self.source_channel.value if isinstance(self.source_channel, HumanChannelType) else str(self.source_channel),
            "conversation_reference": self.conversation_reference,
            "intent": self.intent.value if isinstance(self.intent, HumanCommandIntent) else str(self.intent),
            "target_work_id": self.target_work_id,
            "target_change_id": self.target_change_id,
            "requested_action": self.requested_action,
            "constraints": self.constraints,
            "preferred_provider": self.preferred_provider,
            "stop_condition": self.stop_condition,
            "risk_class": self.risk_class.value if isinstance(self.risk_class, HumanRiskClass) else str(self.risk_class),
            "requires_strong_auth": self.requires_strong_auth,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }


@dataclass
class HumanInteractionRequest:
    """
    Canonical Human Interaction Request (DAIO -> Human).
    Transports notification, choice, or Human Gate to human channels.
    """
    interaction_id: str
    work_id: str
    project_id: str = "default"
    change_id: Optional[str] = None
    interaction_type: HumanInteractionType = HumanInteractionType.APPROVAL
    requested_action: str = ""
    reason: str = ""
    summary: str = ""
    allowed_actions: List[str] = field(default_factory=lambda: ["APPROVE", "REVISE", "REJECT"])
    risk_class: HumanRiskClass = HumanRiskClass.SECURITY_SENSITIVE
    requires_strong_auth: bool = True
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "work_id": self.work_id,
            "project_id": self.project_id,
            "change_id": self.change_id,
            "interaction_type": self.interaction_type.value if isinstance(self.interaction_type, HumanInteractionType) else str(self.interaction_type),
            "requested_action": self.requested_action,
            "reason": self.reason,
            "summary": self.summary,
            "allowed_actions": self.allowed_actions,
            "risk_class": self.risk_class.value if isinstance(self.risk_class, HumanRiskClass) else str(self.risk_class),
            "requires_strong_auth": self.requires_strong_auth,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "evidence_refs": self.evidence_refs,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }


@dataclass
class HumanInteractionResponse:
    """
    Canonical Human Interaction Response (Human -> DAIO).
    Captures human feedback, choices, or approvals with provenance and auth level.
    """
    interaction_id: str
    decision_id: str
    actor_id: str
    channel_id: HumanChannelType
    action: str  # "APPROVE", "REVISE", "REJECT", "ACKNOWLEDGE", "STOP", "RESUME"
    selected_option: Optional[str] = None
    comment: Optional[str] = None
    authentication_level: HumanAuthLevel = HumanAuthLevel.CHANNEL_AUTHENTICATED
    authenticated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    received_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    channel_message_id: Optional[str] = None
    raw_channel_reference: Optional[str] = None
    idempotency_key: Optional[str] = None
    auth_proof: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "decision_id": self.decision_id,
            "actor_id": self.actor_id,
            "channel_id": self.channel_id.value if isinstance(self.channel_id, HumanChannelType) else str(self.channel_id),
            "action": self.action,
            "selected_option": self.selected_option,
            "comment": self.comment,
            "authentication_level": self.authentication_level.value if isinstance(self.authentication_level, HumanAuthLevel) else str(self.authentication_level),
            "authenticated_at": self.authenticated_at,
            "received_at": self.received_at,
            "channel_message_id": self.channel_message_id,
            "raw_channel_reference": self.raw_channel_reference,
            "idempotency_key": self.idempotency_key,
            "auth_proof": self.auth_proof,
            "provenance": self.provenance,
        }


@dataclass
class HumanChannelDescriptor:
    """Canonical descriptor for a human interaction channel."""
    channel_type: HumanChannelType
    display_name: str
    state: HumanChannelState = HumanChannelState.NOT_CONFIGURED
    supports_commands: bool = True
    supports_buttons: bool = True
    supports_deep_links: bool = True
    supports_push: bool = True
    supports_bidirectional_messages: bool = True
    supports_identity_binding: bool = True
    supports_strong_auth: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_type": self.channel_type.value if isinstance(self.channel_type, HumanChannelType) else str(self.channel_type),
            "display_name": self.display_name,
            "state": self.state.value if isinstance(self.state, HumanChannelState) else str(self.state),
            "supports_commands": self.supports_commands,
            "supports_buttons": self.supports_buttons,
            "supports_deep_links": self.supports_deep_links,
            "supports_push": self.supports_push,
            "supports_bidirectional_messages": self.supports_bidirectional_messages,
            "supports_identity_binding": self.supports_identity_binding,
            "supports_strong_auth": self.supports_strong_auth,
            "metadata": self.metadata,
        }


class HumanCommandNormalizer:
    """
    Natural Language Command Normalizer Boundary.
    Normalizes unconstrained human language into canonical HumanCommand representations.
    Executes outside DAIO Core.
    """

    @classmethod
    def normalize_text_command(
        cls,
        text: str,
        source_channel: HumanChannelType = HumanChannelType.CHATGPT,
        actor_id: str = "project_owner",
        project_id: str = "awin-fintech",
        conversation_reference: Optional[str] = None,
    ) -> HumanCommand:
        """Parses natural language commands deterministically into canonical HumanCommand."""
        raw = text.strip()
        raw_lower = raw.lower()
        command_id = f"cmd-{uuid.uuid4().hex[:8]}"

        # 1. Extract Target Change ID if present
        target_change_id = None
        change_match = re.search(r"change\s*([0-9a-zA-Z_\-]+)", raw_lower, re.IGNORECASE)
        if change_match:
            change_num = change_match.group(1).upper()
            if not change_num.startswith("CHANGE_"):
                target_change_id = f"CHANGE_{change_num}"
            else:
                target_change_id = change_num

        # 2. Extract Stop Condition if present
        stop_condition = None
        if "until next human gate" in raw_lower or "until the next human gate" in raw_lower:
            stop_condition = "NEXT_HUMAN_GATE"
        elif "after architecture review" in raw_lower or "after arch review" in raw_lower:
            stop_condition = "ARCHITECTURE_REVIEW"

        # 3. Extract Preferred Provider if specified
        preferred_provider = None
        if "use codex" in raw_lower or "with codex" in raw_lower:
            preferred_provider = "codex_cli"
        elif "use gemini" in raw_lower or "with gemini" in raw_lower:
            preferred_provider = "gemini_cli"
        elif "use antigravity" in raw_lower or "use agy" in raw_lower:
            preferred_provider = "antigravity_cli"
        elif "use opencode" in raw_lower or "with opencode" in raw_lower:
            preferred_provider = "opencode_cli"

        # 4. Intent & Risk Classification
        intent = HumanCommandIntent.GET_STATUS
        risk_class = HumanRiskClass.READ_ONLY
        requires_strong_auth = False

        if "continue" in raw_lower or "resume" in raw_lower:
            intent = HumanCommandIntent.CONTINUE_WORK
            risk_class = HumanRiskClass.ROUTINE_ENGINEERING
            requires_strong_auth = False
        elif "pause" in raw_lower:
            intent = HumanCommandIntent.PAUSE_WORK
            risk_class = HumanRiskClass.WORKFLOW_CONTROL
            requires_strong_auth = False
        elif "stop" in raw_lower or "abort" in raw_lower:
            intent = HumanCommandIntent.STOP_WORK
            risk_class = HumanRiskClass.WORKFLOW_CONTROL
            requires_strong_auth = False
        elif "status" in raw_lower or "show me" in raw_lower:
            intent = HumanCommandIntent.GET_STATUS
            risk_class = HumanRiskClass.READ_ONLY
            requires_strong_auth = False
        elif "blocker" in raw_lower or "why" in raw_lower:
            intent = HumanCommandIntent.GET_BLOCKERS
            risk_class = HumanRiskClass.READ_ONLY
            requires_strong_auth = False
        elif "evidence" in raw_lower or "test result" in raw_lower:
            intent = HumanCommandIntent.GET_EVIDENCE
            risk_class = HumanRiskClass.READ_ONLY
            requires_strong_auth = False
        elif "start" in raw_lower:
            intent = HumanCommandIntent.START_WORK
            risk_class = HumanRiskClass.ROUTINE_ENGINEERING
            requires_strong_auth = False
        elif "approve" in raw_lower:
            intent = HumanCommandIntent.APPROVE
            if "production" in raw_lower or "security" in raw_lower or "credential" in raw_lower:
                risk_class = HumanRiskClass.FINANCIAL_OR_PRODUCTION
                requires_strong_auth = True
            else:
                risk_class = HumanRiskClass.WORKFLOW_CONTROL
                requires_strong_auth = False
        elif "reject" in raw_lower:
            intent = HumanCommandIntent.REJECT
            risk_class = HumanRiskClass.WORKFLOW_CONTROL
            requires_strong_auth = False
        elif "revise" in raw_lower:
            intent = HumanCommandIntent.REVISE
            risk_class = HumanRiskClass.ROUTINE_ENGINEERING
            requires_strong_auth = False

        # Provider preference command override
        if "best available" in raw_lower or "provider" in raw_lower:
            if not intent or intent == HumanCommandIntent.GET_STATUS:
                intent = HumanCommandIntent.SELECT_PROVIDER

        return HumanCommand(
            command_id=command_id,
            actor_id=actor_id,
            project_id=project_id,
            source_channel=source_channel,
            conversation_reference=conversation_reference,
            intent=intent,
            target_work_id=None,
            target_change_id=target_change_id,
            requested_action=raw,
            constraints=[],
            preferred_provider=preferred_provider,
            stop_condition=stop_condition,
            risk_class=risk_class,
            requires_strong_auth=requires_strong_auth,
            provenance={"raw_text": raw, "normalized_by": "HumanCommandNormalizer"},
        )


class ConversationReferenceMapping:
    """
    Cross-Channel Context & Continuity Mapping Layer.
    Enforces invariant: CHANNEL HAS NO WORKFLOW OWNERSHIP. DAIO IS CANONICAL OWNER.
    Maps channel conversation IDs to canonical (project_id, work_id, change_id).
    """

    def __init__(self) -> None:
        # key: (channel, conversation_id) -> (project_id, work_id, change_id)
        self._mappings: Dict[Tuple[str, str], Dict[str, Optional[str]]] = {}
        # change_id -> work_id index
        self._change_to_work: Dict[str, str] = {}

    def register_context(
        self,
        channel: HumanChannelType,
        conversation_id: str,
        project_id: str,
        work_id: Optional[str] = None,
        change_id: Optional[str] = None,
    ) -> None:
        """Associates a channel conversation session with a canonical DAIO workflow context."""
        key = (channel.value if isinstance(channel, HumanChannelType) else str(channel), conversation_id)
        self._mappings[key] = {
            "project_id": project_id,
            "work_id": work_id,
            "change_id": change_id,
        }
        if change_id and work_id:
            self._change_to_work[change_id.upper()] = work_id

    def resolve_context(
        self,
        channel: HumanChannelType,
        conversation_id: str,
        fallback_change_id: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Resolves canonical context across channels."""
        key = (channel.value if isinstance(channel, HumanChannelType) else str(channel), conversation_id)
        ctx = self._mappings.get(key)
        if ctx:
            return dict(ctx)

        # Fallback by change_id if available
        if fallback_change_id:
            chg_norm = fallback_change_id.upper()
            work_id = self._change_to_work.get(chg_norm)
            return {
                "project_id": "awin-fintech",
                "work_id": work_id,
                "change_id": chg_norm,
            }

        return {
            "project_id": "default",
            "work_id": None,
            "change_id": None,
        }


class HumanChannelAdapter(ABC):
    """
    Abstract contract for human notification, interaction, and command transport channels.
    Notification and interaction transport only; canonical DAIO Human Gate remains the sole authorization authority.
    """

    @abstractmethod
    def get_channel_type(self) -> HumanChannelType:
        raise NotImplementedError

    @abstractmethod
    def get_descriptor(self) -> HumanChannelDescriptor:
        raise NotImplementedError

    @abstractmethod
    async def send_interaction(self, request: HumanInteractionRequest) -> DeliveryStatus:
        """Sends an interaction notification or Human Gate prompt to the human channel."""
        raise NotImplementedError

    @abstractmethod
    async def receive_response(self, response: HumanInteractionResponse) -> Tuple[bool, Optional[str]]:
        """Receives a response from human channel."""
        raise NotImplementedError

    @abstractmethod
    async def send_command_acknowledgement(self, command_id: str, status: str, message: str) -> bool:
        """Sends immediate receipt / acknowledgment for a human command."""
        raise NotImplementedError


class CockpitChannelAdapter(HumanChannelAdapter):
    """
    First Concrete HumanChannelAdapter: Wraps canonical Cockpit Passkey / WebAuthn / Face ID architecture.
    Provides STRONG_AUTHENTICATED Human Gate decisions.
    """

    def __init__(self, base_url: str = "https://cockpit.awin.internal") -> None:
        self.base_url = base_url
        self.sent_interactions: List[HumanInteractionRequest] = []
        self.acknowledged_commands: List[Tuple[str, str, str]] = []

    def get_channel_type(self) -> HumanChannelType:
        return HumanChannelType.COCKPIT

    def get_descriptor(self) -> HumanChannelDescriptor:
        return HumanChannelDescriptor(
            channel_type=HumanChannelType.COCKPIT,
            display_name="iPhone Cockpit (WebAuthn / Passkey / Face ID)",
            state=HumanChannelState.AVAILABLE,
            supports_commands=True,
            supports_buttons=True,
            supports_deep_links=True,
            supports_push=True,
            supports_bidirectional_messages=True,
            supports_identity_binding=True,
            supports_strong_auth=True,
            metadata={"auth_mode": "WEBAUTHN_PASSKEY"},
        )

    def generate_secure_deep_link(self, interaction_id: str, work_id: str, action_ticket_id: str) -> str:
        """Generates a secure deep link into iPhone Cockpit for strong authentication."""
        return f"{self.base_url}/gate?interaction_id={interaction_id}&work_id={work_id}&ticket={action_ticket_id}"

    async def send_interaction(self, request: HumanInteractionRequest) -> DeliveryStatus:
        self.sent_interactions.append(request)
        return DeliveryStatus.DELIVERED

    async def receive_response(self, response: HumanInteractionResponse) -> Tuple[bool, Optional[str]]:
        # Cockpit responses carry strong authentication
        response.authentication_level = HumanAuthLevel.STRONG_AUTHENTICATED
        return True, None

    async def send_command_acknowledgement(self, command_id: str, status: str, message: str) -> bool:
        self.acknowledged_commands.append((command_id, status, message))
        return True


class MockHumanChannelAdapter(HumanChannelAdapter):
    """Configurable mock adapter for testing messaging channels (ChatGPT, Telegram, LINE, Messenger)."""

    def __init__(
        self,
        channel_type: HumanChannelType,
        display_name: str,
        delivery_status: DeliveryStatus = DeliveryStatus.DELIVERED,
        default_auth_level: HumanAuthLevel = HumanAuthLevel.CHANNEL_AUTHENTICATED,
        state: HumanChannelState = HumanChannelState.NOT_CONFIGURED,
    ) -> None:
        self.channel_type = channel_type
        self.display_name = display_name
        self.delivery_status = delivery_status
        self.default_auth_level = default_auth_level
        self.state = state
        self.sent_interactions: List[HumanInteractionRequest] = []
        self.received_responses: List[HumanInteractionResponse] = []
        self.acknowledged_commands: List[Tuple[str, str, str]] = []

    def get_channel_type(self) -> HumanChannelType:
        return self.channel_type

    def get_descriptor(self) -> HumanChannelDescriptor:
        return HumanChannelDescriptor(
            channel_type=self.channel_type,
            display_name=self.display_name,
            state=self.state,
            supports_commands=True,
            supports_buttons=True,
            supports_deep_links=True,
            supports_push=True,
            supports_bidirectional_messages=True,
            supports_identity_binding=True,
            supports_strong_auth=False,
        )

    async def send_interaction(self, request: HumanInteractionRequest) -> DeliveryStatus:
        if self.state in (HumanChannelState.UNAVAILABLE, HumanChannelState.NOT_CONFIGURED):
            return DeliveryStatus.DELIVERY_FAILED
        self.sent_interactions.append(request)
        return self.delivery_status

    async def receive_response(self, response: HumanInteractionResponse) -> Tuple[bool, Optional[str]]:
        response.authentication_level = self.default_auth_level
        self.received_responses.append(response)
        return True, None

    async def send_command_acknowledgement(self, command_id: str, status: str, message: str) -> bool:
        self.acknowledged_commands.append((command_id, status, message))
        return True


class HumanChannelRegistry:
    """Registry managing human interaction channel descriptors and adapter instances."""

    def __init__(self) -> None:
        self._descriptors: Dict[HumanChannelType, HumanChannelDescriptor] = {}
        self._adapters: Dict[HumanChannelType, HumanChannelAdapter] = {}

        # Default standard registrations
        self.register_channel_descriptor(
            HumanChannelDescriptor(
                channel_type=HumanChannelType.CHATGPT,
                display_name="ChatGPT Project / Web LLM",
                state=HumanChannelState.AVAILABLE,
                supports_commands=True,
                supports_strong_auth=False,
            )
        )
        self.register_channel_descriptor(
            HumanChannelDescriptor(
                channel_type=HumanChannelType.COCKPIT,
                display_name="iPhone Cockpit (WebAuthn)",
                state=HumanChannelState.AVAILABLE,
                supports_commands=True,
                supports_strong_auth=True,
            )
        )
        self.register_channel_descriptor(
            HumanChannelDescriptor(
                channel_type=HumanChannelType.TELEGRAM,
                display_name="Telegram Bot Channel",
                state=HumanChannelState.NOT_CONFIGURED,
            )
        )
        self.register_channel_descriptor(
            HumanChannelDescriptor(
                channel_type=HumanChannelType.LINE,
                display_name="LINE Messaging Channel",
                state=HumanChannelState.NOT_CONFIGURED,
            )
        )
        self.register_channel_descriptor(
            HumanChannelDescriptor(
                channel_type=HumanChannelType.MESSENGER,
                display_name="Messenger Channel",
                state=HumanChannelState.NOT_CONFIGURED,
            )
        )

    def register_channel_descriptor(self, desc: HumanChannelDescriptor) -> None:
        self._descriptors[desc.channel_type] = desc

    def register_adapter(self, adapter: HumanChannelAdapter) -> None:
        ctype = adapter.get_channel_type()
        self._adapters[ctype] = adapter
        self._descriptors[ctype] = adapter.get_descriptor()

    def get_descriptor(self, channel_type: HumanChannelType) -> Optional[HumanChannelDescriptor]:
        return self._descriptors.get(channel_type)

    def get_adapter(self, channel_type: HumanChannelType) -> Optional[HumanChannelAdapter]:
        return self._adapters.get(channel_type)

    def list_descriptors(self) -> List[HumanChannelDescriptor]:
        return list(self._descriptors.values())


DEFAULT_HUMAN_CHANNEL_POLICY: Dict[str, Any] = {
    "command": {
        "preferred": [
            HumanChannelType.CHATGPT,
            HumanChannelType.TELEGRAM,
            HumanChannelType.LINE,
            HumanChannelType.MESSENGER,
        ]
    },
    "notification": {
        "preferred": [
            HumanChannelType.TELEGRAM,
            HumanChannelType.LINE,
            HumanChannelType.MESSENGER,
            HumanChannelType.COCKPIT,
        ]
    },
    "authorization": {
        "preferred": [
            HumanChannelType.COCKPIT,
        ]
    },
}


class HumanChannelRouter:
    """
    Multi-Channel Router, Delivery Failover & Authorization Gateway.
    Enforces:
    1. Multi-channel notification delivery with failover.
    2. Strong Authentication Upgrade Flow (Messaging -> Cockpit Passkey).
    3. Exactly-Once Human Decision Invariant (idempotency ledger).
    """

    def __init__(
        self,
        registry: Optional[HumanChannelRegistry] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.registry = registry or HumanChannelRegistry()
        self.policy = policy or dict(DEFAULT_HUMAN_CHANNEL_POLICY)
        # Decision Ledger: decision_id / idempotency_key -> applied status
        self._decision_ledger: Dict[str, Dict[str, Any]] = {}
        self._interaction_store: Dict[str, HumanInteractionRequest] = {}

    def register_interaction(self, request: HumanInteractionRequest) -> None:
        """Stores interaction request for validation against incoming responses."""
        self._interaction_store[request.interaction_id] = request

    async def broadcast_or_route_notification(
        self,
        request: HumanInteractionRequest,
    ) -> Tuple[bool, List[Tuple[HumanChannelType, DeliveryStatus]]]:
        """
        Dispatches an interaction notification across preferred notification channels with delivery failover.
        """
        self.register_interaction(request)
        preferred = self.policy.get("notification", {}).get(
            "preferred",
            [HumanChannelType.TELEGRAM, HumanChannelType.LINE, HumanChannelType.COCKPIT]
        )

        delivery_results: List[Tuple[HumanChannelType, DeliveryStatus]] = []
        any_delivered = False

        for ch in preferred:
            adapter = self.registry.get_adapter(ch)
            if not adapter:
                delivery_results.append((ch, DeliveryStatus.DELIVERY_FAILED))
                continue

            try:
                status = await adapter.send_interaction(request)
                delivery_results.append((ch, status))
                if status == DeliveryStatus.DELIVERED:
                    any_delivered = True
                    break  # Delivered successfully on preferred channel
            except Exception as ex:
                logger.error(f"Failed to send interaction to {ch}: {ex}")
                delivery_results.append((ch, DeliveryStatus.DELIVERY_FAILED))

        return any_delivered, delivery_results

    async def process_human_response(
        self,
        response: HumanInteractionResponse,
    ) -> Tuple[DecisionStatus, Optional[str], Optional[str]]:
        """
        Evaluates incoming HumanInteractionResponse against authentication policy and exactly-once ledger.
        Returns (decision_status, error_or_reason, deep_link_if_upgrade_needed).
        """
        interaction = self._interaction_store.get(response.interaction_id)
        requires_strong = interaction.requires_strong_auth if interaction else True
        risk_class = interaction.risk_class if interaction else HumanRiskClass.SECURITY_SENSITIVE

        # 1. Exactly-Once Idempotency Check
        idempotency_key = response.idempotency_key or response.decision_id or f"{response.interaction_id}-{response.action}"
        if idempotency_key in self._decision_ledger:
            logger.info(f"Duplicate human decision received for key {idempotency_key}. Ignored exactly-once.")
            return DecisionStatus.DECISION_APPLIED, "DUPLICATE_IDEMPOTENT_DECISION", None

        # 2. Risk & Authentication Level Verification
        is_high_risk = requires_strong or risk_class in (
            HumanRiskClass.SECURITY_SENSITIVE,
            HumanRiskClass.FINANCIAL_OR_PRODUCTION,
        )

        if is_high_risk and response.action in ("APPROVE", "STOP", "RESUME"):
            if response.authentication_level != HumanAuthLevel.STRONG_AUTHENTICATED:
                # Strong Auth Required: Upgrade via Cockpit Deep Link
                logger.warning(
                    f"Response from {response.channel_id.value} for high-risk action '{response.action}' "
                    f"lacks STRONG_AUTHENTICATED status (has {response.authentication_level.value}). "
                    f"Upgrading to Cockpit Passkey."
                )
                action_ticket_id = f"ticket-{uuid.uuid4().hex[:8]}"
                cockpit_adapter = self.registry.get_adapter(HumanChannelType.COCKPIT)
                deep_link = ""
                if isinstance(cockpit_adapter, CockpitChannelAdapter):
                    deep_link = cockpit_adapter.generate_secure_deep_link(
                        response.interaction_id,
                        interaction.work_id if interaction else "unknown",
                        action_ticket_id,
                    )
                else:
                    deep_link = f"https://cockpit.awin.internal/gate?interaction_id={response.interaction_id}&ticket={action_ticket_id}"

                return DecisionStatus.DECISION_REJECTED, "STRONG_AUTH_REQUIRED", deep_link

        # 3. Decision Verified & Applied to Ledger Exactly-Once
        self._decision_ledger[idempotency_key] = {
            "interaction_id": response.interaction_id,
            "decision_id": response.decision_id,
            "action": response.action,
            "channel_id": response.channel_id.value if isinstance(response.channel_id, HumanChannelType) else str(response.channel_id),
            "actor_id": response.actor_id,
            "auth_level": response.authentication_level.value if isinstance(response.authentication_level, HumanAuthLevel) else str(response.authentication_level),
            "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        logger.info(f"Human decision {response.action} applied canonically via {response.channel_id.value} (key={idempotency_key}).")
        return DecisionStatus.DECISION_APPLIED, None, None
