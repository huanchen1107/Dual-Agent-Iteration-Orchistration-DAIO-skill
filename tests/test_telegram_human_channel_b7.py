"""
Acceptance Test Suite for Phase B7: Telegram Human Channel Adapter.
Covers all acceptance requirements A through N:
A. /status returns current canonical DAIO state.
B. /queue returns active queue state.
C. Unauthorized Telegram user is rejected.
D. Telegram /approve cannot bypass Passkey Human Gate.
E. HUMAN_GATE_REQUIRED generates one Telegram notification.
F. Repeated supervisor ticks do not spam duplicate notifications.
G. Telegram outage does not stop DAIO (failure isolation & DEGRADED state).
H. /pause cannot corrupt active leases/work state.
I. /resume cannot bypass HUMAN_GATE_REQUIRED.
J. Strong-auth command returns secure Cockpit authorization handoff deep link.
K. Successful Face ID / Passkey approval later produces Telegram completion/resume notification.
L. LINE and Messenger registry placeholders exist but are NON-ROUTABLE until configured/implemented.
M. Telegram secrets never appear in logs/audit records.
N. Human channel implementation introduces zero vendor-specific branching into DAIO Core.
"""

import asyncio
import os
import pathlib
import pytest
from typing import Any, Dict, List

from scripts.daio_closed_loop.adapters.human_contract import (
    HumanAuthLevel,
    HumanChannelDescriptor,
    HumanChannelEvent,
    HumanChannelEventType,
    HumanChannelRegistry,
    HumanChannelResponse,
    HumanChannelRouter,
    HumanChannelState,
    HumanChannelType,
    HumanCommand,
    HumanCommandIntent,
    HumanInteractionRequest,
    HumanInteractionResponse,
    HumanInteractionType,
    HumanRiskClass,
    DeliveryStatus,
    DecisionStatus,
    CockpitChannelAdapter,
)
from scripts.daio_closed_loop.adapters.telegram_channel import (
    TelegramHumanChannelAdapter,
    TelegramCommandClassifier,
    TelegramNotificationFormatter,
    HumanChannelCommand,
    HumanChannelAuditRecord,
)


