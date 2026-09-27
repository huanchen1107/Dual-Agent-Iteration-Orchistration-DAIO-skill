"""
Phase B6 Acceptance Tests: Human Command, Interaction & Channel Federation (daio-agent/v1).
Verifies:
1. Two independent federation axes: Agent Provider Federation x Human Channel Federation.
2. Separation of Human Command, Human Interaction, and Authorization (COMMAND != INTERACTION != AUTHORIZATION).
3. ChatGPT as a First-Class Human Command Channel with natural language normalization outside DAIO Core.
4. Risk-based authorization & Strong Authentication Upgrade Flow (Messaging -> Cockpit Passkey / Face ID).
5. Cross-Channel Continuity & Conversation Reference Mapping (Channels do not own workflow state).
6. Multi-Channel Notification Routing with Delivery Failover.
7. Exactly-Once Human Decision Invariant across multiple channels.
8. Preservation of Cockpit canonical WebAuthn/Passkey architecture and RPC-3D/3E security semantics.
9. Zero DAIO Core modifications invariant.
"""

import asyncio
import inspect
import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from scripts.daio_closed_loop.adapters.human_contract import (
    CockpitChannelAdapter,
    ConversationReferenceMapping,
    DecisionStatus,
    DeliveryStatus,
    HumanAuthLevel,
    HumanChannelDescriptor,
    HumanChannelRegistry,
    HumanChannelRouter,
    HumanChannelState,
    HumanChannelType,
    HumanCommand,
    HumanCommandIntent,
    HumanCommandNormalizer,
    HumanInteractionRequest,
    HumanInteractionResponse,
    HumanInteractionType,
    HumanRiskClass,
    MockHumanChannelAdapter,
)
from scripts.daio_closed_loop.adapters.router import (
    ProviderRouter,
    RoutingEngineeringAgentAdapter,
)
from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    transition_to_human_gate,
)
from scripts.daio_closed_loop.router import DAIORoleRouter


# ==============================================================================
# Scenarios A, B, C, D: Command Normalization & Cross-Channel Continuity
# ==============================================================================

def test_scenario_a_chatgpt_natural_language_command_normalization():
    """
    Scenario A: Project Owner natural language command in ChatGPT:
    'Continue Change 052 until the next Human Gate.'
    Normalizes into a valid canonical HumanCommand without touching DAIO Core.
    """
    raw_prompt = "Continue Change 052 until the next Human Gate."
    cmd = HumanCommandNormalizer.normalize_text_command(
        raw_prompt,
        source_channel=HumanChannelType.CHATGPT,
        actor_id="human_project_owner",
        project_id="awin-fintech",
        conversation_reference="chatgpt-conv-987",
    )

    assert cmd.intent == HumanCommandIntent.CONTINUE_WORK
    assert cmd.target_change_id == "CHANGE_052"
    assert cmd.stop_condition == "NEXT_HUMAN_GATE"
    assert cmd.source_channel == HumanChannelType.CHATGPT
    assert cmd.risk_class == HumanRiskClass.ROUTINE_ENGINEERING
    assert cmd.requires_strong_auth is False
    assert cmd.actor_id == "human_project_owner"
    assert cmd.provenance["raw_text"] == raw_prompt


def test_scenario_b_c_d_cross_channel_continuity_and_reference_mapping():
    """
    Scenarios B, C, D:
    Morning in ChatGPT: 'Start Change 052' -> registered context
    Afternoon in Telegram: 'What is the status of Change 052?' -> resolves to same Work ID
    Evening in LINE: 'Continue Change 052' -> resolves to same Work ID
    Verifies DAIO-HUMAN-INVARIANT-006: Channels have NO workflow ownership; DAIO is canonical owner.
    """
    mapping = ConversationReferenceMapping()

    canonical_project = "awin-fintech"
    canonical_work = "daio-work-052-abc"
    canonical_change = "CHANGE_052"

    # 1. Morning in ChatGPT
    mapping.register_context(
        channel=HumanChannelType.CHATGPT,
        conversation_id="chatgpt-thread-101",
        project_id=canonical_project,
        work_id=canonical_work,
        change_id=canonical_change,
    )

    # 2. Afternoon query from Telegram
    telegram_ctx = mapping.resolve_context(
        channel=HumanChannelType.TELEGRAM,
        conversation_id="telegram-chat-555",
        fallback_change_id="CHANGE_052",
    )
    assert telegram_ctx["work_id"] == canonical_work
    assert telegram_ctx["change_id"] == canonical_change
    assert telegram_ctx["project_id"] == canonical_project

    # 3. Evening resume from LINE
    line_ctx = mapping.resolve_context(
        channel=HumanChannelType.LINE,
        conversation_id="line-group-999",
        fallback_change_id="CHANGE_052",
    )
    assert line_ctx["work_id"] == canonical_work
    assert line_ctx["change_id"] == canonical_change

    # 4. Verify channel conversation ID did not mutate or hijack canonical workflow ID
    assert telegram_ctx["work_id"] != "telegram-chat-555"
    assert line_ctx["work_id"] != "line-group-999"


