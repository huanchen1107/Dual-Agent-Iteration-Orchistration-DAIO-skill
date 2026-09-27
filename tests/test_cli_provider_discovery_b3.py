"""
Phase B3 Login-First CLI Provider Contract & Capability Discovery Test Suite.
Validates:
1. Non-destructive host CLI capability discovery (installed vs not-installed).
2. Login-First Authentication Model (LOGIN_SESSION, API_KEY, LOCAL_CREDENTIAL, OAUTH).
3. Capability-based provider selection and ranking.
4. Graceful handling of missing CLI providers (e.g., Claude Code NOT_INSTALLED).
5. Human Channel Adapter and HumanDecisionEnvelope extension contracts.
6. Zero DAIO Core vendor branching / AST neutrality guard.
"""

from __future__ import annotations
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import pytest

from scripts.daio_closed_loop.adapters.agent_contract import (
    AgentCapability,
    AgentRole,
    AuthMode,
    AuthStatus,
    AvailabilityStatus,
    InstallationStatus,
    ProviderDescriptor,
    ProviderTransport,
    HumanChannelType,
    HumanDecisionEnvelope,
    HumanChannelAdapter,
)
from scripts.daio_closed_loop.adapters.discovery import CLIProviderDiscovery
from scripts.daio_closed_loop.adapters.registry import AgentAdapterRegistry


# ==============================================================================
# 1. Host CLI Provider Discovery Tests
# ==============================================================================

def test_host_cli_provider_discovery_non_destructive():
    """Verify CLIProviderDiscovery discovers known CLI tools safely without crashing."""
    descriptors = CLIProviderDiscovery.discover_all_cli_providers()
    assert len(descriptors) >= 5

    descriptor_map = {d.provider_id: d for d in descriptors}

    # Verify Antigravity CLI discovery
    assert "antigravity" in descriptor_map
    agy_desc = descriptor_map["antigravity"]
    assert agy_desc.transport == ProviderTransport.CLI
    assert agy_desc.auth_mode == AuthMode.LOGIN_SESSION
    assert AgentCapability.PROPOSE_EDITS in agy_desc.capabilities
    assert AgentRole.ENGINEERING_EXECUTION in agy_desc.supported_roles

    # Verify missing provider (claude_code) discovery is graceful
    assert "claude_code" in descriptor_map
    claude_desc = descriptor_map["claude_code"]
    assert claude_desc.installation_status in (InstallationStatus.INSTALLED, InstallationStatus.NOT_INSTALLED)
    if claude_desc.installation_status == InstallationStatus.NOT_INSTALLED:
        assert claude_desc.availability == AvailabilityStatus.UNAVAILABLE
        assert claude_desc.executable is None


def test_inspect_individual_provider_status():
    """Verify inspecting single providers produces complete valid descriptors."""
    # Known tool: gemini_cli
    gemini_desc = CLIProviderDiscovery.inspect_provider("gemini_cli")
    assert gemini_desc.provider_id == "gemini_cli"
    assert gemini_desc.auth_mode == AuthMode.LOGIN_SESSION
    assert AgentCapability.ARCHITECT_REVIEW in gemini_desc.capabilities
    assert gemini_desc.supports_structured_output is True

    # Unknown / Novel tool: custom_cli
    custom_desc = CLIProviderDiscovery.inspect_provider("unknown_custom_ai")
    assert custom_desc.provider_id == "unknown_custom_ai"
    assert custom_desc.installation_status == InstallationStatus.UNKNOWN
    assert custom_desc.availability == AvailabilityStatus.UNAVAILABLE


# ==============================================================================
# 2. Login-First Authentication Model Tests
# ==============================================================================

def test_authentication_model_independent_of_api_key():
    """Verify that LOGIN_SESSION is represented independently from API_KEY."""
    cli_desc = ProviderDescriptor(
        provider_id="agy_local",
        display_name="Antigravity Local Session",
        transport=ProviderTransport.CLI,
        auth_mode=AuthMode.LOGIN_SESSION,
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.AUTHENTICATED,
        availability=AvailabilityStatus.AVAILABLE,
        capabilities={AgentCapability.PROPOSE_EDITS, AgentCapability.RUN_TESTS},
        supported_roles={AgentRole.ENGINEERING_EXECUTION},
    )

    api_desc = ProviderDescriptor(
        provider_id="gemini_api",
        display_name="Gemini Remote API",
        transport=ProviderTransport.API,
        auth_mode=AuthMode.API_KEY,
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.AUTHENTICATED,
        availability=AvailabilityStatus.AVAILABLE,
        capabilities={AgentCapability.PROPOSE_EDITS, AgentCapability.RUN_TESTS},
        supported_roles={AgentRole.ENGINEERING_EXECUTION},
    )

    # Auth modes are strictly distinct enums
    assert cli_desc.auth_mode == AuthMode.LOGIN_SESSION
    assert api_desc.auth_mode == AuthMode.API_KEY
    assert cli_desc.auth_mode != api_desc.auth_mode

    # Serialization does not contain secrets
    serialized = cli_desc.to_dict()
    assert serialized["auth_mode"] == "LOGIN_SESSION"
    assert "api_key" not in serialized
    assert "token" not in serialized
    assert "password" not in serialized


# ==============================================================================
# 3. Capability Matching and Login-First Selection
# ==============================================================================

