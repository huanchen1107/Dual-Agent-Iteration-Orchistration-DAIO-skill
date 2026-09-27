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
]