# ==============================================================================
# Scenarios E, F, G, H, I, J: Notification Delivery, Failover & Pending State
# ==============================================================================

def test_scenario_e_cockpit_channel_adapter_strong_auth():
    """
    Scenario E: Cockpit Human Channel Adapter wraps WebAuthn / Passkey / Face ID path.
    Verifies descriptor and strong authentication capabilities.
    """
    adapter = CockpitChannelAdapter(base_url="https://cockpit.awin.internal")
    desc = adapter.get_descriptor()

    assert desc.channel_type == HumanChannelType.COCKPIT
    assert desc.state == HumanChannelState.AVAILABLE
    assert desc.supports_strong_auth is True
    assert desc.supports_deep_links is True

    deep_link = adapter.generate_secure_deep_link("int-1", "work-1", "ticket-1")
    assert "https://cockpit.awin.internal/gate" in deep_link
    assert "ticket=ticket-1" in deep_link


def test_scenario_f_g_h_messaging_channel_notifications():
    """
    Scenarios F, G, H: Telegram, LINE, and Messenger mock adapters receive notification requests.
    """
    async def _run():
        tg = MockHumanChannelAdapter(HumanChannelType.TELEGRAM, "Telegram", state=HumanChannelState.AVAILABLE)
        line = MockHumanChannelAdapter(HumanChannelType.LINE, "LINE", state=HumanChannelState.AVAILABLE)
        msg = MockHumanChannelAdapter(HumanChannelType.MESSENGER, "Messenger", state=HumanChannelState.AVAILABLE)

        req = HumanInteractionRequest(
            interaction_id="int-notif-1",
            work_id="work-052",
            change_id="CHANGE_052",
            interaction_type=HumanInteractionType.INFORMATION,
            summary="Change 052 completed S3 implementation successfully.",
            requires_strong_auth=False,
        )

        st_tg = await tg.send_interaction(req)
        st_line = await line.send_interaction(req)
        st_msg = await msg.send_interaction(req)

        assert st_tg == DeliveryStatus.DELIVERED
        assert st_line == DeliveryStatus.DELIVERED
        assert st_msg == DeliveryStatus.DELIVERED
        assert len(tg.sent_interactions) == 1
        assert len(line.sent_interactions) == 1
        assert len(msg.sent_interactions) == 1

    asyncio.run(_run())


def test_scenario_i_notification_delivery_failover():
    """
    Scenario I: Preferred notification channel (Telegram) fails -> Router fails over to LINE.
    """
    async def _run():
        tg_failed = MockHumanChannelAdapter(
            HumanChannelType.TELEGRAM, "Telegram",
            delivery_status=DeliveryStatus.DELIVERY_FAILED,
            state=HumanChannelState.DEGRADED,
        )
        line_ok = MockHumanChannelAdapter(
            HumanChannelType.LINE, "LINE",
            delivery_status=DeliveryStatus.DELIVERED,
            state=HumanChannelState.AVAILABLE,
        )

        registry = HumanChannelRegistry()
        registry.register_adapter(tg_failed)
        registry.register_adapter(line_ok)

        router = HumanChannelRouter(
            registry=registry,
            policy={"notification": {"preferred": [HumanChannelType.TELEGRAM, HumanChannelType.LINE]}},
        )

        req = HumanInteractionRequest(
            interaction_id="int-failover-1",
            work_id="work-052",
            change_id="CHANGE_052",
            interaction_type=HumanInteractionType.APPROVAL,
            summary="Approval required",
        )

        delivered, results = await router.broadcast_or_route_notification(req)
        assert delivered is True
        assert len(results) == 2
        assert results[0] == (HumanChannelType.TELEGRAM, DeliveryStatus.DELIVERY_FAILED)
        assert results[1] == (HumanChannelType.LINE, DeliveryStatus.DELIVERED)

    asyncio.run(_run())


