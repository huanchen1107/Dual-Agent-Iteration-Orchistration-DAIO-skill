"""
Backend-Neutral Agent Capability Contract for Generic DAIO (daio-agent/v1).
Defines capabilities, requests, normalized responses, health, and failure semantics
without depending on specific AI vendors or model APIs.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class AgentRole(str, Enum):
    """Canonical logical roles within the DAIO multi-agent federation."""
    LEAD_ARCHITECT = "LEAD_ARCHITECT"
    ENGINEERING_EXECUTION = "ENGINEERING_EXECUTION"
    RESEARCH_AGENT = "RESEARCH_AGENT"
    REVIEW_AGENT = "REVIEW_AGENT"
    TEST_AGENT = "TEST_AGENT"
    OPTIONAL_SPECIALIST = "OPTIONAL_SPECIALIST"


class AgentCapability(str, Enum):
    """Standardized functional capability tags advertised by adapters."""
    READ_REPOSITORY = "READ_REPOSITORY"
    WRITE_REPOSITORY = "WRITE_REPOSITORY"
    PROPOSE_EDITS = "PROPOSE_EDITS"
    RUN_COMMANDS = "RUN_COMMANDS"
    RUN_TESTS = "RUN_TESTS"
    GIT_COMMIT = "GIT_COMMIT"
    GIT_PUSH = "GIT_PUSH"
    WEB_RESEARCH = "WEB_RESEARCH"
    ARCHITECT_REVIEW = "ARCHITECT_REVIEW"
    STRUCTURED_DECISION = "STRUCTURED_DECISION"
    ARTIFACT_GENERATION = "ARTIFACT_GENERATION"
    LONG_RUNNING_EXECUTION = "LONG_RUNNING_EXECUTION"


@dataclass
class AgentIdentity:
    """Immutable identity metadata for an adapter instance."""
    logical_role: AgentRole
    provider: str
    adapter_type: str
    model: str = "configured-model"
    instance_id: str = "primary"
    capability_version: str = "1"
    contract_version: str = "daio-agent/v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logical_role": self.logical_role.value if isinstance(self.logical_role, AgentRole) else str(self.logical_role),
            "provider": self.provider,
            "adapter_type": self.adapter_type,
            "model": self.model,
            "instance_id": self.instance_id,
            "capability_version": self.capability_version,
            "contract_version": self.contract_version,
            "metadata": self.metadata,
        }


class AgentFailureType(str, Enum):
    """Standardized failure categories across all agent providers."""
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AUTH_FAILURE = "AUTH_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    TOOL_FAILURE = "TOOL_FAILURE"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    SECURITY_BOUNDARY_VIOLATION = "SECURITY_BOUNDARY_VIOLATION"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RecoveryClassification(str, Enum):
    """Recovery strategy classification for an agent failure."""
    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"


@dataclass
class AgentFailure:
    """Normalized error envelope returned when execution fails."""
    failure_type: AgentFailureType
    recovery_classification: RecoveryClassification
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_type": self.failure_type.value if isinstance(self.failure_type, AgentFailureType) else str(self.failure_type),
            "recovery_classification": self.recovery_classification.value if isinstance(self.recovery_classification, RecoveryClassification) else str(self.recovery_classification),
            "message": self.message,
            "details": self.details,
        }


@dataclass
class AgentDecision:
    """Provider-neutral structured architectural decision."""
    decision: str  # "APPROVE", "REVISE", "REJECT", "STOP", "HUMAN_GATE", "NOT_EVALUATED"
    gate: str = "IMPLEMENTATION_GATE"
    rationale: str = ""
    required_actions: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "gate": self.gate,
            "rationale": self.rationale,
            "required_actions": self.required_actions,
            "evidence_refs": self.evidence_refs,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class AgentEvidence:
    """A referenced piece of execution or verification evidence."""
    evidence_type: str
    uri: str
    description: str = ""
    sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "uri": self.uri,
            "description": self.description,
            "sha256": self.sha256,
        }


@dataclass
class ProposedFileEdit:
    """A proposed modification to a file within the workspace."""
    file_path: str
    new_content: str
    description: str = ""
    is_deletion: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "new_content": self.new_content,
            "description": self.description,
            "is_deletion": self.is_deletion,
        }


@dataclass
class AgentRequest:
    """Canonical versioned request envelope dispatched to any agent adapter."""
    contract_version: str = "daio-agent/v1"
    request_id: str = ""
    work_id: str = ""
    change_id: str = ""
    role: AgentRole = AgentRole.ENGINEERING_EXECUTION
    requested_capabilities: List[AgentCapability] = field(default_factory=list)
    instruction: str = ""
    project_root: str = ""
    allowed_scope: List[str] = field(default_factory=list)
    frozen_paths: List[str] = field(default_factory=list)
    base_sha: str = ""
    head_sha: str = ""
    context_files: Dict[str, str] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    timeout_seconds: int = 300
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "request_id": self.request_id,
            "work_id": self.work_id,
            "change_id": self.change_id,
            "role": self.role.value if isinstance(self.role, AgentRole) else str(self.role),
            "requested_capabilities": [c.value if isinstance(c, AgentCapability) else str(c) for c in self.requested_capabilities],
            "instruction": self.instruction,
            "project_root": self.project_root,
            "allowed_scope": self.allowed_scope,
            "frozen_paths": self.frozen_paths,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "evidence_refs": self.evidence_refs,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }


@dataclass
class AgentResponse:
    """Canonical normalized response envelope returned by any agent adapter."""
    contract_version: str = "daio-agent/v1"
    request_id: str = ""
    agent_identity: Optional[AgentIdentity] = None
    status: str = "SUCCESS"  # "SUCCESS", "FAILED", "DEGRADED"
    summary: str = ""
    decision: Optional[AgentDecision] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[AgentEvidence] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    proposed_edits: List[ProposedFileEdit] = field(default_factory=list)
    test_results: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    failure: Optional[AgentFailure] = None
    started_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    completed_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "request_id": self.request_id,
            "agent_identity": self.agent_identity.to_dict() if self.agent_identity else None,
            "status": self.status,
            "summary": self.summary,
            "decision": self.decision.to_dict() if self.decision else None,
            "artifacts": self.artifacts,
            "evidence": [e.to_dict() for e in self.evidence],
            "commands": self.commands,
            "changed_files": self.changed_files,
            "proposed_edits": [p.to_dict() for p in self.proposed_edits],
            "test_results": self.test_results,
            "warnings": self.warnings,
            "failure": self.failure.to_dict() if self.failure else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class AgentHealthStatus(str, Enum):
    """Health / readiness status of an adapter."""
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"


@dataclass
class AgentHealth:
    """Normalized readiness health assessment of an agent adapter."""
    status: AgentHealthStatus
    provider_reachable: bool = True
    credentials_available: bool = True
    required_cli_available: bool = True
    contract_supported: bool = True
    capabilities_available: List[AgentCapability] = field(default_factory=list)
    last_success_at: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class AgentAdapter(ABC):
    """Abstract base contract for any provider-neutral agent adapter."""

    @abstractmethod
    def get_identity(self) -> AgentIdentity:
        """Returns the advertised identity of the adapter."""
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> Set[AgentCapability]:
        """Returns the set of capabilities supported by this adapter."""
        raise NotImplementedError

    @abstractmethod
    def check_health(self) -> AgentHealth:
        """Evaluates readiness without exposing sensitive credentials."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Executes the requested agent task and returns a normalized response envelope."""
        raise NotImplementedError