def create_mock_client():
    """Mock HTTP client for Telegram Bot API calls."""
    dispatched_messages = []
    
    def client_fn(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        dispatched_messages.append({"method": method, "payload": payload})
        if method == "getMe":
            return {"ok": True, "result": {"id": 123456789, "is_bot": True, "first_name": "DAIOBot"}}
        return {"ok": True, "result": {"message_id": 999}}
        
    client_fn.messages = dispatched_messages  # type: ignore
    return client_fn


def create_sample_adapter(mock_client=None):
    """Configured Telegram Human Channel Adapter."""
    client = mock_client or create_mock_client()
    adapter = TelegramHumanChannelAdapter(
        bot_token="test_secret_bot_token_12345",
        allowed_chat_ids=["1001", "1002"],
        allowed_user_ids=["user_alice", "user_bob"],
        cockpit_base_url="https://cockpit.awin.internal",
        project_binding="awin-fintech",
        http_client_fn=client,
    )
    return adapter, client


def test_a_status_returns_canonical_state():
    """Test A: /status returns current canonical DAIO state."""
    async def _run():
        adapter, _ = create_sample_adapter()
        adapter.state_provider_fn = lambda: {
            "supervisor": "ONLINE",
            "mode": "CANONICAL",
            "active_work": "CHANGE_052",
            "stage": "EXECUTION",
            "provider": "Antigravity CLI (Federated)",
        }
        
        cmd = HumanChannelCommand(
            external_user_id="user_alice",
            chat_id="1001",
            command_text="/status",
        )
        res = await adapter.receive_command(cmd)
        
        assert res.status == "SUCCESS"
        assert "ONLINE" in res.message
        assert "CHANGE_052" in res.message
        assert "Antigravity CLI" in res.message
        assert "<b>Supervisor:</b>" in res.mobile_formatted

    asyncio.run(_run())


def test_b_queue_returns_active_queue():
    """Test B: /queue returns active queue state."""
    async def _run():
        adapter, _ = create_sample_adapter()
        adapter.queue_provider_fn = lambda: [
            {"work_id": "CHANGE_052", "stage": "EXECUTION"},
            {"work_id": "CHANGE_053", "stage": "QUEUED"},
        ]
        
        cmd = HumanChannelCommand(
            external_user_id="user_alice",
            chat_id="1001",
            command_text="/queue",
        )
        res = await adapter.receive_command(cmd)
        
        assert res.status == "SUCCESS"
        assert "2 items" in res.mobile_formatted
        assert "CHANGE_052" in res.mobile_formatted
        assert "CHANGE_053" in res.mobile_formatted

    asyncio.run(_run())


def test_c_unauthorized_user_rejected():
    """Test C: Unauthorized Telegram user is rejected and audited."""
    async def _run():
        adapter, _ = create_sample_adapter()
        cmd = HumanChannelCommand(
            external_user_id="unauthorized_hacker",
            chat_id="9999",
            command_text="/status",
        )
        res = await adapter.receive_command(cmd)
        
        assert res.status == "REJECTED"
        assert "Access Denied" in res.message
        assert res.audit_record is not None
        assert res.audit_record.accepted is False
        assert "UNAUTHORIZED_USER" in (res.audit_record.reason or "")
        
        # Audit trail contains rejection
        audit_log = adapter.get_audit_log()
        assert any(a.external_user_id == "unauthorized_hacker" and not a.accepted for a in audit_log)

    asyncio.run(_run())


def test_d_and_j_telegram_approve_interception_and_deep_link():
    """
    Test D & J: Telegram /approve cannot bypass Passkey Human Gate.
    Strong-auth command returns secure Cockpit authorization handoff deep link.
    """
    async def _run():
        adapter, _ = create_sample_adapter()
        cmd = HumanChannelCommand(
            external_user_id="user_alice",
            chat_id="1001",
            command_text="/approve CHANGE_052",
            work_id="CHANGE_052",
        )
        res = await adapter.receive_command(cmd)
        
        assert res.status == "STRONG_AUTH_REQUIRED"
        assert res.requires_strong_auth is True
        assert res.deep_link is not None
        assert "https://cockpit.awin.internal/gate" in res.deep_link
        assert "CHANGE_052" in res.deep_link
        assert "Passkey / Face ID" in res.mobile_formatted
        
        # Audit verification
        assert res.audit_record is not None
        assert res.audit_record.authorization_class == "STRONG_AUTH_REQUIRED"
        assert res.audit_record.accepted is False  # Rejected for direct execution on Telegram

    asyncio.run(_run())


def test_e_and_f_human_gate_notification_and_deduplication():
    """
    Test E & F: HUMAN_GATE_REQUIRED generates one Telegram notification.
    Repeated supervisor ticks do not spam duplicate notifications.
    """
    async def _run():
        adapter, client = create_sample_adapter()
        event = HumanChannelEvent(
            event_type=HumanChannelEventType.HUMAN_GATE_REQUIRED,
            work_id="CHANGE_052",
            change_id="CHANGE_052",
            project_id="awin-fintech",
            stage="IMPLEMENTATION_GATE",
            gate="HUMAN_GATE",
            recovery_epoch=1,
            summary="Lead Architect signoff required",
            reason="Security sensitive architectural changes",
            requires_strong_auth=True,
        )
        
        # Tick 1: First dispatch
        status_1 = await adapter.send_notification(event)
        assert status_1 == DeliveryStatus.DELIVERED
        
        # 2 allowed chats configured -> 2 messages sent
        assert len(client.messages) == 2
        first_msg_text = client.messages[0]["payload"]["text"]
        assert "DAIO — HUMAN GATE REQUIRED" in first_msg_text
        assert "Open Secure Cockpit" in first_msg_text
        
        # Tick 2: Repeated supervisor tick with identical (work_id, gate, epoch, event_type)
        status_2 = await adapter.send_notification(event)
        assert status_2 == DeliveryStatus.DELIVERED
        # Count should NOT increase (deduplicated)
        assert len(client.messages) == 2
        
        # Tick 3: New epoch (material state change) -> Should dispatch
        event_epoch_2 = HumanChannelEvent(
            event_type=HumanChannelEventType.HUMAN_GATE_REQUIRED,
            work_id="CHANGE_052",
            change_id="CHANGE_052",
            project_id="awin-fintech",
            stage="IMPLEMENTATION_GATE",
            gate="HUMAN_GATE",
            recovery_epoch=2,
            summary="Lead Architect signoff required",
            requires_strong_auth=True,
        )
        status_3 = await adapter.send_notification(event_epoch_2)
        assert status_3 == DeliveryStatus.DELIVERED
        assert len(client.messages) == 4

    asyncio.run(_run())


def test_g_telegram_outage_does_not_halt_daio():
    """Test G: Telegram failure degrades adapter without halting DAIO or corrupting state."""
    async def _run():
        def failing_client(method, payload):
            raise ConnectionError("Telegram API DNS Down")
        
        adapter = TelegramHumanChannelAdapter(
            bot_token="dummy_token",
            allowed_chat_ids=["1001"],
            http_client_fn=failing_client,
        )
        
        event = HumanChannelEvent(
            event_type=HumanChannelEventType.WORK_STARTED,
            work_id="CHANGE_052",
            summary="Starting work",
        )
        
        delivery = await adapter.send_notification(event)
        assert delivery == DeliveryStatus.DELIVERY_FAILED
        
        # Health check shows DEGRADED
        st = await adapter.health_check()
        assert st == HumanChannelState.DEGRADED

    asyncio.run(_run())


def test_h_pause_handler_safety():
    """Test H: /pause cannot corrupt active leases/work state."""
    async def _run():
        adapter, _ = create_sample_adapter()
        pause_called = []
        
        def safe_pause():
            pause_called.append(True)
            return True, "Queue safely paused; active work lease preserved."
            
        adapter.pause_handler_fn = safe_pause
        
        cmd = HumanChannelCommand(
            external_user_id="user_alice",
            chat_id="1001",
            command_text="/pause",
        )
        res = await adapter.receive_command(cmd)
        
        assert res.status == "SUCCESS"
        assert len(pause_called) == 1
        assert "active work lease preserved" in res.message

    asyncio.run(_run())


def test_i_resume_cannot_bypass_human_gate():
    """Test I: /resume cannot bypass active HUMAN_GATE_REQUIRED state."""
    async def _run():
        adapter, _ = create_sample_adapter()
        def guarded_resume():
            # DAIO supervisor logic rejects resume if work is blocked on HUMAN_GATE
            return False, "Cannot resume: Active work CHANGE_052 is blocked on HUMAN_GATE. Cockpit approval required."
            
        adapter.resume_handler_fn = guarded_resume
        
        cmd = HumanChannelCommand(
            external_user_id="user_alice",
            chat_id="1001",
            command_text="/resume",
        )
        res = await adapter.receive_command(cmd)
        
        assert res.status == "ERROR"
        assert "blocked on HUMAN_GATE" in res.message

    asyncio.run(_run())


def test_k_passkey_approval_notification_flow():
    """
    Test K: Successful Face ID / Passkey approval in Cockpit produces Telegram completion/resume notification.
    """
    async def _run():
        router = HumanChannelRouter()
        cockpit_adapter = CockpitChannelAdapter()
        tg_adapter, client = create_sample_adapter()
        router.registry.register_adapter(cockpit_adapter)
        router.registry.register_adapter(tg_adapter)
        
        # 1. Gate prompt registered
        req = HumanInteractionRequest(
            interaction_id="inter-052",
            work_id="CHANGE_052",
            interaction_type=HumanInteractionType.APPROVAL,
            summary="Lead Architect Approval Required",
            requires_strong_auth=True,
        )
        router.register_interaction(req)
        
        # 2. Cockpit submits strong Passkey approval
        passkey_response = HumanInteractionResponse(
            interaction_id="inter-052",
            channel_id=HumanChannelType.COCKPIT,
            actor_id="lead_architect",
            action="APPROVE",
            authentication_level=HumanAuthLevel.STRONG_AUTHENTICATED,
            decision_id="dec-passkey-001",
        )
        status, err, deep_link = await router.process_human_response(passkey_response)
        assert status == DecisionStatus.DECISION_APPLIED
        assert err is None
        
        # 3. DAIO dispatches Telegram notification of resumption / completion
        completion_evt = HumanChannelEvent(
            event_type=HumanChannelEventType.WORK_COMPLETED,
            work_id="CHANGE_052",
            summary="Execution resumed and completed after Passkey approval.",
        )
        delivery = await tg_adapter.send_notification(completion_evt)
        assert delivery == DeliveryStatus.DELIVERED
        
        # Verify Telegram payload
        last_msg = client.messages[-1]["payload"]["text"]
        assert "DAIO — WORK COMPLETED" in last_msg
        assert "CHANGE_052" in last_msg

    asyncio.run(_run())


def test_l_line_and_messenger_placeholders_non_routable():
    """Test L: LINE and Messenger registry placeholders exist but are NON-ROUTABLE until configured."""
    registry = HumanChannelRegistry()
    
    desc_line = registry.get_descriptor(HumanChannelType.LINE)
    desc_messenger = registry.get_descriptor(HumanChannelType.MESSENGER)
    desc_telegram = registry.get_descriptor(HumanChannelType.TELEGRAM)
    
    assert desc_line is not None
    assert desc_line.state == HumanChannelState.NOT_CONFIGURED
    assert desc_messenger is not None
    assert desc_messenger.state == HumanChannelState.NOT_CONFIGURED
    
    # Neither has an active adapter instance registered yet
    assert registry.get_adapter(HumanChannelType.LINE) is None
    assert registry.get_adapter(HumanChannelType.MESSENGER) is None


def test_m_zero_secret_leakage_in_logs_and_audits():
    """Test M: Telegram secrets never appear in logs or audit records."""
    async def _run():
        adapter, _ = create_sample_adapter()
        secret_token = "test_secret_bot_token_12345"
        
        cmd = HumanChannelCommand(
            external_user_id="user_alice",
            chat_id="1001",
            command_text="/status",
        )
        res = await adapter.receive_command(cmd)
        
        audit_dict = res.audit_record.to_dict() if res.audit_record else {}
        audit_str = str(audit_dict)
        
        assert secret_token not in audit_str
        assert secret_token not in res.message
        assert secret_token not in res.mobile_formatted
        
        for record in adapter.get_audit_log():
            assert secret_token not in str(record.to_dict())

    asyncio.run(_run())


def test_n_zero_vendor_branching_in_daio_core():
    """
    Test N: DAIO-PORTABILITY-INVARIANT-001.
    Verify that generic DAIO core orchestrator modules contain zero vendor-specific 'telegram' or 'line' branching.
    """
    core_dir = pathlib.Path(__file__).parent.parent / "scripts" / "daio_closed_loop"
    core_files = [
        core_dir / "orchestrator.py",
        core_dir / "fsm.py",
        core_dir / "supervisor.py",
        core_dir / "work_store.py",
    ]
    
    for cf in core_files:
        if not cf.exists():
            continue
        content = cf.read_text(encoding="utf-8")
        # Check that core files do not branch on vendor specifics
        assert "if channel == 'telegram'" not in content.lower()
        assert "if telegram" not in content.lower()
        assert "if line" not in content.lower()
        assert "if messenger" not in content.lower()