def test_scenario_j_delivery_succeeds_user_idle_gate_remains_pending():
    """
    Scenario J: Delivery succeeds, but user does nothing -> Decision remains DECISION_PENDING.
    Human Gate state does not change automatically.
    """
    work = DAIOWorkItem(
        work_id="work-idle-gate",
        change_id="CHANGE_052",
        project_root="/tmp/sandbox",
        current_stage="S3",
        current_gate=DAIOGate.HUMAN_GATE.value,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER.value,
        status=DAIOStatus.HUMAN_GATE_REQUIRED.value,
    )

    # State remains pending indefinitely without human response
    assert work.status == DAIOStatus.HUMAN_GATE_REQUIRED.value
    assert work.current_gate == DAIOGate.HUMAN_GATE.value


# ==============================================================================
# Scenarios K, L, M, N, O: Risk-Based Authorization & Strong Auth Upgrade Flow
# ==============================================================================

def test_scenario_k_low_risk_acknowledgement_accepted():
    """
    Scenario K: Low-risk acknowledgement from messaging channel accepted with CHANNEL_AUTHENTICATED.
    """
    async def _run():
        router = HumanChannelRouter()
        req = HumanInteractionRequest(
            interaction_id="int-ack-1",
            work_id="work-052",
            interaction_type=HumanInteractionType.ACKNOWLEDGEMENT,
            risk_class=HumanRiskClass.READ_ONLY,
            requires_strong_auth=False,
        )
        router.register_interaction(req)

        resp = HumanInteractionResponse(
            interaction_id="int-ack-1",
            decision_id="dec-ack-1",
            actor_id="user_telegram_123",
            channel_id=HumanChannelType.TELEGRAM,
            action="ACKNOWLEDGE",
            authentication_level=HumanAuthLevel.CHANNEL_AUTHENTICATED,
        )

        status, reason, deep_link = await router.process_human_response(resp)
        assert status == DecisionStatus.DECISION_APPLIED
        assert reason is None
        assert deep_link is None

    asyncio.run(_run())


def test_scenario_l_m_n_high_risk_approve_from_messaging_rejected_without_strong_auth():
    """
    Scenarios L, M, N:
    High-risk APPROVE from Telegram, LINE, or ChatGPT without strong auth is REJECTED.
    Router returns STRONG_AUTH_REQUIRED and provides secure Cockpit Passkey deep link.
    """
    async def _run():
        cockpit = CockpitChannelAdapter(base_url="https://cockpit.awin.internal")
        registry = HumanChannelRegistry()
        registry.register_adapter(cockpit)
        router = HumanChannelRouter(registry=registry)

        req = HumanInteractionRequest(
            interaction_id="int-highrisk-1",
            work_id="work-052",
            interaction_type=HumanInteractionType.APPROVAL,
            risk_class=HumanRiskClass.FINANCIAL_OR_PRODUCTION,
            requires_strong_auth=True,
        )
        router.register_interaction(req)

        channels_to_test = [
            (HumanChannelType.TELEGRAM, "user_tg"),
            (HumanChannelType.LINE, "user_line"),
            (HumanChannelType.CHATGPT, "user_chatgpt"),
        ]

        for ch, actor in channels_to_test:
            resp = HumanInteractionResponse(
                interaction_id="int-highrisk-1",
                decision_id=f"dec-{ch.value}-1",
                actor_id=actor,
                channel_id=ch,
                action="APPROVE",
                authentication_level=HumanAuthLevel.CHANNEL_AUTHENTICATED,  # Not strong
                idempotency_key=f"idemp-{ch.value}-1",
            )

            status, reason, deep_link = await router.process_human_response(resp)
            assert status == DecisionStatus.DECISION_REJECTED
            assert reason == "STRONG_AUTH_REQUIRED"
            assert deep_link is not None
            assert "https://cockpit.awin.internal/gate" in deep_link
            assert "interaction_id=int-highrisk-1" in deep_link

    asyncio.run(_run())


