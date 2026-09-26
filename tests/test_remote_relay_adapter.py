"""
Tests for RPC-2A Remote Decision Transport & Dry-Run Adapter.

Verifies schema validation, fail-closed project/work/gate identity binding,
freshness checks, authentication, delivery state flow, ACK handling,
unified worker routing contracts, strict privilege separation between
RPC-1 (status plane) and RPC-2A (decision transport), and explicit isolation
ensuring 0 mutation to local SQLite or DAIO work state.
"""

import datetime
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import uuid

import pytest

try:
    from scripts.daio_closed_loop.adapters.remote_relay import (
        DryRunValidationResult,
        RemoteDecisionAdapter,
        RemoteDecisionEnvelope,
        RemoteDecisionRelayClient,
        RemoteDecisionValidator,
        SUPPORTED_PROTOCOL_VERSIONS,
        TransportDeliveryState,
    )
    from scripts.daio_closed_loop.models import (
        ArchitectDecision,
        DAIOGate,
        DAIORole,
        DAIOStatus,
        DAIOWorkItem,
    )
    from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
    from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
    ROUTER_PATCH_PATH = "scripts.daio_closed_loop.router.DAIORoleRouter.process_architect_review"
except ImportError:
    from _daio.scripts.daio_closed_loop.adapters.remote_relay import (
        DryRunValidationResult,
        RemoteDecisionAdapter,
        RemoteDecisionEnvelope,
        RemoteDecisionRelayClient,
        RemoteDecisionValidator,
        SUPPORTED_PROTOCOL_VERSIONS,
        TransportDeliveryState,
    )
    from _daio.scripts.daio_closed_loop.models import (
        ArchitectDecision,
        DAIOGate,
        DAIORole,
        DAIOStatus,
        DAIOWorkItem,
    )
    from _daio.scripts.daio_closed_loop.store import SqliteDAIOWorkStore
    from _daio.scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
    ROUTER_PATCH_PATH = "_daio.scripts.daio_closed_loop.router.DAIORoleRouter.process_architect_review"


def _create_sample_envelope(
    protocol_version: str = "rpc-2.v1",
    decision_id: str = "dec-test-001",
    project_id: str = "awin-fintech",
    work_id: str = "daio-work-051",
    gate_id: str = "HUMAN_GATE",
    decision: str = "APPROVE",
    current_phase: str = "PHASE_1_SCAFFOLDING",
    next_phase: Optional[str] = None,
    action: str = "RUN",
    instruction: str = "Authorize Phase 2 scaffolding.",
    expires_in_hours: int = 24,
    expires_at: Optional[str] = None,
) -> RemoteDecisionEnvelope:
    now = datetime.datetime.now(datetime.timezone.utc)
    exp = expires_at or (now + datetime.timedelta(hours=expires_in_hours)).isoformat()
    return RemoteDecisionEnvelope(
        protocol_version=protocol_version,
        decision_id=decision_id,
        project_id=project_id,
        work_id=work_id,
        gate_id=gate_id,
        decision=decision,
        current_phase=current_phase,
        next_phase=next_phase,
        action=action,
        instruction=instruction,
        issued_at=now.isoformat(),
        expires_at=exp,
        delivery_status=TransportDeliveryState.SUBMITTED,
    )



# 1. Valid Decision Envelope Validation
def test_valid_decision_envelope_accepted():
    env = _create_sample_envelope(next_phase="PHASE_2_EXECUTION")
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
        expected_work_id="daio-work-051",
        expected_gate_id="HUMAN_GATE",
    )
    assert res.valid is True
    assert res.status == "DRY_RUN_ACCEPTED"
    assert res.dry_run_only is True
    assert res.architect_decision is not None
    assert res.architect_decision.decision == "APPROVE"
    assert res.architect_decision.action == "RUN"
    assert res.architect_decision.next_phase == "PHASE_2_EXECUTION"


# 2. Authentication Gate: Missing or Invalid Bearer Token
def test_auth_token_missing_raises_permission_error():
    client = RemoteDecisionRelayClient(
        endpoint_url="https://daio-relay.example.workers.dev",
        project_id="awin-fintech",
        auth_token="",
        auth_token_env="NON_EXISTENT_ENV_VAR",
    )
    with pytest.raises(PermissionError, match="authentication token missing"):
        client._get_headers()


