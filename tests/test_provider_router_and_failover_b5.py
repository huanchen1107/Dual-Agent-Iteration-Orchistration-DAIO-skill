"""
Phase B5 Acceptance Tests: Provider Capability Registry, Router & Runtime Failover (daio-agent/v1).
Verifies:
1. Provider Capability Registry state machine (NOT_INSTALLED, DISCOVERED, AVAILABLE, AUTH_REQUIRED, DEGRADED, UNAVAILABLE).
2. Separation of Discovery from Selection (DISCOVERED != AVAILABLE).
3. Deterministic provider selection & failover across Antigravity, Gemini, Codex, OpenCode.
4. Failover semantics (allowed ONLY for provider/runtime availability failures; FORBIDDEN for workflow outcomes).
5. Closed-loop scope and test integrity preservation (NO fallback on scope violation or test failure).
6. Human Gate invariant preservation (no provider may bypass Human Gate).
7. Complete audit trail generation (FailoverAuditRecord).
8. Future provider readiness (Claude Code as discoverable / NOT_INSTALLED).
9. DAIO Core modification invariant (0 core modifications).
"""

import asyncio
import inspect
import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.daio_closed_loop.adapters.agent_contract import (
    AgentCapability,
    AgentRole,
    AgentTaskProposal,
    AgentTaskRequest,
    AuthMode,
    AuthStatus,
    AvailabilityStatus,
    FailoverAuditRecord,
    InstallationStatus,
    ProposedFileEdit,
    ProviderDescriptor,
    ProviderState,
    ProviderTransport,
    RoutingFailureType,
)
from scripts.daio_closed_loop.adapters.registry import AgentAdapterRegistry
from scripts.daio_closed_loop.adapters.discovery import CLIProviderDiscovery
from scripts.daio_closed_loop.adapters.router import (
    DEFAULT_ROUTING_POLICY,
    ProviderRouter,
    RoutingEngineeringAgentAdapter,
)
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor
from scripts.daio_closed_loop.adapters.factory import create_engineering_agent_adapter
from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    transition_to_human_gate,
)
from scripts.daio_closed_loop.router import DAIORoleRouter


class FakeAgentAdapter:
    """Configurable mock adapter for routing acceptance tests."""

    def __init__(
        self,
        name: str,
        success: bool = True,
        proposed_edits: Optional[List[ProposedFileEdit]] = None,
        error_message: Optional[str] = None,
        model_name: str = "test-model",
        delay: float = 0.0,
        raise_timeout: bool = False,
        raise_exc: Optional[Exception] = None,
    ) -> None:
        self.name = name
        self.success = success
        self.proposed_edits = proposed_edits or []
        self.error_message = error_message
        self.model_name = model_name
        self.delay = delay
        self.raise_timeout = raise_timeout
        self.raise_exc = raise_exc
        self.invocations: List[AgentTaskRequest] = []

    async def propose_task_solution(self, request: AgentTaskRequest) -> AgentTaskProposal:
        self.invocations.append(request)
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.raise_timeout:
            raise asyncio.TimeoutError(f"{self.name} timed out")
        if self.raise_exc:
            raise self.raise_exc

        return AgentTaskProposal(
            work_id=request.work_id,
            success=self.success,
            backend_identity=self.name,
            model_name=self.model_name,
            proposed_edits=self.proposed_edits,
            error_message=self.error_message,
        )


# ==============================================================================
# 1. Registry & Discovery State Machine Tests
# ==============================================================================

