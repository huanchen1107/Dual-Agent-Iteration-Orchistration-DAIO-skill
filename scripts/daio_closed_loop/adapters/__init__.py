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
    ProviderState,
    RoutingFailureType,
    ProviderRoutingAttempt,
    FailoverAuditRecord,
    HumanChannelType,
    HumanDecisionEnvelope,
    HumanChannelAdapter,
)
from .antigravity_cli_agent import AntigravityCLIAdapter, find_antigravity_cli_path
from .gemini_cli_agent import GeminiCLIAdapter, find_gemini_cli_path
from .codex_cli_agent import CodexCLIAdapter, find_codex_cli_path
from .opencode_cli_agent import OpenCodeCLIAdapter, find_opencode_cli_path
from .gemini_agent import GeminiEngineeringAgentAdapter
from .registry import AgentAdapterRegistry
from .discovery import CLIProviderDiscovery
from .router import ProviderRouter, RoutingEngineeringAgentAdapter, DEFAULT_ROUTING_POLICY

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
    "ProviderState",
    "RoutingFailureType",
    "ProviderRoutingAttempt",
    "FailoverAuditRecord",
    "HumanChannelType",
    "HumanDecisionEnvelope",
    "HumanChannelAdapter",
    "AgentAdapterRegistry",
    "CLIProviderDiscovery",
    "ProviderRouter",
    "RoutingEngineeringAgentAdapter",
    "DEFAULT_ROUTING_POLICY",
    "AntigravityCLIAdapter",
    "find_antigravity_cli_path",
    "GeminiCLIAdapter",
    "find_gemini_cli_path",
    "CodexCLIAdapter",
    "find_codex_cli_path",
    "OpenCodeCLIAdapter",
    "find_opencode_cli_path",
    "GeminiEngineeringAgentAdapter",
]