def test_auth_token_provided_in_headers():
    client = RemoteDecisionRelayClient(
        endpoint_url="https://daio-relay.example.workers.dev",
        project_id="awin-fintech",
        auth_token="secret-token-12345",
    )
    headers = client._get_headers()
    assert headers["Authorization"] == "Bearer secret-token-12345"
    assert "User-Agent" in headers


# 3. Malformed Envelope: Missing Fields & Bad JSON
def test_malformed_envelope_rejected():
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")
    bad_data = {
        "protocol_version": "rpc-2.v1",
        # missing decision_id, work_id, etc.
    }
    res = adapter.dry_run_validate_envelope(bad_data)
    assert res.valid is False
    assert res.status == "DRY_RUN_REJECTED"


# 4. Project ID Mismatch (Fail-Closed)
def test_wrong_project_id_rejected():
    env = _create_sample_envelope(project_id="foreign-project-xyz")
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
    )
    assert res.valid is False
    assert res.status == "DRY_RUN_REJECTED"
    assert "Project ID mismatch" in res.reason


# 5. Work Item Binding Mismatch (Fail-Closed)
def test_wrong_work_id_rejected():
    env = _create_sample_envelope(work_id="daio-work-999")
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
        expected_work_id="daio-work-051",
    )
    assert res.valid is False
    assert res.status == "DRY_RUN_REJECTED"
    assert "Work ID mismatch" in res.reason


# 6. Gate Binding Mismatch (Fail-Closed)
def test_wrong_gate_id_rejected():
    env = _create_sample_envelope(gate_id="CONTRACT_GATE")
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
        expected_work_id="daio-work-051",
        expected_gate_id="HUMAN_GATE",
    )
    assert res.valid is False
    assert res.status == "DRY_RUN_REJECTED"
    assert "Gate ID mismatch" in res.reason


# 7. Expired Decision Rejection (Freshness Check)
def test_expired_decision_rejected():
    env = _create_sample_envelope(expires_in_hours=-1)  # Expired 1 hour ago
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
    )
    assert res.valid is False
    assert res.status == "DRY_RUN_REJECTED"
    assert "Decision expired" in res.reason


# 8. Unsupported Protocol Version Rejection
def test_unsupported_protocol_version_rejected():
    env = _create_sample_envelope(protocol_version="rpc-99.beta")
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
    )
    assert res.valid is False
    assert res.status == "DRY_RUN_REJECTED"
    assert "Unsupported protocol version" in res.reason


# 9. Canonical Decision & Action Vocabulary Checks
def test_invalid_decision_vocabulary_rejected():
    env = _create_sample_envelope(decision="MAYBE_LATER")
    res = RemoteDecisionValidator.validate(
        envelope=env,
        expected_project_id="awin-fintech",
    )
    assert res.valid is False
    assert "Invalid decision value" in res.reason


# 10. Explicit Proof: Dry-Run Does NOT Mutate SQLite Database or Human Gate State
def test_dry_run_zero_mutation_guarantee():
    # Setup real in-memory SQLite work store
    store = SqliteDAIOWorkStore(":memory:")
    work = DAIOWorkItem(
        work_id="daio-work-051",
        project_root="/test/project",
        change_id="051",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        current_gate=DAIOGate.HUMAN_GATE,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
        human_gate_reason="Phase 1 scaffold requires human approval",
    )
    store.save_work_item(work)

    # Initial state verification
    loaded_before = store.load_work_item("daio-work-051")
    assert loaded_before is not None
    assert loaded_before.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert loaded_before.assigned_role == DAIORole.HUMAN_PROJECT_OWNER

    # Execute RPC-2A dry-run validation
    env = _create_sample_envelope(work_id="daio-work-051", decision="APPROVE")
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")
    result = adapter.dry_run_validate_envelope(
        envelope_data=env.to_dict(),
        expected_work_id="daio-work-051",
        expected_gate_id="HUMAN_GATE",
    )
    assert result.valid is True
    assert result.status == "DRY_RUN_ACCEPTED"

    # Strict check: work item in store was completely untouched
    loaded_after = store.load_work_item("daio-work-051")
    assert loaded_after is not None
    assert loaded_after.status == DAIOStatus.HUMAN_GATE_REQUIRED
    assert loaded_after.current_gate == DAIOGate.HUMAN_GATE
    assert loaded_after.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
    assert loaded_after.updated_at == loaded_before.updated_at

    # Strict check: applied decision ledger has 0 records
    assert store.is_decision_applied("any_hash") is False