def test_registry_provider_states_and_discovery_separation():
    """
    Verifies Section 1 & 2: Provider Capability Registry & DISCOVERED != AVAILABLE.
    """
    registry = AgentAdapterRegistry()

    # Register descriptors in various states
    desc_installed_auth = ProviderDescriptor(
        provider_id="test_available",
        display_name="Test Available",
        transport=ProviderTransport.CLI,
        auth_mode=AuthMode.LOGIN_SESSION,
        state=ProviderState.AVAILABLE,
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.AUTHENTICATED,
        availability=AvailabilityStatus.AVAILABLE,
        capabilities={AgentCapability.PROPOSE_EDITS},
        supported_roles={AgentRole.ENGINEERING_EXECUTION},
    )
    desc_discovered_unverified = ProviderDescriptor(
        provider_id="test_discovered",
        display_name="Test Discovered Only",
        transport=ProviderTransport.CLI,
        auth_mode=AuthMode.LOGIN_SESSION,
        state=ProviderState.DISCOVERED,  # Discovered binary, not yet validated
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.UNKNOWN,
        availability=AvailabilityStatus.DEGRADED,
    )
    desc_auth_required = ProviderDescriptor(
        provider_id="test_auth_req",
        display_name="Test Auth Required",
        transport=ProviderTransport.CLI,
        auth_mode=AuthMode.LOGIN_SESSION,
        state=ProviderState.AUTH_REQUIRED,
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.NOT_AUTHENTICATED,
        availability=AvailabilityStatus.DEGRADED,
    )
    desc_not_installed = ProviderDescriptor(
        provider_id="test_not_installed",
        display_name="Test Not Installed",
        transport=ProviderTransport.CLI,
        auth_mode=AuthMode.LOGIN_SESSION,
        state=ProviderState.NOT_INSTALLED,
        installation_status=InstallationStatus.NOT_INSTALLED,
        auth_status=AuthStatus.NOT_AUTHENTICATED,
        availability=AvailabilityStatus.UNAVAILABLE,
    )

    registry.register_descriptor(desc_installed_auth)
    registry.register_descriptor(desc_discovered_unverified)
    registry.register_descriptor(desc_auth_required)
    registry.register_descriptor(desc_not_installed)

    assert registry.is_provider_routable("test_available") is True
    assert registry.is_provider_routable("test_discovered") is False  # DISCOVERED != AVAILABLE
    assert registry.is_provider_routable("test_auth_req") is False
    assert registry.is_provider_routable("test_not_installed") is False

    meta = registry.get_provider_metadata("test_available")
    assert meta["state"] == "AVAILABLE"
    assert meta["transport"] == "CLI"
    assert meta["capabilities"] == ["PROPOSE_EDITS"]


def test_claude_code_future_readiness_in_registry():
    """
    Verifies Section 10: Claude Code CLI is discoverable as NOT_INSTALLED without installing it.
    """
    desc = CLIProviderDiscovery.inspect_provider("claude_code")
    assert desc.provider_id == "claude_code"
    assert desc.transport == ProviderTransport.CLI
    assert desc.auth_mode == AuthMode.LOGIN_SESSION
    # Claude code is not installed on this machine
    assert desc.installation_status == InstallationStatus.NOT_INSTALLED
    assert desc.state == ProviderState.NOT_INSTALLED
    assert desc.availability == AvailabilityStatus.UNAVAILABLE

    registry = AgentAdapterRegistry()
    registry.register_descriptor(desc)
    assert registry.is_provider_routable("claude_code") is False


# ==============================================================================
# 2. Router & Failover Acceptance Cases (A -> J)
# ==============================================================================

