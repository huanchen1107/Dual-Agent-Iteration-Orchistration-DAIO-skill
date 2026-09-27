"""
Generic DAIO Replaceable Adapters Layer.
"""

from .executor import EngineeringExecutorAdapter, SubprocessWorkspaceExecutor, ExecutionResult
from .bridge import (
    ArchitectBridgeAdapter,
    ChromeCDPBridgeAdapter,
    MockArchitectBridgeAdapter,
    GeminiArchitectBridgeAdapter,
    parse_decision_from_text,
    discover_tab_by_endpoint,
)
from .rpc_status_collector import DAIOStatusCollector
from .rpc_status_publisher import DAIOStatusPublisher
from .factory import create_engineering_agent_adapter, create_architect_bridge_adapter
from .agent_contract import (
    AgentRole,
    AgentCapability,
    AgentIdentity,
    AgentFailureType,
    RecoveryClassification,
    AgentFailure,
    AgentDecision,
    AgentEvidence,
    ProposedFileEdit,
    AgentRequest,
    AgentResponse,
    AgentHealthStatus,
    AgentHealth,
    AgentAdapter,
    EngineeringAgentAdapter,
    MockEngineeringAgentAdapter,
    AgentTaskRequest,
    AgentTaskProposal,
    AuthMode,
    AuthStatus,
    InstallationStatus,
    AvailabilityStatus,
    ProviderTransport,
    ProviderDescriptor,
    HumanChannelType,
    HumanDecisionEnvelope,
    HumanChannelAdapter,
)
from .registry import AgentAdapterRegistry
from .discovery import CLIProviderDiscovery

__all__ = [
    "EngineeringExecutorAdapter",
    "SubprocessWorkspaceExecutor",
    "ExecutionResult",
    "ArchitectBridgeAdapter",
    "ChromeCDPBridgeAdapter",
    "MockArchitectBridgeAdapter",
    "GeminiArchitectBridgeAdapter",
    "parse_decision_from_text",
    "discover_tab_by_endpoint",
    "DAIOStatusCollector",
    "DAIOStatusPublisher",
    "create_engineering_agent_adapter",
    "create_architect_bridge_adapter",
    "AgentRole",
    "AgentCapability",
    "AgentIdentity",
    "AgentFailureType",
    "RecoveryClassification",
    "AgentFailure",
    "AgentDecision",
    "AgentEvidence",
    "ProposedFileEdit",
    "AgentRequest",
    "AgentResponse",
    "AgentHealthStatus",
    "AgentHealth",
    "AgentAdapter",
    "EngineeringAgentAdapter",
    "MockEngineeringAgentAdapter",
    "AgentTaskRequest",
    "AgentTaskProposal",
    "AuthMode",
    "AuthStatus",
    "InstallationStatus",
    "AvailabilityStatus",
    "ProviderTransport",
    "ProviderDescriptor",
    "HumanChannelType",
    "HumanDecisionEnvelope",
    "HumanChannelAdapter",
    "AgentAdapterRegistry",
    "CLIProviderDiscovery",
]





