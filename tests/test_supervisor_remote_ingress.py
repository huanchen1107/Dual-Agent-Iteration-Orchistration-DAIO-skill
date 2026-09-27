"""
RPC-3E Verification Suite:
Tests DAIOSupervisor Persistent Remote Ingress & Zero-Touch Resume.
Proves that remote decisions arriving on Cloudflare edge are automatically polled,
ingested via atomic SQLite compare-and-apply, acknowledged, and resumed by the supervisor
without any human intervention, IDE chat commands, or interactive permission prompts.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import os
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.daio_closed_loop.models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.adapters.remote_relay import (
    RemoteDecisionAdapter,
    RemoteDecisionEnvelope,
    RemoteDecisionRelayClient,
    TransportDeliveryState,
)
from scripts.daio_closed_loop.adapters.agent_contract import AgentTaskProposal, ProposedFileEdit
from scripts.daio_closed_loop.adapters.executor import EngineeringExecutorAdapter, ExecutionResult
from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter


class MockRemoteDecisionRelayClient:
    """Mock outbound-only transport client simulating Cloudflare DECISION_KV."""

    def __init__(self, project_id: str = "awin-fintech") -> None:
        self.project_id = project_id
        self.pending_envelopes = []
        self.acknowledged_ids = []

    def poll_decisions(self, work_id: str = None):
        if work_id:
            return [e for e in self.pending_envelopes if e.work_id == work_id]
        return list(self.pending_envelopes)

    def acknowledge_decision(self, decision_id: str, status: str = "ACKNOWLEDGED") -> bool:
        self.acknowledged_ids.append(decision_id)
        self.pending_envelopes = [e for e in self.pending_envelopes if e.decision_id != decision_id]
        return True


class MockAutoResumeExecutor(EngineeringExecutorAdapter):
    """Executor verifying unattended execution of resumed work."""

    def __init__(self) -> None:
        self.executed_work_ids = []

    def execute_task(
        self,
        work: DAIOWorkItem,
        command: str = None,
        test_command: str = None,
        commit_message: str = None,
    ) -> ExecutionResult:
        self.executed_work_ids.append(work.work_id)
        proposal = AgentTaskProposal(
            work_id=work.work_id,
            success=True,
            backend_identity="ANTIGRAVITY_CLI",
            model_name="antigravity-cli-default",
            reasoning_summary="Auto-executed by persistent supervisor",
            proposed_edits=[
                ProposedFileEdit(file_path="src/logic.py", new_content="# auto-resumed logic\n", description="edit")
            ],
            started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        return ExecutionResult(
            success=True,
            test_passed=True,
            generated_commit_sha="9999aaaa",
            proposal=proposal,
        )

    async def execute_task_async(
        self,
        work: DAIOWorkItem,
        command: str = None,
        test_command: str = None,
        commit_message: str = None,
    ) -> ExecutionResult:
        return self.execute_task(work, command, test_command, commit_message)


def test_supervisor_initializes_remote_relay_adapter(tmp_path):
    """Proves supervisor automatically instantiates remote relay adapter when configured."""
    store = SqliteDAIOWorkStore(str(tmp_path / "daio_work.db"))
    mock_client = MockRemoteDecisionRelayClient()
    adapter = RemoteDecisionAdapter(project_id="awin-fintech", client=mock_client)

    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
        remote_relay_adapter=adapter,
        enable_remote_ingress=True,
    )

    assert supervisor.remote_relay_adapter is not None
    assert supervisor.remote_relay_adapter.project_id == "awin-fintech"


def test_supervisor_remote_decision_arrival_zero_touch_resume(tmp_path):
    """
    Core RPC-3E E2E Invariant:
    1. Work item waiting at HUMAN_GATE / HUMAN_GATE_REQUIRED / HUMAN_PROJECT_OWNER.
    2. Remote decision envelope arrives in Cloudflare Relay buffer.
    3. Supervisor run_tick() automatically:
       a. Detects and polls decision.
       b. Atomically applies decision via BEGIN IMMEDIATE (HUMAN_GATE -> QUEUED).
       c. Sends ACK to Cloudflare (queue cleared).
       d. Persistent worker claims work and executes via agent adapter.
       e. Completes work without any IDE chat or permission prompt.
    """
    async def _test():
        store = SqliteDAIOWorkStore(str(tmp_path / "daio_work.db"))
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        exp_iso = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)).isoformat()

        # 1. Create work item at HUMAN_GATE
        work_id = "daio-work-zero-touch-001"
        work = DAIOWorkItem(
            work_id=work_id,
            project_root=str(tmp_path),
            change_id="CHANGE_ZERO_TOUCH",
            current_stage="S3_EXECUTION",
            current_gate=DAIOGate.HUMAN_GATE,
            assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
            requested_action="Execute automated feature",
            allowed_scope=["src/*", "tests/*"],
            base_sha="11112222",
            head_sha="11112222",
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
            attempt_count=0,
            max_attempts=3,
            human_gate_reason="Awaiting Project Owner Approval",
            authorized_next_phase=None,
            created_at=now_iso,
            updated_at=now_iso,
        )
        store.save_work_item(work)

        # 2. Prepare remote decision in relay buffer
        mock_client = MockRemoteDecisionRelayClient(project_id="awin-fintech")
        envelope = RemoteDecisionEnvelope(
            protocol_version="rpc-2.v1",
            decision_id="dec-remote-zt-100",
            project_id="awin-fintech",
            work_id=work_id,
            gate_id="HUMAN_GATE",
            decision="APPROVE",
            current_phase="S3_EXECUTION",
            next_phase=None,
            action="RUN",
            instruction="Approved via iPhone Face ID",
            issued_at=now_iso,
            expires_at=exp_iso,
            delivery_status=TransportDeliveryState.SUBMITTED,
            metadata={"auth": "WebAuthn_Passkey_FaceID"},
        )
        mock_client.pending_envelopes.append(envelope)

        # 3. Setup Supervisor with Mock Executor and Bridge
        remote_adapter = RemoteDecisionAdapter(project_id="awin-fintech", client=mock_client)
        executor = MockAutoResumeExecutor()
        bridge = MockArchitectBridgeAdapter()

        supervisor = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            executor=executor,
            bridge=bridge,
            remote_relay_adapter=remote_adapter,
            enable_remote_ingress=True,
        )

        # 4. Run supervisor tick (Simulates autonomous background daemon tick)
        tick_result = await supervisor.run_tick()

        # 5. Verify remote decision was detected and applied
        processed = tick_result.get("remote_decisions_processed", [])
        assert len(processed) == 1
        assert processed[0]["decision_id"] == "dec-remote-zt-100"
        assert processed[0]["applied"] is True
        assert processed[0]["status"] == "DECISION_APPLIED"

        # 6. Verify Cloudflare ACK was sent and queue cleared
        assert "dec-remote-zt-100" in mock_client.acknowledged_ids
        assert len(mock_client.pending_envelopes) == 0

        # 7. Verify work item was claimed and processed by worker unattended
        assert work_id in executor.executed_work_ids

        # 8. Verify SQLite final state
        updated_work = store.load_work_item(work_id)
        assert updated_work.last_decision == "APPROVE"
        assert updated_work.status in {DAIOStatus.AWAITING_REVIEW, DAIOStatus.COMPLETED, DAIOStatus.IN_PROGRESS}

    asyncio.run(_test())


def test_supervisor_remote_poller_network_failure_resilience(tmp_path):
    """Proves supervisor survives transport errors gracefully without crashing the daemon."""
    async def _test():
        store = SqliteDAIOWorkStore(str(tmp_path / "daio_work.db"))
        mock_client = MagicMock()
        mock_client.poll_decisions.side_effect = RuntimeError("Cloudflare Network Timeout 504")

        remote_adapter = RemoteDecisionAdapter(project_id="awin-fintech", client=mock_client)
        supervisor = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            remote_relay_adapter=remote_adapter,
        )

        # Must not raise exception
        tick_result = await supervisor.run_tick()
        assert tick_result["supervisor_id"] == supervisor.supervisor_id
        assert tick_result["remote_decisions_processed"] == []

    asyncio.run(_test())


def test_supervisor_clean_shutdown(tmp_path):
    """Proves supervisor stops cleanly and updates durable heartbeat."""
    store = SqliteDAIOWorkStore(str(tmp_path / "daio_work.db"))
    supervisor = DAIOSupervisor(
        project_root=str(tmp_path),
        store=store,
    )
    supervisor.stop()
    assert supervisor._running is False
    assert supervisor.worker._running is False