def test_acceptance_case_a_preferred_provider_healthy():
    """Case A: Preferred provider healthy -> Antigravity selected, no fallback."""
    async def _run():
        agy_adapter = FakeAgentAdapter(
            "ANTIGRAVITY_CLI",
            success=True,
            proposed_edits=[ProposedFileEdit(file_path="src/a.py", new_content="# agy\n")],
        )
        gemini_adapter = FakeAgentAdapter("GEMINI_CLI")

        router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})
        with patch.object(router, "evaluate_provider", return_value=(ProviderState.AVAILABLE, True, None)):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={"antigravity_cli": agy_adapter, "gemini_cli": gemini_adapter},
            )

            req = AgentTaskRequest(work_id="req-a", change_id="CHG_A", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "ANTIGRAVITY_CLI"
            assert len(agy_adapter.invocations) == 1
            assert len(gemini_adapter.invocations) == 0

            audit = routing_adapter.get_audit_records()[0]
            assert audit.selected_provider == "antigravity_cli"
            assert audit.fallback_occurred is False
            assert len(audit.provider_attempts) == 1
            assert audit.provider_attempts[0].status == "SUCCESS"

    asyncio.run(_run())


def test_acceptance_case_b_preferred_unavailable_failover_to_second():
    """Case B: Preferred provider unavailable -> Antigravity unavailable, Gemini selected."""
    async def _run():
        agy_adapter = FakeAgentAdapter("ANTIGRAVITY_CLI")
        gemini_adapter = FakeAgentAdapter(
            "GEMINI_CLI",
            success=True,
            proposed_edits=[ProposedFileEdit(file_path="src/b.py", new_content="# gemini\n")],
        )

        router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})

        def mock_eval(pid):
            if pid == "antigravity_cli":
                return (ProviderState.NOT_INSTALLED, False, RoutingFailureType.BINARY_UNAVAILABLE)
            return (ProviderState.AVAILABLE, True, None)

        with patch.object(router, "evaluate_provider", side_effect=mock_eval):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={"antigravity_cli": agy_adapter, "gemini_cli": gemini_adapter},
            )

            req = AgentTaskRequest(work_id="req-b", change_id="CHG_B", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "GEMINI_CLI"
            assert len(agy_adapter.invocations) == 0
            assert len(gemini_adapter.invocations) == 1

            audit = routing_adapter.get_audit_records()[0]
            assert audit.selected_provider == "gemini_cli"
            assert audit.fallback_occurred is True
            assert len(audit.provider_attempts) == 2
            assert audit.provider_attempts[0].status == "SKIPPED"
            assert audit.provider_attempts[0].failure_reason == "BINARY_UNAVAILABLE"
            assert audit.provider_attempts[1].status == "SUCCESS"

    asyncio.run(_run())


def test_acceptance_case_c_first_two_fail_codex_succeeds():
    """Case C: First two fail (runtime crash) -> Antigravity -> Gemini fail -> Codex succeeds."""
    async def _run():
        agy_adapter = FakeAgentAdapter("ANTIGRAVITY_CLI", success=False, error_message="Process returned non-zero exit code 1")
        gemini_adapter = FakeAgentAdapter("GEMINI_CLI", success=False, error_message="Subprocess timed out (TIMEOUT)")
        codex_adapter = FakeAgentAdapter(
            "CODEX_CLI",
            success=True,
            proposed_edits=[ProposedFileEdit(file_path="src/c.py", new_content="# codex\n")],
        )

        router = ProviderRouter(
            policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli", "codex_cli"], "failover": True}}
        )
        with patch.object(router, "evaluate_provider", return_value=(ProviderState.AVAILABLE, True, None)):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={
                    "antigravity_cli": agy_adapter,
                    "gemini_cli": gemini_adapter,
                    "codex_cli": codex_adapter,
                },
            )

            req = AgentTaskRequest(work_id="req-c", change_id="CHG_C", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "CODEX_CLI"
            assert len(agy_adapter.invocations) == 1
            assert len(gemini_adapter.invocations) == 1
            assert len(codex_adapter.invocations) == 1

            audit = routing_adapter.get_audit_records()[0]
            assert audit.selected_provider == "codex_cli"
            assert audit.fallback_occurred is True
            assert len(audit.provider_attempts) == 3
            assert audit.provider_attempts[0].status == "FAILURE"
            assert audit.provider_attempts[1].status == "FAILURE"
            assert audit.provider_attempts[2].status == "SUCCESS"

    asyncio.run(_run())


def test_acceptance_case_d_multiple_failures_opencode_succeeds():
    """Case D: Multiple provider failure -> Router eventually selects OpenCode."""
    async def _run():
        agy = FakeAgentAdapter("ANTIGRAVITY_CLI", success=False, error_message="CLI unavailable")
        gem = FakeAgentAdapter("GEMINI_CLI", success=False, error_message="Rate limit 429")
        cdx = FakeAgentAdapter("CODEX_CLI", success=False, error_message="Process failed to execute")
        opc = FakeAgentAdapter(
            "OPENCODE_CLI",
            success=True,
            proposed_edits=[ProposedFileEdit(file_path="src/d.py", new_content="# opencode\n")],
        )

        router = ProviderRouter(
            policy={
                "engineering": {
                    "preferred": ["antigravity_cli", "gemini_cli", "codex_cli", "opencode_cli"],
                    "failover": True,
                }
            }
        )
        with patch.object(router, "evaluate_provider", return_value=(ProviderState.AVAILABLE, True, None)):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={
                    "antigravity_cli": agy,
                    "gemini_cli": gem,
                    "codex_cli": cdx,
                    "opencode_cli": opc,
                },
            )

            req = AgentTaskRequest(work_id="req-d", change_id="CHG_D", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "OPENCODE_CLI"
            audit = routing_adapter.get_audit_records()[0]
            assert audit.selected_provider == "opencode_cli"
            assert len(audit.provider_attempts) == 4

    asyncio.run(_run())


def test_acceptance_case_e_auth_unavailable_skipped_safely():
    """Case E: Provider marked AUTH_REQUIRED is skipped safely without running subprocess."""
    async def _run():
        agy = FakeAgentAdapter("ANTIGRAVITY_CLI")
        gem = FakeAgentAdapter("GEMINI_CLI", success=True, proposed_edits=[])

        router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})

        def mock_eval(pid):
            if pid == "antigravity_cli":
                return (ProviderState.AUTH_REQUIRED, False, RoutingFailureType.AUTH_UNAVAILABLE)
            return (ProviderState.AVAILABLE, True, None)

        with patch.object(router, "evaluate_provider", side_effect=mock_eval):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={"antigravity_cli": agy, "gemini_cli": gem},
            )

            req = AgentTaskRequest(work_id="req-e", change_id="CHG_E", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is True
            assert len(agy.invocations) == 0  # Not even called
            assert len(gem.invocations) == 1

            audit = routing_adapter.get_audit_records()[0]
            assert audit.provider_attempts[0].status == "SKIPPED"
            assert audit.provider_attempts[0].failure_reason == "AUTH_UNAVAILABLE"

    asyncio.run(_run())


def test_acceptance_case_f_provider_timeout_failover():
    """Case F: Provider asyncio timeout triggers failover and records TIMEOUT reason in audit."""
    async def _run():
        agy = FakeAgentAdapter("ANTIGRAVITY_CLI", raise_timeout=True)
        gem = FakeAgentAdapter("GEMINI_CLI", success=True)

        router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})
        with patch.object(router, "evaluate_provider", return_value=(ProviderState.AVAILABLE, True, None)):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={"antigravity_cli": agy, "gemini_cli": gem},
            )

            req = AgentTaskRequest(work_id="req-f", change_id="CHG_F", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is True
            assert proposal.backend_identity == "GEMINI_CLI"

            audit = routing_adapter.get_audit_records()[0]
            assert audit.provider_attempts[0].failure_reason == "TIMEOUT"
            assert audit.provider_attempts[0].status == "FAILURE"

    asyncio.run(_run())


def test_acceptance_case_g_scope_violation_no_provider_fallback():
    """
    Case G: Proposal violates allowed_scope -> NO provider fallback.
    The proposal is returned as-is to DAIO Two-Tier policy engine, which rejects the mutation.
    """
    async def _run():
        temp_dir = tempfile.mkdtemp()
        try:
            # Proposed edits touch out-of-scope file
            agy_adapter = FakeAgentAdapter(
                "ANTIGRAVITY_CLI",
                success=True,
                proposed_edits=[ProposedFileEdit(file_path="forbidden/secrets.py", new_content="# leak\n")],
            )
            gemini_adapter = FakeAgentAdapter("GEMINI_CLI")

            router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})
            with patch.object(router, "evaluate_provider", return_value=(ProviderState.AVAILABLE, True, None)):
                routing_adapter = RoutingEngineeringAgentAdapter(
                    router=router,
                    adapters_map={"antigravity_cli": agy_adapter, "gemini_cli": gemini_adapter},
                )

                work = DAIOWorkItem(
                    work_id="work-g",
                    change_id="CHG_G",
                    project_root=temp_dir,
                    current_stage="S3",
                    current_gate=DAIOGate.IMPLEMENTATION_GATE.value,
                    assigned_role=DAIORole.ENGINEERING_EXECUTION.value,
                    status=DAIOStatus.IN_PROGRESS.value,
                    requested_action="Refactor",
                    allowed_scope=["src/*"],
                )

                # Execute closed loop via DAIO SubprocessWorkspaceExecutor
                executor = SubprocessWorkspaceExecutor(project_root=temp_dir, agent_adapter=routing_adapter)
                res = await executor.execute_task_async(work)

                assert res.success is False
                assert res.scope_violation is True
                assert len(agy_adapter.invocations) == 1
                assert len(gemini_adapter.invocations) == 0  # No fallback!
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    asyncio.run(_run())