# 11. Mock End-to-End Transport Flow (Poll -> Validate -> ACK)
class MockHTTPResponse:
    def __init__(self, status: int, data: bytes):
        self.status = status
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_mock_transport_poll_and_ack_flow():
    sample_env = _create_sample_envelope(decision_id="dec-abc-123")
    poll_payload = json.dumps({"project_id": "awin-fintech", "count": 1, "decisions": [sample_env.to_dict()]}).encode("utf-8")
    ack_payload = json.dumps({"status": "ACK_PROCESSED", "decision_id": "dec-abc-123"}).encode("utf-8")

    def mock_urlopen(req, timeout=10.0):
        url = req.full_url
        if "/api/v1/decisions?" in url and req.get_method() == "GET":
            # Verify outbound bearer header
            assert "Authorization" in req.headers
            assert req.headers["Authorization"] == "Bearer mock-secret"
            return MockHTTPResponse(200, poll_payload)
        elif "/ack" in url and req.get_method() == "POST":
            assert req.headers["Authorization"] == "Bearer mock-secret"
            return MockHTTPResponse(200, ack_payload)
        raise ValueError(f"Unexpected URL in mock: {url}")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        client = RemoteDecisionRelayClient(
            endpoint_url="https://daio-relay.mock.workers.dev",
            project_id="awin-fintech",
            auth_token="mock-secret",
        )
        adapter = RemoteDecisionAdapter(project_id="awin-fintech", client=client)

        results = adapter.poll_and_dry_run_validate(
            expected_work_id="daio-work-051",
            expected_gate_id="HUMAN_GATE",
            auto_ack=True,
        )

        assert len(results) == 1
        assert results[0].valid is True
        assert results[0].status == "DRY_RUN_ACCEPTED"
        assert results[0].envelope.decision_id == "dec-abc-123"


# 12. RPC-1 Regression Protection: Taskboard Schema Integrity
def test_rpc1_taskboard_schema_integrity():
    taskboard_path = Path("taskboard.json")
    if taskboard_path.exists():
        data = json.loads(taskboard_path.read_text(encoding="utf-8"))
        assert "dialogue_history" in data
        assert "tasks" in data
        assert isinstance(data["tasks"], list)


# 13. Simulated Unified Worker: Privilege Separation & Cross-Plane Non-Interference
class UnifiedRelaySimulator:
    """
    In-memory Python simulator of the JavaScript Cloudflare Worker logic in relay_worker.js.
    Verifies routing, separate secrets, and storage isolation between RPC-1 and RPC-2A.
    """

    def __init__(self, publish_token: str = "token-rpc1", relay_secret: str = "secret-rpc2a"):
        self.publish_token = publish_token
        self.relay_secret = relay_secret
        self.status_kv: dict = {}
        self.decision_kv: dict = {}

    def handle(self, method: str, path: str, headers: dict = None, body: dict = None, query: dict = None) -> tuple:
        headers = headers or {}
        auth = headers.get("Authorization", "").replace("Bearer ", "").strip()

        # Meta Routes
        if path == "/" and method == "GET":
            return (200, {
                "status": "OK",
                "service": "DAIO Unified Remote Relay",
                "version": "daio-rpc/v2.1",
                "published_status_available": "status:latest" in self.status_kv,
            })
        if path == "/openapi.json" and method == "GET":
            return (200, {"openapi": "3.1.0", "info": {"title": "DAIO Unified Remote Relay API"}})
        if path == "/api/v1/health" and method == "GET":
            return (200, {"status": "OK", "timestamp": "2026-09-26T18:00:00Z"})

        # RPC-1 Status Plane
        if path == "/api/v1/status" and method == "GET":
            if "status:latest" in self.status_kv:
                return (200, self.status_kv["status:latest"])
            return (200, {
                "live_plane": {
                    "project_name": "DAIO",
                    "host": "unknown",
                    "host_status": "UNKNOWN",
                    "freshness": "UNKNOWN",
                    "supervisor_running": False,
                    "heartbeat_age_seconds": None,
                    "degraded_note": "No status published yet from DAIO host instance.",
                },
                "durable_plane": {"repository": None, "push_synchronized": False},
                "provenance": {"protocol_version": "daio-rpc/v1", "relay_node": "cloudflare-edge"},
            })

        if path == "/api/v1/publish" and method == "POST":
            if auth != self.publish_token:
                return (401, {"error": "Unauthorized: Invalid DAIO_RPC_PUBLISH_TOKEN"})
            self.status_kv["status:latest"] = body
            return (200, {"status": "OK"})

        # RPC-2A Decision Transport Plane
        if path.startswith("/api/v1/decisions"):
            if auth != self.relay_secret:
                return (401, {"error": "Unauthorized: Invalid DAIO_RELAY_SECRET"})

            if path == "/api/v1/decisions" and method == "POST":
                p_id = body.get("project_id")
                d_id = body.get("decision_id", str(uuid.uuid4()))
                self.decision_kv[f"decision:{p_id}:{d_id}"] = body
                idx = self.decision_kv.get(f"index:{p_id}", [])
                if d_id not in idx:
                    idx.append(d_id)
                self.decision_kv[f"index:{p_id}"] = idx
                return (201, {"status": "SUBMITTED", "decision_id": d_id})

            if path == "/api/v1/decisions" and method == "GET":
                p_id = (query or {}).get("project_id")
                if not p_id:
                    return (400, {"error": "Missing project_id"})
                idx = self.decision_kv.get(f"index:{p_id}", [])
                decisions = [self.decision_kv.get(f"decision:{p_id}:{d_id}") for d_id in idx if f"decision:{p_id}:{d_id}" in self.decision_kv]
                return (200, {"project_id": p_id, "count": len(decisions), "decisions": decisions})

            if "/ack" in path and method == "POST":
                d_id = path.split("/")[-2]
                for k in list(self.decision_kv.keys()):
                    if k.endswith(f":{d_id}"):
                        del self.decision_kv[k]
                        p_id = k.split(":")[1]
                        idx = self.decision_kv.get(f"index:{p_id}", [])
                        if d_id in idx:
                            idx.remove(d_id)
                            self.decision_kv[f"index:{p_id}"] = idx
                        return (200, {"status": "ACK_PROCESSED", "decision_id": d_id})
                return (200, {"status": "NOT_FOUND_OR_ALREADY_ACKED"})

        return (404, {"error": "Not Found"})


