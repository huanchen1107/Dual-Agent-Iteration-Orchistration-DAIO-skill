"""
Provider-Neutral Agent Adapter Registry for Generic DAIO (daio-agent/v1).
Resolves adapters dynamically by logical role and advertised capabilities.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .agent_contract import (
    AgentAdapter,
    AgentCapability,
    AgentHealth,
    AgentHealthStatus,
    AgentIdentity,
    AgentRole,
)

logger = logging.getLogger("DAIO_Agent_Registry")


class AgentAdapterRegistry:
    """
    Central provider-neutral registry for agent adapters.
    Matches incoming AgentRequests to compatible, healthy adapters without hardcoding vendor names.
    """

    def __init__(self) -> None:
        # role -> list of (priority, adapter)
        self._registry: Dict[AgentRole, List[Tuple[int, AgentAdapter]]] = {}
        self._instances: Dict[str, AgentAdapter] = {}

    def register(self, adapter: AgentAdapter, priority: int = 100) -> None:
        """
        Registers an adapter with an optional priority (lower number = higher priority).
        """
        identity = adapter.get_identity()
        role = identity.logical_role
        if not isinstance(role, AgentRole):
            role = AgentRole(str(role))

        if role not in self._registry:
            self._registry[role] = []

        # Remove existing instance with the same ID if re-registering
        self.unregister(identity.instance_id)

        self._registry[role].append((priority, adapter))
        self._registry[role].sort(key=lambda x: x[0])
        self._instances[identity.instance_id] = adapter
        logger.debug(f"Registered adapter: {identity.instance_id} for role {role.value} (priority={priority})")

    def unregister(self, instance_id: str) -> bool:
        """Unregisters an adapter by instance_id."""
        if instance_id not in self._instances:
            return False

        adapter = self._instances.pop(instance_id)
        role = adapter.get_identity().logical_role
        if not isinstance(role, AgentRole):
            role = AgentRole(str(role))

        if role in self._registry:
            self._registry[role] = [(p, a) for p, a in self._registry[role] if a.get_identity().instance_id != instance_id]
        return True

    def get_adapter(self, instance_id: str) -> Optional[AgentAdapter]:
        """Retrieves a specific adapter instance by ID."""
        return self._instances.get(instance_id)

    def list_adapters(self, role: Optional[AgentRole] = None) -> List[AgentAdapter]:
        """Lists all registered adapters, optionally filtered by role."""
        if role is not None:
            if not isinstance(role, AgentRole):
                role = AgentRole(str(role))
            return [a for _, a in self._registry.get(role, [])]
        
        result: List[AgentAdapter] = []
        for entries in self._registry.values():
            result.extend([a for _, a in entries])
        return result

    def resolve(
        self,
        role: AgentRole,
        required_capabilities: Optional[Set[AgentCapability]] = None,
        allow_degraded: bool = True,
    ) -> Optional[AgentAdapter]:
        """
        Resolves the highest-priority, healthy adapter matching the logical role and required capabilities.
        """
        if not isinstance(role, AgentRole):
            role = AgentRole(str(role))

        candidates = self._registry.get(role, [])
        if not candidates:
            logger.warning(f"No adapters registered for role: {role.value}")
            return None

        req_caps = required_capabilities or set()

        for priority, adapter in candidates:
            advertised_caps = adapter.get_capabilities()
            if not req_caps.issubset(advertised_caps):
                logger.debug(
                    f"Adapter {adapter.get_identity().instance_id} lacks required capabilities: "
                    f"needed={req_caps - advertised_caps}"
                )
                continue

            health = adapter.check_health()
            if health.status == AgentHealthStatus.READY:
                return adapter
            if allow_degraded and health.status == AgentHealthStatus.DEGRADED:
                logger.info(f"Using degraded adapter: {adapter.get_identity().instance_id}")
                return adapter

            logger.warning(
                f"Skipping unhealthy adapter {adapter.get_identity().instance_id}: "
                f"status={health.status.value}"
            )

        logger.warning(f"No healthy, compatible adapter found for role: {role.value} with caps: {req_caps}")
        return None