# ==============================================================================
# Legacy Compatibility Layer (Phase S5.1 & Pre-RPC-3 backward compatibility)
# ==============================================================================

@dataclass
class AgentTaskRequest:
    """Backward-compatible wrapper for legacy EngineeringAgentAdapter callers."""
    work_id: str
    change_id: str
    requested_action: str
    project_root: str
    allowed_scope: List[str] = field(default_factory=list)
    frozen_paths: List[str] = field(default_factory=list)
    context_files: Dict[str, str] = field(default_factory=dict)
    backend_config: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300


@dataclass
class AgentTaskProposal:
    """Backward-compatible wrapper for legacy EngineeringAgentAdapter responses."""
    work_id: str
    success: bool
    proposed_edits: List[ProposedFileEdit] = field(default_factory=list)
    backend_identity: str = "GENERIC_AGENT"
    model_name: str = "UNKNOWN"
    reasoning_summary: str = ""
    error_message: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    completed_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    raw_response: str = ""


class EngineeringAgentAdapter(ABC):
    """Abstract contract for an unattended coding agent backend (legacy interface)."""

    @abstractmethod
    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        raise NotImplementedError


class MockEngineeringAgentAdapter(EngineeringAgentAdapter):
    """Mock agent adapter for deterministic contract testing."""

    def __init__(self, canned_proposals: Optional[List[AgentTaskProposal]] = None) -> None:
        self.canned_proposals = canned_proposals or []
        self.invocations: List[AgentTaskRequest] = []

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        self.invocations.append(request)
        if self.canned_proposals:
            return self.canned_proposals.pop(0)
        return AgentTaskProposal(
            work_id=request.work_id,
            success=True,
            backend_identity="MOCK_AGENT",
            model_name="mock-model-v1",
            proposed_edits=[
                ProposedFileEdit(file_path="src/service.py", new_content="# auto-generated by mock\n")
            ]
        )