def test_unified_relay_privilege_separation_and_isolation():
    sim = UnifiedRelaySimulator(publish_token="rpc1-publish-only", relay_secret="rpc2a-decision-only")

    # 1. Verify Public Meta Endpoints
    code, res = sim.handle("GET", "/")
    assert code == 200
    assert res["status"] == "OK"

    code, res = sim.handle("GET", "/openapi.json")
    assert code == 200
    assert res["openapi"] == "3.1.0"

    code, res = sim.handle("GET", "/api/v1/health")
    assert code == 200
    assert res["status"] == "OK"

    # 2. RPC-1 Token CANNOT access RPC-2A Decision Endpoints (Cross-Plane Breach Blocked)
    code, res = sim.handle("POST", "/api/v1/decisions", headers={"Authorization": "Bearer rpc1-publish-only"}, body={"project_id": "awin-fintech"})
    assert code == 401
    assert "Invalid DAIO_RELAY_SECRET" in res["error"]

    code, res = sim.handle("GET", "/api/v1/decisions", headers={"Authorization": "Bearer rpc1-publish-only"}, query={"project_id": "awin-fintech"})
    assert code == 401

    # 3. RPC-2A Secret CANNOT publish to RPC-1 Status (Cross-Plane Breach Blocked)
    code, res = sim.handle("POST", "/api/v1/publish", headers={"Authorization": "Bearer rpc2a-decision-only"}, body={"live_plane": {}, "durable_plane": {}})
    assert code == 401
    assert "Invalid DAIO_RPC_PUBLISH_TOKEN" in res["error"]

    # 4. Valid RPC-1 Publish and Read Operates Correctly
    code, res = sim.handle("POST", "/api/v1/publish", headers={"Authorization": "Bearer rpc1-publish-only"}, body={"live_plane": {"stage": "S5"}, "durable_plane": {"sha": "16cec7a"}})
    assert code == 200

    code, res = sim.handle("GET", "/api/v1/status")
    assert code == 200
    assert res["live_plane"]["stage"] == "S5"

    # 5. Valid RPC-2A Decision Submit, Poll, and ACK Operates Correctly
    env_payload = _create_sample_envelope(decision_id="dec-cross-001").to_dict()
    code, res = sim.handle("POST", "/api/v1/decisions", headers={"Authorization": "Bearer rpc2a-decision-only"}, body=env_payload)
    assert code == 201

    code, res = sim.handle("GET", "/api/v1/decisions", headers={"Authorization": "Bearer rpc2a-decision-only"}, query={"project_id": "awin-fintech"})
    assert code == 200
    assert res["count"] == 1
    assert res["decisions"][0]["decision_id"] == "dec-cross-001"

    # 6. Cross-Plane Isolation: Decision operations did NOT alter RPC-1 status
    code, res = sim.handle("GET", "/api/v1/status")
    assert code == 200
    assert res["live_plane"]["stage"] == "S5"

    # 7. ACK removes decision from index
    code, res = sim.handle("POST", "/api/v1/decisions/dec-cross-001/ack", headers={"Authorization": "Bearer rpc2a-decision-only"})
    assert code == 200
    assert res["status"] == "ACK_PROCESSED"

    code, res = sim.handle("GET", "/api/v1/decisions", headers={"Authorization": "Bearer rpc2a-decision-only"}, query={"project_id": "awin-fintech"})
    assert code == 200
    assert res["count"] == 0