def test_acceptance_case_h_test_failure_no_provider_fallback():
    """
    Case H: Proposal causes test failure -> NO provider fallback to find a provider that passes.
    Test execution is a DAIO validation phase, not an adapter availability failure.
    """
    async def _run():
        temp_dir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(temp_dir, "src"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, "tests"), exist_ok=True)
            with open(os.path.join(temp_dir, "tests", "test_sample.py"), "w") as f:
                f.write("from src.code import val\ndef test_val(): assert val == 10\n")

            # Provider outputs buggy code (val = 5 instead of 10)
            agy_adapter = FakeAgentAdapter(
                "ANTIGRAVITY_CLI",
                success=True,
                proposed_edits=[ProposedFileEdit(file_path="src/code.py", new_content="val = 5\n")],
            )
            gemini_adapter = FakeAgentAdapter("GEMINI_CLI")

            router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})
            with patch.object(router, "evaluate_provider", return_value=(ProviderState.AVAILABLE, True, None)):
                routing_adapter = RoutingEngineeringAgentAdapter(
                    router=router,
                    adapters_map={"antigravity_cli": agy_adapter, "gemini_cli": gemini_adapter},
                )

                work = DAIOWorkItem(
                    work_id="work-h",
                    change_id="CHG_H",
                    project_root=temp_dir,
                    current_stage="S3",
                    current_gate=DAIOGate.IMPLEMENTATION_GATE.value,
                    assigned_role=DAIORole.ENGINEERING_EXECUTION.value,
                    status=DAIOStatus.IN_PROGRESS.value,
                    requested_action="Fix val",
                    allowed_scope=["src/*"],
                )

                executor = SubprocessWorkspaceExecutor(project_root=temp_dir, agent_adapter=routing_adapter)
                res = await executor.execute_task_async(work, test_command="pytest tests/test_sample.py")

                assert res.success is False
                assert res.test_passed is False
                assert len(agy_adapter.invocations) == 1
                assert len(gemini_adapter.invocations) == 0  # No fallback!
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    asyncio.run(_run())