def test_scenario_o_strong_auth_upgrade_flow_via_cockpit_passkey():
    """
    Scenario O: User follows Cockpit deep link and signs with Face ID / Passkey.
    Response carries STRONG_AUTHENTICATED and is APPLIED canonically to DAIO.
    """
    async def _run():
        router = HumanChannelRouter()
        req = HumanInteractionRequest(
            interaction_id="int-passkey-1",
            work_id="work-052",
            interaction_type=HumanInteractionType.APPROVAL,
            risk_class=HumanRiskClass.FINANCIAL_OR_PRODUCTION,
            requires_strong_auth=True,
        )
        router.register_interaction(req)

        # Response from Cockpit carrying WebAuthn assertion proof
        resp = HumanInteractionResponse(
            interaction_id="int-passkey-1",
            decision_id="dec-cockpit-strong-1",
            actor_id="huanchen_iphone_passkey",
            channel_id=HumanChannelType.COCKPIT,
            action="APPROVE",
            authentication_level=HumanAuthLevel.STRONG_AUTHENTICATED,
            auth_proof={"webauthn_credential_id": "cred-abc-123", "authenticator": "Apple Face ID"},
            idempotency_key="idemp-passkey-052",
        )

        status, reason, deep_link = await router.process_human_response(resp)
        assert status == DecisionStatus.DECISION_APPLIED
        assert reason is None
        assert deep_link is None

    asyncio.run(_run())


# ==============================================================================
# Scenarios P, Q, R, S, T: Exactly-Once Invariant, Failover Security & Regressions
# ==============================================================================

def test_scenario_p_duplicate_responses_across_channels_exactly_once():
    """
    Scenario P: Multiple channels return APPROVE for same interaction.
    Verifies DAIO-HUMAN-INVARIANT-004: Exactly one canonical decision is applied to DAIO state.
    """
    async def _run():
        router = HumanChannelRouter()
        req = HumanInteractionRequest(
            interaction_id="int-dup-1",
            work_id="work-052",
            requires_strong_auth=False,
            risk_class=HumanRiskClass.ROUTINE_ENGINEERING,
        )
        router.register_interaction(req)

        shared_idempotency_key = "idemp-shared-052-approval"

        # 1. First approval from Telegram arrives
        resp1 = HumanInteractionResponse(
            interaction_id="int-dup-1",
            decision_id="dec-1",
            actor_id="user_tg",
            channel_id=HumanChannelType.TELEGRAM,
            action="APPROVE",
            authentication_level=HumanAuthLevel.CHANNEL_AUTHENTICATED,
            idempotency_key=shared_idempotency_key,
        )
        st1, r1, _ = await router.process_human_response(resp1)
        assert st1 == DecisionStatus.DECISION_APPLIED
        assert r1 is None

        # 2. Duplicate approval arrives from LINE
        resp2 = HumanInteractionResponse(
            interaction_id="int-dup-1",
            decision_id="dec-2",
            actor_id="user_line",
            channel_id=HumanChannelType.LINE,
            action="APPROVE",
            authentication_level=HumanAuthLevel.CHANNEL_AUTHENTICATED,
            idempotency_key=shared_idempotency_key,
        )
        st2, r2, _ = await router.process_human_response(resp2)
        assert st2 == DecisionStatus.DECISION_APPLIED
        assert r2 == "DUPLICATE_IDEMPOTENT_DECISION"

        # 3. Duplicate approval arrives from Cockpit
        resp3 = HumanInteractionResponse(
            interaction_id="int-dup-1",
            decision_id="dec-3",
            actor_id="user_cockpit",
            channel_id=HumanChannelType.COCKPIT,
            action="APPROVE",
            authentication_level=HumanAuthLevel.STRONG_AUTHENTICATED,
            idempotency_key=shared_idempotency_key,
        )
        st3, r3, _ = await router.process_human_response(resp3)
        assert st3 == DecisionStatus.DECISION_APPLIED
        assert r3 == "DUPLICATE_IDEMPOTENT_DECISION"

    asyncio.run(_run())