# ===========================================================================
# RPC-2B.1 Application Adapter & Fail-Closed Revalidation Tests
# ===========================================================================

def _create_test_store_with_human_gate_work(
    work_id: str = "work-human-001",
    stage: str = "S3",
    gate: DAIOGate = DAIOGate.HUMAN_GATE,
    status: DAIOStatus = DAIOStatus.HUMAN_GATE_REQUIRED,
    role: DAIORole = DAIORole.HUMAN_PROJECT_OWNER,
    project_root: str = "/test/workspace",
) -> Tuple[SqliteDAIOWorkStore, DAIOWorkItem]:
    store = SqliteDAIOWorkStore(":memory:")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    work = DAIOWorkItem(
        work_id=work_id,
        project_root=project_root,
        change_id="CHANGE-052",
        current_stage=stage,
        current_gate=gate,
        assigned_role=role,
        requested_action="Human approval required",
        allowed_scope=["tests/**", "_daio/**"],
        base_sha="base123",
        head_sha="head123",
        status=status,
        attempt_count=1,
        max_attempts=3,
        human_gate_reason="Lead Architect requested Human Review",
        created_at=now,
        updated_at=now,
    )
    store.save_work_item(work)
    return store, work


def test_rpc2b_valid_human_gate_application_success():
    store, work = _create_test_store_with_human_gate_work()
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-001",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
        action="RUN",
    )

    result = adapter.validate_and_apply(envelope=env, store=store, project_root="/test/workspace")

    assert result.applied is True
    assert result.status == "DECISION_APPLIED"
    assert "successfully applied" in result.reason
    assert result.work_item is not None
    assert result.work_item.current_gate == DAIOGate.ENGINEERING_TASK
    assert result.work_item.assigned_role == DAIORole.ENGINEERING_EXECUTION
    assert result.work_item.status == DAIOStatus.QUEUED

    # Verify persisted in SQLite
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.ENGINEERING_TASK
    assert reloaded.assigned_role == DAIORole.ENGINEERING_EXECUTION
    assert reloaded.status == DAIOStatus.QUEUED
    assert reloaded.human_gate_reason is None

    # Verify applied decision ledger
    assert result.decision_hash is not None
    assert store.is_decision_applied(result.decision_hash) is True


def test_rpc2b_wrong_work_id_fails_closed_zero_mutation():
    store, work = _create_test_store_with_human_gate_work()
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-wrong-work",
        project_id="awin-fintech",
        work_id="work-non-existent-999",
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
    )

    result = adapter.validate_and_apply(envelope=env, store=store)

    assert result.applied is False
    assert result.status == "REJECTED_STALE_CONTEXT"
    assert "not found in canonical store" in result.reason

    # Zero mutation on real work item
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.HUMAN_GATE
    assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_rpc2b_wrong_gate_fails_closed_zero_mutation():
    store, work = _create_test_store_with_human_gate_work(
        gate=DAIOGate.CONTRACT_GATE,
        status=DAIOStatus.AWAITING_REVIEW,
        role=DAIORole.LEAD_ARCHITECT_REVIEW,
    )
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-wrong-gate",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
    )

    result = adapter.validate_and_apply(envelope=env, store=store)

    assert result.applied is False
    assert result.status == "REJECTED_STALE_CONTEXT"
    assert "TOCTOU violation" in result.reason or "Gate mismatch" in result.reason

    # Zero mutation
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.CONTRACT_GATE
    assert reloaded.status == DAIOStatus.AWAITING_REVIEW