class AuthMode(str, Enum):
    """Canonical authentication mechanism used by an agent or CLI tool."""
    LOGIN_SESSION = "LOGIN_SESSION"
    API_KEY = "API_KEY"
    OAUTH = "OAUTH"
    LOCAL_CREDENTIAL = "LOCAL_CREDENTIAL"
    PROVIDER_DEPENDENT = "PROVIDER_DEPENDENT"
    UNAVAILABLE = "UNAVAILABLE"


class AuthStatus(str, Enum):
    """Current authentication health status detected non-destructively."""
    AUTHENTICATED = "AUTHENTICATED"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    UNKNOWN = "UNKNOWN"


class InstallationStatus(str, Enum):
    """System binary / environment installation status."""
    INSTALLED = "INSTALLED"
    NOT_INSTALLED = "NOT_INSTALLED"
    UNKNOWN = "UNKNOWN"


class AvailabilityStatus(str, Enum):
    """Operational availability status of the provider."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"


class ProviderTransport(str, Enum):
    """Transport protocol or medium used to interact with the provider."""
    CLI = "CLI"
    API = "API"
    CDP = "CDP"
    SUBPROCESS = "SUBPROCESS"
    IPC = "IPC"


@dataclass
class ProviderDescriptor:
    """
    Canonical provider descriptor representing capability, authentication,
    and invocation features of an agent provider.
    """
    provider_id: str
    display_name: str
    transport: ProviderTransport
    auth_mode: AuthMode
    installation_status: InstallationStatus = InstallationStatus.UNKNOWN
    auth_status: AuthStatus = AuthStatus.UNKNOWN
    availability: AvailabilityStatus = AvailabilityStatus.UNAVAILABLE
    capabilities: Set[AgentCapability] = field(default_factory=set)
    supported_roles: Set[AgentRole] = field(default_factory=set)
    executable: Optional[str] = None
    version: Optional[str] = None
    supports_non_interactive: bool = True
    supports_structured_output: bool = True
    supports_sandbox: bool = True
    supports_unattended: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "transport": self.transport.value if isinstance(self.transport, ProviderTransport) else str(self.transport),
            "auth_mode": self.auth_mode.value if isinstance(self.auth_mode, AuthMode) else str(self.auth_mode),
            "installation_status": self.installation_status.value if isinstance(self.installation_status, InstallationStatus) else str(self.installation_status),
            "auth_status": self.auth_status.value if isinstance(self.auth_status, AuthStatus) else str(self.auth_status),
            "availability": self.availability.value if isinstance(self.availability, AvailabilityStatus) else str(self.availability),
            "capabilities": [c.value if isinstance(c, AgentCapability) else str(c) for c in self.capabilities],
            "supported_roles": [r.value if isinstance(r, AgentRole) else str(r) for r in self.supported_roles],
            "executable": self.executable,
            "version": self.version,
            "supports_non_interactive": self.supports_non_interactive,
            "supports_structured_output": self.supports_structured_output,
            "supports_sandbox": self.supports_sandbox,
            "supports_unattended": self.supports_unattended,
            "metadata": self.metadata,
        }


class HumanChannelType(str, Enum):
    """Supported human communication channels for notification and decision transport."""
    WEB_COCKPIT = "WEB_COCKPIT"
    LINE = "LINE"
    TELEGRAM = "TELEGRAM"
    MESSENGER = "MESSENGER"
    DISCORD = "DISCORD"
    CUSTOM = "CUSTOM"


@dataclass
class HumanDecisionEnvelope:
    """
    Canonical Human Gate Decision Envelope.
    Transported across human interaction channels while preserving strict DAIO Human Gate authority.
    """
    envelope_id: str
    work_id: str
    action_ticket_id: str
    channel: HumanChannelType
    operator_identity: str
    decision: str  # APPROVE, REVISE, REJECT, STOP, RESUME
    instruction: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    auth_proof: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "work_id": self.work_id,
            "action_ticket_id": self.action_ticket_id,
            "channel": self.channel.value if isinstance(self.channel, HumanChannelType) else str(self.channel),
            "operator_identity": self.operator_identity,
            "decision": self.decision,
            "instruction": self.instruction,
            "timestamp": self.timestamp,
            "auth_proof": self.auth_proof,
            "metadata": self.metadata,
        }


class HumanChannelAdapter(ABC):
    """
    Abstract extension interface for human notification and decision transport channels.
    Notification and interaction transport only; canonical DAIO Human Gate remains the sole authorization authority.
    """

    @abstractmethod
    def get_channel_type(self) -> HumanChannelType:
        raise NotImplementedError

    @abstractmethod
    async def send_gate_notification(self, work_item: Any, gate_reason: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def receive_human_decision(self, envelope: HumanDecisionEnvelope) -> bool:
        raise NotImplementedError


