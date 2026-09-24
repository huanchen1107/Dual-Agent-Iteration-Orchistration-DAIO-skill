"""
Generic DAIO Replaceable Adapters Layer.
"""

from .executor import EngineeringExecutorAdapter, SubprocessWorkspaceExecutor, ExecutionResult
from .bridge import ArchitectBridgeAdapter, ChromeCDPBridgeAdapter, MockArchitectBridgeAdapter, parse_decision_from_text, discover_tab_by_endpoint

__all__ = [
    "EngineeringExecutorAdapter",
    "SubprocessWorkspaceExecutor",
    "ExecutionResult",
    "ArchitectBridgeAdapter",
    "ChromeCDPBridgeAdapter",
    "MockArchitectBridgeAdapter",
    "parse_decision_from_text",
    "discover_tab_by_endpoint",
]