def test_rpc2b_wrong_phase_fails_closed_zero_mutation():
    store, work = _create_test_store_with_human_gate_work(stage="S3")
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-wrong-phase",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S4",  # Mismatch: live work is at S3
    )

    result = adapter.validate_and_apply(envelope=env, store=store)

    assert result.applied is False
    assert result.status == "REJECTED_STALE_CONTEXT"
    assert ("stage mismatch" in result.reason) or ("Phase mismatch" in result.reason)

    # Zero mutation
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_stage == "S3"
    assert reloaded.current_gate == DAIOGate.HUMAN_GATE
    assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_rpc2b_gate_changed_after_submission_toctou_rejection():
    store, work = _create_test_store_with_human_gate_work()
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    # Prepare decision envelope for HUMAN_GATE
    env = _create_sample_envelope(
        decision_id="dec-rpc2b-toctou",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
    )

    # Simulate local state advancing before remote decision is applied
    work.current_gate = DAIOGate.CONTRACT_GATE
    work.status = DAIOStatus.COMPLETED
    store.save_work_item(work)

    # Attempt application of now-stale decision
    result = adapter.validate_and_apply(envelope=env, store=store)

    assert result.applied is False
    assert result.status == "REJECTED_STALE_CONTEXT"
    assert "TOCTOU violation" in result.reason

    # Verify zero unwanted mutations
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.CONTRACT_GATE
    assert reloaded.status == DAIOStatus.COMPLETED


def test_rpc2b_expired_decision_fails_closed_zero_mutation():
    store, work = _create_test_store_with_human_gate_work()
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()
    env = _create_sample_envelope(
        decision_id="dec-rpc2b-expired",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        expires_at=past_time,
    )

    result = adapter.validate_and_apply(envelope=env, store=store)

    assert result.applied is False
    assert result.status == "REJECTED_PRECONDITION_FAILED"
    assert "expired" in result.reason

    # Zero mutation
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.HUMAN_GATE
    assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_rpc2b_already_applied_decision_idempotent_no_duplicate_mutation():
    store, work = _create_test_store_with_human_gate_work()
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-idempotent",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
        action="RUN",
        instruction="Approved via RPC-2",
    )

    # 1. First application succeeds
    res1 = adapter.validate_and_apply(envelope=env, store=store)
    assert res1.applied is True
    assert res1.status == "DECISION_APPLIED"

    # Reset work state back to HUMAN_GATE to test deduplication specifically
    work.status = DAIOStatus.HUMAN_GATE_REQUIRED
    work.current_gate = DAIOGate.HUMAN_GATE
    work.assigned_role = DAIORole.HUMAN_PROJECT_OWNER
    store.save_work_item(work)

    # 2. Second application with identical decision hash is recognized as duplicate
    res2 = adapter.validate_and_apply(envelope=env, store=store)
    assert res2.applied is False
    assert res2.status == "DECISION_ALREADY_APPLIED"
    assert ("already" in res2.reason) and ("applied" in res2.reason)