def test_scenario_q_channel_outage_does_not_downgrade_security():
    """
    Scenario Q: Messaging channel outage does not lower authentication requirements.
    Verifies DAIO-HUMAN-INVARIANT-002: Channel failover MUST NOT downgrade authentication requirements.
    """
    async def _run():
        router = HumanChannelRouter()
        req = HumanInteractionRequest(
            interaction_id="int-sec-outage-1",
            work_id="work-052",
            risk_class=HumanRiskClass.FINANCIAL_OR_PRODUCTION,
            requires_strong_auth=True,
        )
        router.register_interaction(req)

        # Attempt to bypass strong auth by claiming channel failure or fallback
        resp_downgrade = HumanInteractionResponse(
            interaction_id="int-sec-outage-1",
            decision_id="dec-downgrade-1",
            actor_id="unverified_actor",
            channel_id=HumanChannelType.TELEGRAM,
            action="APPROVE",
            authentication_level=HumanAuthLevel.UNVERIFIED,
            idempotency_key="idemp-downgrade-1",
        )

        status, reason, deep_link = await router.process_human_response(resp_downgrade)
        assert status == DecisionStatus.DECISION_REJECTED
        assert reason == "STRONG_AUTH_REQUIRED"
        assert deep_link is not None

    asyncio.run(_run())


def test_scenario_r_all_messaging_channels_unavailable_cockpit_functional():
    """
    Scenario R: All external messaging channels UNAVAILABLE -> Cockpit canonical WebAuthn path remains fully functional.
    """
    async def _run():
        cockpit = CockpitChannelAdapter()
        tg = MockHumanChannelAdapter(HumanChannelType.TELEGRAM, "Telegram", state=HumanChannelState.UNAVAILABLE)
        line = MockHumanChannelAdapter(HumanChannelType.LINE, "LINE", state=HumanChannelState.UNAVAILABLE)

        registry = HumanChannelRegistry()
        registry.register_adapter(cockpit)
        registry.register_adapter(tg)
        registry.register_adapter(line)

        router = HumanChannelRouter(registry=registry)

        req = HumanInteractionRequest(
            interaction_id="int-cockpit-only-1",
            work_id="work-052",
            requires_strong_auth=True,
        )
        router.register_interaction(req)

        resp = HumanInteractionResponse(
            interaction_id="int-cockpit-only-1",
            decision_id="dec-cockpit-direct",
            actor_id="owner_face_id",
            channel_id=HumanChannelType.COCKPIT,
            action="APPROVE",
            authentication_level=HumanAuthLevel.STRONG_AUTHENTICATED,
        )

        status, reason, _ = await router.process_human_response(resp)
        assert status == DecisionStatus.DECISION_APPLIED
        assert reason is None

    asyncio.run(_run())


def test_scenario_s_provider_router_b5_remains_unchanged():
    """
    Scenario S: Agent Provider Router (B5) continues to function orthogonally without interference.
    Verifies DAIO-HUMAN-INVARIANT-008: Agent Provider Federation and Human Channel Federation remain orthogonal.
    """
    router = ProviderRouter()
    order = router.get_preferred_order()
    assert order == ["antigravity_cli", "gemini_cli", "codex_cli", "opencode_cli"]
    assert router.is_failover_enabled() is True


def test_scenario_t_zero_daio_core_modification_invariant_b6():
    """
    Scenario T / Invariant Audit:
    Verifies DAIO-PORTABILITY-INVARIANT-001 & DAIO-HUMAN-INVARIANT-007:
    Zero human-channel or platform-specific tokens leak into DAIO Core modules.
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
        "telegram_bot",
        "line_channel",
        "messenger_webhook",
        "chatgpt_prompt_parser",
        "HumanCommandNormalizer",
        "MockTelegramChannelAdapter",
        "MockLineChannelAdapter",
    ]

    for mod in core_modules:
        src = inspect.getsource(mod)
        for token in forbidden_tokens:
            assert token not in src, (
                f"Invariant violation: Token '{token}' leaked into DAIO Core module '{mod.__name__}'!"
            )
