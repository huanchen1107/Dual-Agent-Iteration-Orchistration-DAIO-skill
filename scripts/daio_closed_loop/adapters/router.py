"""
Provider-Neutral Agent Federation Router & Failover Engine (daio-agent/v1 / Phase B5).
Orchestrates provider selection and deterministic runtime failover across CLI adapters
without introducing vendor-specific logic into DAIO Core.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import uuid

from .agent_contract import (
    AgentAdapter,
    AgentCapability,
    AgentHealth,
    AgentHealthStatus,
    AgentIdentity,
    AgentRole,
    AgentTaskProposal,
    AgentTaskRequest,
    EngineeringAgentAdapter,
    FailoverAuditRecord,
    ProviderDescriptor,
    ProviderRoutingAttempt,
    ProviderState,
    RoutingFailureType,
)
from .registry import AgentAdapterRegistry
from .discovery import CLIProviderDiscovery

logger = logging.getLogger("DAIO_Provider_Router")


DEFAULT_ROUTING_POLICY: Dict[str, Any] = {
    "engineering": {
        "preferred": [
            "antigravity_cli",
            "gemini_cli",
            "codex_cli",
            "opencode_cli",
        ],
        "failover": True,
    }
}


class ProviderRouter:
    """
    Evaluates provider availability and determines ordered dispatch candidates.
    Supports dynamic policy injection and runtime failover management.
    """

    def __init__(
        self,
        policy: Optional[Dict[str, Any]] = None,
        registry: Optional[AgentAdapterRegistry] = None,
    ) -> None:
        self._policy = policy or dict(DEFAULT_ROUTING_POLICY)
        self._registry = registry or AgentAdapterRegistry()

    @property
    def registry(self) -> AgentAdapterRegistry:
        return self._registry

    def get_preferred_order(self, role: str = "engineering") -> List[str]:
        """Returns the configured preferred provider list for a logical role."""
        role_cfg = self._policy.get(role, {})
        return list(role_cfg.get("preferred", DEFAULT_ROUTING_POLICY["engineering"]["preferred"]))

    def is_failover_enabled(self, role: str = "engineering") -> bool:
        """Returns whether failover to subsequent providers is enabled."""
        role_cfg = self._policy.get(role, {})
        return bool(role_cfg.get("failover", True))

    def update_policy(self, new_policy: Dict[str, Any]) -> None:
        """Updates the router policy dynamically without modifying Core."""
        self._policy.update(new_policy)

    def evaluate_provider(self, provider_id: str) -> Tuple[ProviderState, bool, Optional[RoutingFailureType]]:
        """
        Non-destructively inspects provider state.
        Returns (state, is_routable, failure_type_if_unusable).
        Enforces DISCOVERED != AVAILABLE.
        """
        canonical_pid = provider_id.lower().replace("-", "_")
        # Normalize provider IDs
        if canonical_pid in ("agy", "antigravity"):
            canonical_pid = "antigravity"
        elif canonical_pid in ("gemini", "gemini_cli"):
            canonical_pid = "gemini_cli"
        elif canonical_pid in ("codex", "codex_cli"):
            canonical_pid = "codex_cli"
        elif canonical_pid in ("opencode", "opencode_cli"):
            canonical_pid = "opencode_cli"
        elif canonical_pid in ("claude", "claude_code", "claude_code_cli"):
            canonical_pid = "claude_code"

        desc = self._registry.get_descriptor(canonical_pid)
        if not desc:
            desc = CLIProviderDiscovery.inspect_provider(canonical_pid)
            self._registry.register_descriptor(desc)

        state = desc.state
        if state == ProviderState.NOT_INSTALLED:
            return (state, False, RoutingFailureType.BINARY_UNAVAILABLE)
        if state == ProviderState.AUTH_REQUIRED:
            return (state, False, RoutingFailureType.AUTH_UNAVAILABLE)
        if state == ProviderState.UNAVAILABLE:
            return (state, False, RoutingFailureType.PROVIDER_UNAVAILABLE)
        if state in (ProviderState.AVAILABLE, ProviderState.DEGRADED):
            return (state, True, None)

        return (state, False, RoutingFailureType.PROVIDER_UNAVAILABLE)


class RoutingEngineeringAgentAdapter(EngineeringAgentAdapter, AgentAdapter):
    """
    Provider-neutral engineering adapter implementing the Agent Federation Router.
    Dispatches tasks across preferred providers with deterministic failover and audit logging.
    """

    def __init__(
        self,
        router: Optional[ProviderRouter] = None,
        adapter_factory_override: Optional[Callable[[str], EngineeringAgentAdapter]] = None,
        adapters_map: Optional[Dict[str, EngineeringAgentAdapter]] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.router = router or ProviderRouter(policy=policy)
        self._factory_override = adapter_factory_override
        self._adapters_map = adapters_map or {}
        self._audit_records: List[FailoverAuditRecord] = []

    def get_identity(self) -> AgentIdentity:
        return AgentIdentity(
            logical_role=AgentRole.ENGINEERING_EXECUTION,
            provider="DAIO_FEDERATION_ROUTER",
            adapter_type="RoutingEngineeringAgentAdapter",
            instance_id="federation-router-primary",
            metadata={
                "preferred_order": self.router.get_preferred_order(),
                "failover_enabled": self.router.is_failover_enabled(),
            }
        )

    def get_capabilities(self) -> Set[AgentCapability]:
        return {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.PROPOSE_EDITS,
            AgentCapability.RUN_COMMANDS,
            AgentCapability.RUN_TESTS,
            AgentCapability.ARTIFACT_GENERATION,
            AgentCapability.STRUCTURED_DECISION,
        }

    def check_health(self) -> AgentHealth:
        preferred = self.router.get_preferred_order()
        for pid in preferred:
            state, routable, _ = self.router.evaluate_provider(pid)
            if routable:
                return AgentHealth(
                    status=AgentHealthStatus.READY,
                    message=f"Primary available provider: {pid} (state={state.value})",
                    details={"active_provider": pid, "state": state.value},
                )
        return AgentHealth(
            status=AgentHealthStatus.UNAVAILABLE,
            message="No configured providers are currently AVAILABLE or routable.",
            details={"preferred": preferred},
        )

    async def execute(self, request: Any) -> Any:
        if isinstance(request, AgentTaskRequest):
            return await self.propose_task_solution(request)
        raise ValueError(f"Unsupported request type: {type(request)}")

    def _resolve_adapter_for_provider(self, provider_id: str) -> EngineeringAgentAdapter:
        """Instantiates or fetches the adapter for the given provider ID."""
        pid_norm = provider_id.lower().replace("-", "_")
        if pid_norm in self._adapters_map:
            return self._adapters_map[pid_norm]
        if provider_id in self._adapters_map:
            return self._adapters_map[provider_id]

        if self._factory_override:
            return self._factory_override(provider_id)

        from .factory import create_engineering_agent_adapter
        cfg_map = {
            "antigravity_cli": "ANTIGRAVITY_CLI",
            "antigravity": "ANTIGRAVITY_CLI",
            "agy": "ANTIGRAVITY_CLI",
            "gemini_cli": "GEMINI_CLI",
            "gemini": "GEMINI_CLI",
            "codex_cli": "CODEX_CLI",
            "codex": "CODEX_CLI",
            "opencode_cli": "OPENCODE_CLI",
            "opencode": "OPENCODE_CLI",
        }
        prov_key = cfg_map.get(pid_norm, provider_id.upper())
        return create_engineering_agent_adapter({"provider": prov_key})

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        """
        Executes proposal generation via the configured provider sequence with failover semantics.
        Failover is strictly limited to provider runtime/availability failures.
        """
        routing_id = f"route-{uuid.uuid4().hex[:8]}"
        preferred_order = self.router.get_preferred_order()
        failover_enabled = self.router.is_failover_enabled()

        attempts: List[ProviderRoutingAttempt] = []
        selected_provider: Optional[str] = None
        fallback_occurred = False
        fallback_reason: Optional[str] = None
        final_proposal: Optional[AgentTaskProposal] = None

        logger.info(
            f"Routing work item {request.work_id} (change={request.change_id}) "
            f"across preferred providers: {preferred_order}"
        )

        for idx, pid in enumerate(preferred_order):
            state, routable, unusable_reason = self.router.evaluate_provider(pid)
            if not routable:
                reason_str = unusable_reason.value if unusable_reason else "UNAVAILABLE"
                logger.info(f"Provider {pid} skipped: state={state.value}, reason={reason_str}")
                attempts.append(
                    ProviderRoutingAttempt(
                        provider_id=pid,
                        status="SKIPPED",
                        failure_reason=reason_str,
                        details={"state": state.value},
                    )
                )
                if not fallback_occurred and idx > 0:
                    fallback_occurred = True
                    fallback_reason = f"Previous provider(s) unusable ({reason_str})"
                continue

            # Provider is routable, attempt execution
            adapter = self._resolve_adapter_for_provider(pid)
            t0 = time.time()
            try:
                proposal = await adapter.propose_task_solution(request)
                latency = (time.time() - t0) * 1000.0

                # Check if the proposal failed due to provider runtime/crash/timeout
                is_runtime_failure = False
                fail_reason_type = RoutingFailureType.PROVIDER_UNAVAILABLE

                if not proposal.success:
                    err = (proposal.error_message or "").upper()
                    if "TIMEOUT" in err or "TIMED OUT" in err:
                        is_runtime_failure = True
                        fail_reason_type = RoutingFailureType.TIMEOUT
                    elif "RATE LIMIT" in err or "429" in err:
                        is_runtime_failure = True
                        fail_reason_type = RoutingFailureType.RATE_LIMIT
                    elif "NON-ZERO EXIT" in err or "FAILED TO EXECUTE" in err or "RETURNED CODE" in err:
                        is_runtime_failure = True
                        fail_reason_type = RoutingFailureType.MALFORMED_PROVIDER_RESPONSE
                    elif "UNAVAILABLE" in err or "NOT FOUND" in err:
                        is_runtime_failure = True
                        fail_reason_type = RoutingFailureType.PROVIDER_UNAVAILABLE

                if is_runtime_failure and failover_enabled and (idx < len(preferred_order) - 1):
                    logger.warning(
                        f"Provider {pid} encountered runtime failure: {proposal.error_message}. "
                        f"Failing over to next provider."
                    )
                    attempts.append(
                        ProviderRoutingAttempt(
                            provider_id=pid,
                            status="FAILURE",
                            failure_reason=fail_reason_type.value,
                            latency_ms=latency,
                            model=proposal.model_name,
                            details={"error_message": proposal.error_message},
                        )
                    )
                    fallback_occurred = True
                    fallback_reason = f"Failover triggered by {pid} {fail_reason_type.value}: {proposal.error_message}"
                    continue

                # Successful attempt or non-failover proposal (e.g. valid proposal with edits or workflow outcome)
                status_str = "SUCCESS" if proposal.success else "FAILURE"
                attempts.append(
                    ProviderRoutingAttempt(
                        provider_id=pid,
                        status=status_str,
                        latency_ms=latency,
                        model=proposal.model_name,
                        details={"proposed_edits_count": len(proposal.proposed_edits)},
                    )
                )
                selected_provider = pid
                if idx > 0 and not fallback_occurred:
                    fallback_occurred = True
                    fallback_reason = f"Resolved via fallback to {pid}"

                final_proposal = proposal
                break

            except asyncio.TimeoutError:
                latency = (time.time() - t0) * 1000.0
                logger.warning(f"Provider {pid} timed out after {latency:.1f}ms")
                attempts.append(
                    ProviderRoutingAttempt(
                        provider_id=pid,
                        status="FAILURE",
                        failure_reason=RoutingFailureType.TIMEOUT.value,
                        latency_ms=latency,
                    )
                )
                if failover_enabled and (idx < len(preferred_order) - 1):
                    fallback_occurred = True
                    fallback_reason = f"Provider {pid} timed out"
                    continue
                break

            except Exception as ex:
                latency = (time.time() - t0) * 1000.0
                logger.error(f"Provider {pid} execution exception: {ex}")
                attempts.append(
                    ProviderRoutingAttempt(
                        provider_id=pid,
                        status="FAILURE",
                        failure_reason=RoutingFailureType.PROVIDER_UNAVAILABLE.value,
                        latency_ms=latency,
                        details={"exception": str(ex)},
                    )
                )
                if failover_enabled and (idx < len(preferred_order) - 1):
                    fallback_occurred = True
                    fallback_reason = f"Provider {pid} threw exception: {ex}"
                    continue
                break

        # Record audit trail
        audit_record = FailoverAuditRecord(
            routing_id=routing_id,
            work_id=request.work_id,
            requested_capabilities=[c.value for c in [AgentCapability.PROPOSE_EDITS, AgentCapability.READ_REPOSITORY]],
            preferred_order=preferred_order,
            provider_attempts=attempts,
            selected_provider=selected_provider,
            fallback_occurred=fallback_occurred,
            fallback_reason=fallback_reason,
            model=final_proposal.model_name if final_proposal else None,
        )
        self._audit_records.append(audit_record)

        if final_proposal is not None:
            # Attach audit trail to proposal raw_response/metadata for provenance
            audit_dict = audit_record.to_dict()
            if not final_proposal.raw_response:
                final_proposal.raw_response = json.dumps({"routing_audit": audit_dict})
            return final_proposal

        # All providers failed or were unavailable
        err_msg = (
            f"All configured providers failed or were unavailable. "
            f"Attempts: {[(a.provider_id, a.status, a.failure_reason) for a in attempts]}"
        )
        return AgentTaskProposal(
            work_id=request.work_id,
            success=False,
            backend_identity="DAIO_FEDERATION_ROUTER",
            model_name="NONE",
            reasoning_summary="No available provider could fulfill the task.",
            error_message=err_msg,
            raw_response=json.dumps({"routing_audit": audit_record.to_dict()}),
        )

    def get_audit_records(self) -> List[FailoverAuditRecord]:
        """Returns the full in-memory audit history of routing decisions."""
        return list(self._audit_records)