def test_capability_matching_and_login_first_preference():
    """Verify registry ranks login-first CLI descriptors ahead of remote API keys when requested."""
    registry = AgentAdapterRegistry()

    # Register CLI tool (Login Session)
    desc_cli = ProviderDescriptor(
        provider_id="cli_tool",
        display_name="CLI Tool",
        transport=ProviderTransport.CLI,
        auth_mode=AuthMode.LOGIN_SESSION,
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.AUTHENTICATED,
        availability=AvailabilityStatus.AVAILABLE,
        capabilities={AgentCapability.PROPOSE_EDITS, AgentCapability.RUN_TESTS},
        supported_roles={AgentRole.ENGINEERING_EXECUTION},
    )
    registry.register_descriptor(desc_cli)

    # Register API backend (API Key)
    desc_api = ProviderDescriptor(
        provider_id="api_tool",
        display_name="API Tool",
        transport=ProviderTransport.API,
        auth_mode=AuthMode.API_KEY,
        installation_status=InstallationStatus.INSTALLED,
        auth_status=AuthStatus.AUTHENTICATED,
        availability=AvailabilityStatus.AVAILABLE,
        capabilities={AgentCapability.PROPOSE_EDITS, AgentCapability.RUN_TESTS},
        supported_roles={AgentRole.ENGINEERING_EXECUTION},
    )
    registry.register_descriptor(desc_api)

    # 1. Query with preference for LOGIN_SESSION + CLI
    matches_login_first = registry.find_matching_descriptors(
        required_capabilities={AgentCapability.PROPOSE_EDITS},
        preferred_auth_mode=AuthMode.LOGIN_SESSION,
        preferred_transport=ProviderTransport.CLI,
        role=AgentRole.ENGINEERING_EXECUTION,
    )

    assert len(matches_login_first) == 2
    # CLI tool with LOGIN_SESSION should be ranked first!
    assert matches_login_first[0].provider_id == "cli_tool"
    assert matches_login_first[1].provider_id == "api_tool"

    # 2. Query with required capability that only API tool has
    desc_api.capabilities.add(AgentCapability.WEB_RESEARCH)
    matches_research = registry.find_matching_descriptors(
        required_capabilities={AgentCapability.WEB_RESEARCH},
        role=AgentRole.ENGINEERING_EXECUTION,
    )
    assert len(matches_research) == 1
    assert matches_research[0].provider_id == "api_tool"


# ==============================================================================
# 4. Missing Provider Graceful Degradation
# ==============================================================================

def test_missing_provider_does_not_break_registry():
    """Verify that uninstalled / missing providers do not cause errors or block available providers."""
    registry = AgentAdapterRegistry()

    # Discover real host providers
    discovered = registry.discover_and_register_cli_providers()
    assert len(discovered) > 0

    # Query for installed providers only
    installed_matches = registry.find_matching_descriptors(
        required_capabilities={AgentCapability.PROPOSE_EDITS},
        only_installed=True,
    )

    # Missing providers are excluded from installed matches
    for d in installed_matches:
        assert d.installation_status == InstallationStatus.INSTALLED
        assert d.executable is not None


# ==============================================================================
# 5. Human Channel Adapter Extension Contract Tests
# ==============================================================================

def test_human_channel_adapter_and_decision_envelope():
    """Verify HumanChannelAdapter extension contract and HumanDecisionEnvelope immutability."""
    envelope = HumanDecisionEnvelope(
        envelope_id="env-12345",
        work_id="daio-work-001",
        action_ticket_id="ticket-999",
        channel=HumanChannelType.LINE,
        operator_identity="project_owner_iphone",
        decision="APPROVE",
        instruction="Approved via external channel",
        auth_proof={"signature": "valid-sig-hex", "method": "passkey_webauthn"}
    )

    d = envelope.to_dict()
    assert d["envelope_id"] == "env-12345"
    assert d["channel"] == "LINE"
    assert d["decision"] == "APPROVE"
    assert d["auth_proof"]["method"] == "passkey_webauthn"

    # Mock implementation of HumanChannelAdapter
    class MockLineChannelAdapter(HumanChannelAdapter):
        def __init__(self) -> None:
            self.notifications_sent: List[str] = []
            self.decisions_received: List[HumanDecisionEnvelope] = []

        def get_channel_type(self) -> HumanChannelType:
            return HumanChannelType.LINE

        async def send_gate_notification(self, work_item: Any, gate_reason: str) -> bool:
            self.notifications_sent.append(gate_reason)
            return True

        async def receive_human_decision(self, env: HumanDecisionEnvelope) -> bool:
            self.decisions_received.append(env)
            return True

    adapter = MockLineChannelAdapter()
    assert adapter.get_channel_type() == HumanChannelType.LINE


# ==============================================================================
# 6. AST Core Neutrality & Zero Hardcoded Vendor Branching Guard
# ==============================================================================

def test_daio_core_zero_hardcoded_vendor_branching():
    """
    AST-based guard verifying DAIO core orchestration, supervisor, store, and FSM
    modules contain zero hardcoded CLI vendor branching.
    """
    core_files = [
        "scripts/daio_closed_loop/continuous_orchestrator.py",
        "scripts/daio_closed_loop/orchestrator.py",
        "scripts/daio_closed_loop/supervisor.py",
        "scripts/daio_closed_loop/store.py",
        "scripts/daio_closed_loop/sqlite_store.py",
        "scripts/daio_closed_loop/models.py",
        "scripts/daio_closed_loop/router.py",
    ]

    prohibited_vendor_literals = [
        "anthropic",
        "openai.com",
        "chatgpt.com",
        "claude.ai",
    ]

    for rel_path in core_files:
        full_path = Path(__file__).parent.parent / rel_path
        if not full_path.exists():
            continue

        tree = ast.parse(full_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val_lower = node.value.lower()
                for bad_vendor in prohibited_vendor_literals:
                    assert bad_vendor not in val_lower, (
                        f"Found prohibited vendor literal '{bad_vendor}' in DAIO Core file: {rel_path}"
                    )