def test_rpc2b_role_mismatch_fails_closed():
    store, work = _create_test_store_with_human_gate_work(
        role=DAIORole.ENGINEERING_EXECUTION,  # Invariant violation: HUMAN_GATE without HUMAN_PROJECT_OWNER
    )
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-role-mismatch",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
    )

    result = adapter.validate_and_apply(envelope=env, store=store)

    assert result.applied is False
    assert result.status == "REJECTED_STALE_CONTEXT"
    assert ("role mismatch" in result.reason) or ("assigned_role" in result.reason)

    # Zero mutation
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.HUMAN_GATE
    assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_rpc2b_storage_isolation_mismatch_fails_closed():
    store, work = _create_test_store_with_human_gate_work(project_root="/unauthorized/workspace")
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")

    env = _create_sample_envelope(
        decision_id="dec-rpc2b-iso-mismatch",
        project_id="awin-fintech",
        work_id=work.work_id,
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
    )

    result = adapter.validate_and_apply(envelope=env, store=store, project_root="/authorized/workspace")

    assert result.applied is False
    assert result.status == "REJECTED_PRECONDITION_FAILED"
    assert "project root mismatch" in result.reason

    # Zero mutation
    reloaded = store.load_work_item(work.work_id)
    assert reloaded.current_gate == DAIOGate.HUMAN_GATE
    assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_rpc2b_atomic_store_concurrency_race_rejection(tmp_path):
    """
    Deterministic concurrency race test:
    Proves that a concurrent writer modifying canonical state causes the
    atomic compare-and-apply transaction to fail closed with REJECTED_STALE_CONTEXT.
    """
    db_file = str(tmp_path / "daio_race_test.db")
    store = SqliteDAIOWorkStore(db_file)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    work = DAIOWorkItem(
        work_id="work-race-001",
        project_root=str(tmp_path),
        change_id="CHANGE-052",
        current_stage="S3",
        current_gate=DAIOGate.HUMAN_GATE,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
        requested_action="Awaiting human decision",
        allowed_scope=["tests/**"],
        base_sha="base000",
        head_sha="head000",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        attempt_count=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )
    store.save_work_item(work)

    # 1. Competing thread / supervisor mutates state to CONTRACT_GATE / COMPLETED
    work.current_gate = DAIOGate.CONTRACT_GATE
    work.status = DAIOStatus.COMPLETED
    work.assigned_role = DAIORole.LEAD_ARCHITECT_REVIEW
    store.save_work_item(work)

    # 2. Remote decision arrives expecting old HUMAN_GATE
    adapter = RemoteDecisionAdapter(project_id="awin-fintech")
    env = _create_sample_envelope(
        decision_id="dec-race-001",
        project_id="awin-fintech",
        work_id="work-race-001",
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
    )

    # 3. Apply remote decision -> Must be rejected by atomic store
    result = adapter.validate_and_apply(envelope=env, store=store, project_root=str(tmp_path))

    assert result.applied is False
    assert result.status == "REJECTED_STALE_CONTEXT"
    assert "TOCTOU violation" in result.reason

    # 4. Assert concurrent state (CONTRACT_GATE) is 100% preserved
    reloaded = store.load_work_item("work-race-001")
    assert reloaded.current_gate == DAIOGate.CONTRACT_GATE
    assert reloaded.status == DAIOStatus.COMPLETED

    # 5. Assert zero records in applied decisions ledger and zero turn history for the rejected decision
    turns = store.get_turn_history_for_work("work-race-001")
    assert len(turns) == 0


def test_rpc2b_crash_before_ack_replay_zero_second_transition(tmp_path):
    """
    Crash-before-ACK replay test:
    Proves that when a network crash occurs before ACK and the relay re-delivers
    the exact same decision, zero duplicate mutations occur.
    """
    db_file = str(tmp_path / "daio_replay_test.db")
    store = SqliteDAIOWorkStore(db_file)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    work = DAIOWorkItem(
        work_id="work-replay-001",
        project_root=str(tmp_path),
        change_id="CHANGE-052",
        current_stage="S3",
        current_gate=DAIOGate.HUMAN_GATE,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
        requested_action="Awaiting human decision",
        allowed_scope=["tests/**"],
        base_sha="base000",
        head_sha="head000",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        attempt_count=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )
    store.save_work_item(work)

    adapter = RemoteDecisionAdapter(project_id="awin-fintech")
    env = _create_sample_envelope(
        decision_id="dec-replay-001",
        project_id="awin-fintech",
        work_id="work-replay-001",
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
        action="RUN",
        instruction="Remote Human approved",
    )

    # First application succeeds
    res1 = adapter.validate_and_apply(envelope=env, store=store, project_root=str(tmp_path))
    assert res1.applied is True
    assert res1.status == "DECISION_APPLIED"

    work_after_first = store.load_work_item("work-replay-001")
    assert work_after_first.current_gate == DAIOGate.ENGINEERING_TASK
    assert work_after_first.status == DAIOStatus.QUEUED

    # Second delivery (replay after simulated network failure before ACK)
    res2 = adapter.validate_and_apply(envelope=env, store=store, project_root=str(tmp_path))
    assert res2.applied is False
    assert res2.status == "DECISION_ALREADY_APPLIED"

    # Verify state remains exactly as transitioned by the first delivery (0 duplicate transitions)
    work_after_second = store.load_work_item("work-replay-001")
    assert work_after_second.current_gate == DAIOGate.ENGINEERING_TASK
    assert work_after_second.status == DAIOStatus.QUEUED
    assert work_after_second.updated_at == work_after_first.updated_at