def test_acceptance_case_i_human_gate_cannot_be_routed_around():
    """
    Case I: HUMAN_GATE invariant preservation.
    Verifies that no provider or router can bypass or self-resolve a Human Gate.
    """
    work = DAIOWorkItem(
        work_id="work-human-gate",
        change_id="CHG_HUMAN",
        project_root="/tmp/sandbox",
        current_stage="S3",
        current_gate=DAIOGate.HUMAN_GATE.value,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW.value,
        status=DAIOStatus.IN_PROGRESS.value,
    )

    # Transition to Human Gate
    work_hg = transition_to_human_gate(work, reason="High risk modification requires owner signature")
    assert work_hg.current_gate == DAIOGate.HUMAN_GATE.value
    assert work_hg.status == DAIOStatus.HUMAN_GATE_REQUIRED.value
    assert work_hg.assigned_role == DAIORole.HUMAN_PROJECT_OWNER.value

    # An unauthorized agent provider attempting to review must be rejected
    with pytest.raises(PermissionError):
        DAIORoleRouter.process_architect_review(
            work_hg,
            ArchitectDecision(
                decision="APPROVE",
                current_phase="S3",
                next_phase="S4",
                action="APPROVE",
            ),
            acting_role=DAIORole.ENGINEERING_EXECUTION,  # Unauthorized
        )


def test_acceptance_case_j_all_providers_unavailable_fails_closed():
    """
    Case J: All providers unavailable -> Router fails closed with explicit error proposal and complete audit.
    """
    async def _run():
        router = ProviderRouter(policy={"engineering": {"preferred": ["antigravity_cli", "gemini_cli"], "failover": True}})

        def mock_eval(pid):
            return (ProviderState.NOT_INSTALLED, False, RoutingFailureType.BINARY_UNAVAILABLE)

        with patch.object(router, "evaluate_provider", side_effect=mock_eval):
            routing_adapter = RoutingEngineeringAgentAdapter(
                router=router,
                adapters_map={"antigravity_cli": FakeAgentAdapter("AGY"), "gemini_cli": FakeAgentAdapter("GEM")},
            )

            req = AgentTaskRequest(work_id="req-j", change_id="CHG_J", requested_action="test", project_root="/tmp")
            proposal = await routing_adapter.propose_task_solution(req)

            assert proposal.success is False
            assert proposal.backend_identity == "DAIO_FEDERATION_ROUTER"
            assert "All configured providers failed or were unavailable" in proposal.error_message

            audit = routing_adapter.get_audit_records()[0]
            assert audit.selected_provider is None
            assert len(audit.provider_attempts) == 2
            assert all(a.status == "SKIPPED" for a in audit.provider_attempts)

    asyncio.run(_run())


# ==============================================================================
# 3. DAIO Core Modification Invariant Audit (DAIO-PORTABILITY-INVARIANT-001)
# ==============================================================================

def test_zero_daio_core_modification_invariant_b5():
    """
    Verifies DAIO-PORTABILITY-INVARIANT-001:
    Zero vendor or provider-specific branches or tokens exist in core modules.
    """
    from scripts.daio_closed_loop import (
        models,
        orchestrator,
        router,
        runner,
        store,
        supervisor,
        watchdog,
        worker,
    )

    core_modules = [
        models,
        orchestrator,
        router,
        runner,
        store,
        supervisor,
        watchdog,
        worker,
    ]

    forbidden_tokens = [
        "antigravity_cli",
        "gemini_cli",
        "codex_cli",
        "opencode_cli",
        "claude_code",
        "--dangerously-skip-permissions",
        "--approval-mode yolo",
        "opencode run",
    ]

    for mod in core_modules:
        src = inspect.getsource(mod)
        for token in forbidden_tokens:
            assert token not in src, (
                f"Invariant violation: Provider token '{token}' found in core module '{mod.__name__}'!"
            )