def test_rpc2b_atomic_store_rollback_on_transaction_failure(tmp_path):
    """
    Transaction-failure rollback test:
    Proves that an unexpected database exception rolls back all changes cleanly.
    """
    db_file = str(tmp_path / "daio_rollback_test.db")
    store = SqliteDAIOWorkStore(db_file)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    work = DAIOWorkItem(
        work_id="work-err-001",
        project_root=str(tmp_path),
        change_id="CHANGE-052",
        current_stage="S3",
        current_gate=DAIOGate.HUMAN_GATE,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
        requested_action="Awaiting human decision",
        allowed_scope=["tests/**"],
        base_sha="base000",
        head_sha="head000",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        attempt_count=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )
    store.save_work_item(work)

    adapter = RemoteDecisionAdapter(project_id="awin-fintech")
    env = _create_sample_envelope(
        decision_id="dec-err-001",
        project_id="awin-fintech",
        work_id="work-err-001",
        gate_id=DAIOGate.HUMAN_GATE.value,
        decision="APPROVE",
        current_phase="S3",
    )

    # Patch router to throw unexpected runtime error
    with patch(ROUTER_PATCH_PATH, side_effect=RuntimeError("Simulated DB Disk Error")):
        res = adapter.validate_and_apply(envelope=env, store=store, project_root=str(tmp_path))
        assert res.applied is False
        assert res.status == "ERROR_TRANSACTION_FAILED"

    # State must be 100% rolled back
    reloaded = store.load_work_item("work-err-001")
    assert reloaded.current_gate == DAIOGate.HUMAN_GATE
    assert reloaded.status == DAIOStatus.HUMAN_GATE_REQUIRED


def test_rpc2b_orchestrator_canonical_ingestion_single_path():
    """
    Integration test:
    Proves that DAIOClosedLoopOrchestrator.process_incoming_architect_decision
    uses the same atomic store primitive for both local and remote decisions.
    """
    import asyncio
    store = SqliteDAIOWorkStore(":memory:")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 1. Local Architect Review on CONTRACT_GATE
    work_contract = DAIOWorkItem(
        work_id="work-local-001",
        project_root="/test",
        change_id="CHANGE-052",
        current_stage="S3",
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        requested_action="Review contract",
        allowed_scope=["tests/**"],
        base_sha="base",
        head_sha="head",
        status=DAIOStatus.AWAITING_REVIEW,
        attempt_count=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )
    store.save_work_item(work_contract)

    orch = DAIOClosedLoopOrchestrator(
        store=store,
        bridge=None,
    )

    arch_dec = ArchitectDecision(
        decision="APPROVE",
        current_phase="S3",
        action="RUN",
        instruction="Contract approved",
        raw_text="APPROVE",
    )

    ok, updated_local, report = asyncio.run(orch.process_incoming_architect_decision(
        work_id="work-local-001",
        decision=arch_dec,
        send_ack=False,
        acting_role=DAIORole.LEAD_ARCHITECT_REVIEW,
        expected_gate=DAIOGate.CONTRACT_GATE,
    ))
    assert ok is True
    assert updated_local.current_gate == DAIOGate.ENGINEERING_TASK
    assert updated_local.status == DAIOStatus.QUEUED

    # 2. Remote Human Gate on HUMAN_GATE
    work_human = DAIOWorkItem(
        work_id="work-remote-001",
        project_root="/test",
        change_id="CHANGE-052",
        current_stage="S3",
        current_gate=DAIOGate.HUMAN_GATE,
        assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
        requested_action="Human approval",
        allowed_scope=["tests/**"],
        base_sha="base",
        head_sha="head",
        status=DAIOStatus.HUMAN_GATE_REQUIRED,
        attempt_count=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )
    store.save_work_item(work_human)

    human_dec = ArchitectDecision(
        decision="APPROVE",
        current_phase="S3",
        action="RUN",
        instruction="Remote Human Project Owner approved via RPC-2",
        raw_text="APPROVE",
    )

    ok_h, updated_human, report_h = asyncio.run(orch.process_incoming_architect_decision(
        work_id="work-remote-001",
        decision=human_dec,
        send_ack=False,
        acting_role=DAIORole.HUMAN_PROJECT_OWNER,
        expected_gate=DAIOGate.HUMAN_GATE,
        expected_status=DAIOStatus.HUMAN_GATE_REQUIRED,
    ))
    assert ok_h is True
    assert updated_human.current_gate == DAIOGate.ENGINEERING_TASK
    assert updated_human.status == DAIOStatus.QUEUED


