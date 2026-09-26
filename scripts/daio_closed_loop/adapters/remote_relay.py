"""
RPC-2A Remote Decision Transport & Dry-Run Adapter.

This module provides the outbound-only remote decision transport client and validator
that connects local Mac DAIO to the Cloudflare Decision Relay buffer without mutating
any local SQLite state or Human Gate state machines during dry-run validation.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ..models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    is_terminal_phase,
    validate_work_item_isolation,
)
from ..router import DAIORoleRouter
from ..store import DAIOWorkStore

logger = logging.getLogger("DAIO_Remote_Relay")

SUPPORTED_PROTOCOL_VERSIONS = {"rpc-2.v1", "2026-09-26.v1"}
VALID_DECISIONS = {"APPROVE", "REVISE", "REJECT", "HOLD", "STOP", "HUMAN_REVIEW"}
VALID_ACTIONS = {"RUN", "HOLD", "STOP"}


class TransportDeliveryState:
    SUBMITTED = "SUBMITTED"
    DELIVERED = "DELIVERED"
    DRY_RUN_VALIDATED = "DRY_RUN_VALIDATED"
    DECISION_APPLIED = "DECISION_APPLIED"
    REJECTED_STALE_CONTEXT = "REJECTED_STALE_CONTEXT"
    REJECTED_PRECONDITION_FAILED = "REJECTED_PRECONDITION_FAILED"
    DECISION_ALREADY_APPLIED = "DECISION_ALREADY_APPLIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


@dataclass
class RemoteApplicationResult:
    applied: bool
    status: str  # "DECISION_APPLIED", "REJECTED_STALE_CONTEXT", "REJECTED_PRECONDITION_FAILED", "DECISION_ALREADY_APPLIED", "DRY_RUN_ACCEPTED"
    reason: str
    work_item: Optional[DAIOWorkItem] = None
    decision_hash: Optional[str] = None
    envelope: Optional[RemoteDecisionEnvelope] = None


@dataclass
class RemoteDecisionEnvelope:
    protocol_version: str
    decision_id: str
    project_id: str
    work_id: str
    gate_id: str
    decision: str
    current_phase: str
    issued_at: str
    expires_at: str
    next_phase: Optional[str] = None
    action: str = "RUN"
    instruction: str = ""
    delivery_status: str = TransportDeliveryState.SUBMITTED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RemoteDecisionEnvelope:
        return cls(
            protocol_version=str(data.get("protocol_version", "")),
            decision_id=str(data.get("decision_id", "")),
            project_id=str(data.get("project_id", "")),
            work_id=str(data.get("work_id", "")),
            gate_id=str(data.get("gate_id", "")),
            decision=str(data.get("decision", "")).upper(),
            current_phase=str(data.get("current_phase", "")),
            issued_at=str(data.get("issued_at", "")),
            expires_at=str(data.get("expires_at", "")),
            next_phase=data.get("next_phase"),
            action=str(data.get("action", "RUN")).upper(),
            instruction=str(data.get("instruction", "")),
            delivery_status=str(data.get("delivery_status", TransportDeliveryState.SUBMITTED)),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DryRunValidationResult:
    valid: bool
    status: str  # "DRY_RUN_ACCEPTED" or "DRY_RUN_REJECTED"
    reason: str
    envelope: Optional[RemoteDecisionEnvelope] = None
    architect_decision: Optional[ArchitectDecision] = None
    dry_run_only: bool = True


class RemoteDecisionValidator:
    """
    Strict, pure-function validator for RemoteDecisionEnvelope.
    Zero side-effects; never mutates local state or database records.
    """

    @staticmethod
    def validate(
        envelope: RemoteDecisionEnvelope,
        expected_project_id: str,
        expected_work_id: Optional[str] = None,
        expected_gate_id: Optional[str] = None,
        now: Optional[datetime.datetime] = None,
    ) -> DryRunValidationResult:
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)

        # 1. Protocol Version
        if envelope.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Unsupported protocol version '{envelope.protocol_version}'. Supported: {sorted(list(SUPPORTED_PROTOCOL_VERSIONS))}",
                envelope=envelope,
            )

        # 2. Decision ID
        if not envelope.decision_id or len(envelope.decision_id.strip()) < 4:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason="Missing or malformed 'decision_id'",
                envelope=envelope,
            )

        # 3. Project Identity Mapping (Fail-closed)
        if not envelope.project_id or envelope.project_id.strip() != expected_project_id.strip():
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Project ID mismatch. Expected '{expected_project_id}', got '{envelope.project_id}'",
                envelope=envelope,
            )

        # 4. Work Item Binding (Fail-closed if expected_work_id provided)
        if expected_work_id and envelope.work_id.strip() != expected_work_id.strip():
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Work ID mismatch. Expected '{expected_work_id}', got '{envelope.work_id}'",
                envelope=envelope,
            )

        # 5. Gate Binding (Fail-closed if expected_gate_id provided)
        if expected_gate_id and envelope.gate_id.strip() != expected_gate_id.strip():
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Gate ID mismatch. Expected '{expected_gate_id}', got '{envelope.gate_id}'",
                envelope=envelope,
            )

        # 6. Canonical Decision Vocabulary
        if envelope.decision not in VALID_DECISIONS:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Invalid decision value '{envelope.decision}'. Valid: {sorted(list(VALID_DECISIONS))}",
                envelope=envelope,
            )

        # 7. Action Vocabulary
        if envelope.action not in VALID_ACTIONS:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Invalid action value '{envelope.action}'. Valid: {sorted(list(VALID_ACTIONS))}",
                envelope=envelope,
            )

        # 8. Timestamp & Freshness / Expiration
        try:
            exp_time = datetime.datetime.fromisoformat(envelope.expires_at.replace("Z", "+00:00"))
            if exp_time.tzinfo is None:
                exp_time = exp_time.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Malformed 'expires_at' timestamp: '{envelope.expires_at}'",
                envelope=envelope,
            )

        if now > exp_time:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Decision expired at {envelope.expires_at} (current time: {now.isoformat()})",
                envelope=envelope,
            )

        # 9. Map to DAIO Canonical ArchitectDecision (dry-run preparation only)
        arch_dec = ArchitectDecision(
            decision=envelope.decision,
            current_phase=envelope.current_phase,
            next_phase=envelope.next_phase,
            action=envelope.action,
            human_approval_required=False,
            instruction=envelope.instruction,
            raw_text=json.dumps(envelope.to_dict()),
        )

        return DryRunValidationResult(
            valid=True,
            status="DRY_RUN_ACCEPTED",
            reason="Decision envelope strictly matches schema, identity, and freshness gates.",
            envelope=envelope,
            architect_decision=arch_dec,
            dry_run_only=True,
        )


class RemoteDecisionRelayClient:
    """
    Outbound-only HTTP client communicating with Cloudflare Decision Relay.
    Never opens inbound listening ports on the Mac.
    """

    def __init__(
        self,
        endpoint_url: str,
        project_id: str,
        auth_token: Optional[str] = None,
        auth_token_env: str = "DAIO_RELAY_TOKEN",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.project_id = project_id
        self.auth_token = auth_token or os.environ.get(auth_token_env, "")
        self.timeout_seconds = timeout_seconds

    def _get_headers(self) -> Dict[str, str]:
        if not self.auth_token:
            raise PermissionError("DAIO Remote Relay authentication token missing. Configure DAIO_RELAY_TOKEN environment variable.")
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "User-Agent": "DAIO-Mac-RemoteRelayClient/2.1 (RPC-2A Outbound)",
        }

    def poll_decisions(self, work_id: Optional[str] = None) -> List[RemoteDecisionEnvelope]:
        """
        Poll pending unacknowledged decisions for this project from Cloudflare Relay.
        """
        params = {"project_id": self.project_id}
        if work_id:
            params["work_id"] = work_id
        query = urllib.parse.urlencode(params)
        url = f"{self.endpoint_url}/api/v1/decisions?{query}"

        req = urllib.request.Request(url, headers=self._get_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status != 200:
                    logger.error(f"Cloudflare Relay poll returned HTTP {resp.status}")
                    return []
                payload = json.loads(resp.read().decode("utf-8"))
                decisions = payload.get("decisions", [])
                return [RemoteDecisionEnvelope.from_dict(d) for d in decisions]
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PermissionError("Cloudflare Relay authentication failed (HTTP 401 Unauthorized)")
            logger.warning(f"Relay poll HTTPError: {e}")
            return []
        except Exception as ex:
            logger.warning(f"Relay poll network exception: {ex}")
            return []

    def submit_decision(self, envelope: RemoteDecisionEnvelope) -> bool:
        """
        Test / client helper to submit an authenticated decision to Cloudflare Relay.
        """
        url = f"{self.endpoint_url}/api/v1/decisions"
        body = json.dumps(envelope.to_dict()).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=self._get_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.status in (200, 201)
        except Exception as ex:
            logger.error(f"Relay submit exception: {ex}")
            return False

    def acknowledge_decision(self, decision_id: str, status: str = TransportDeliveryState.DRY_RUN_VALIDATED) -> bool:
        """
        Acknowledge delivery / dry-run processing back to Cloudflare Relay.
        """
        url = f"{self.endpoint_url}/api/v1/decisions/{decision_id}/ack"
        body = json.dumps({"status": status, "acknowledged_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=self._get_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.status == 200
        except Exception as ex:
            logger.error(f"Relay acknowledge exception: {ex}")
            return False


class RemoteDecisionAdapter:
    """
    RPC-2A Remote Decision Adapter.
    Orchestrates outbound polling, envelope validation, and dry-run reporting.
    Guarantees 0 mutations to local database or Human Gate state.
    """

    def __init__(
        self,
        project_id: str,
        client: Optional[RemoteDecisionRelayClient] = None,
    ) -> None:
        self.project_id = project_id
        self.client = client

    def dry_run_validate_envelope(
        self,
        envelope_data: Dict[str, Any],
        expected_work_id: Optional[str] = None,
        expected_gate_id: Optional[str] = None,
    ) -> DryRunValidationResult:
        """
        Pure validation of raw envelope data without external network or local DB dependency.
        """
        try:
            envelope = RemoteDecisionEnvelope.from_dict(envelope_data)
        except Exception as ex:
            return DryRunValidationResult(
                valid=False,
                status="DRY_RUN_REJECTED",
                reason=f"Malformed envelope JSON structure: {ex}",
            )
        return RemoteDecisionValidator.validate(
            envelope=envelope,
            expected_project_id=self.project_id,
            expected_work_id=expected_work_id,
            expected_gate_id=expected_gate_id,
        )

    def poll_and_dry_run_validate(
        self,
        expected_work_id: Optional[str] = None,
        expected_gate_id: Optional[str] = None,
        auto_ack: bool = True,
    ) -> List[DryRunValidationResult]:
        """
        Polls remote relay, validates any available envelopes in DRY-RUN mode,
        and optionally sends DRY_RUN_VALIDATED ACK.
        NEVER calls process_incoming_architect_decision().
        """
        if not self.client:
            logger.warning("No RemoteDecisionRelayClient configured.")
            return []

        envelopes = self.client.poll_decisions(work_id=expected_work_id)
        results: List[DryRunValidationResult] = []

        for env in envelopes:
            val_res = RemoteDecisionValidator.validate(
                envelope=env,
                expected_project_id=self.project_id,
                expected_work_id=expected_work_id,
                expected_gate_id=expected_gate_id,
            )
            results.append(val_res)
            logger.info(f"🔍 RPC-2A Dry-Run Result for decision [{env.decision_id}]: {val_res.status} ({val_res.reason})")

            if auto_ack and val_res.valid:
                self.client.acknowledge_decision(
                    decision_id=env.decision_id,
                    status=TransportDeliveryState.DRY_RUN_VALIDATED,
                )

        return results

    def validate_and_apply(
        self,
        envelope: RemoteDecisionEnvelope,
        store: DAIOWorkStore,
        project_root: Optional[str] = None,
        send_ack: bool = True,
    ) -> RemoteApplicationResult:
        """
        RPC-2B: Authoritatively validates remote envelope and delegates to the canonical
        atomic compare-and-apply engine in SqliteDAIOWorkStore.
        Strict fail-closed checks against TOCTOU, context drift, stale gate, and replay.
        """
        # 1. Pure envelope validation first
        val_res = RemoteDecisionValidator.validate(
            envelope=envelope,
            expected_project_id=self.project_id,
        )
        if not val_res.valid:
            if send_ack and self.client:
                self.client.acknowledge_decision(
                    decision_id=envelope.decision_id,
                    status=TransportDeliveryState.REJECTED_PRECONDITION_FAILED,
                )
            return RemoteApplicationResult(
                applied=False,
                status="REJECTED_PRECONDITION_FAILED",
                reason=val_res.reason,
                envelope=envelope,
            )

        # 2. Storage isolation pre-check if project_root specified
        if project_root:
            live_check = store.load_work_item(envelope.work_id)
            if live_check and not validate_work_item_isolation(live_check, project_root):
                if send_ack and self.client:
                    self.client.acknowledge_decision(
                        decision_id=envelope.decision_id,
                        status=TransportDeliveryState.REJECTED_PRECONDITION_FAILED,
                    )
                return RemoteApplicationResult(
                    applied=False,
                    status="REJECTED_PRECONDITION_FAILED",
                    reason=f"Work item project root mismatch: '{live_check.project_root}' != '{project_root}'",
                    envelope=envelope,
                    work_item=live_check,
                )

        # 3. Construct canonical ArchitectDecision
        arch_dec = ArchitectDecision(
            decision=envelope.decision,
            current_phase=envelope.current_phase,
            next_phase=envelope.next_phase,
            action=envelope.action,
            human_approval_required=False,
            instruction=envelope.instruction or "Remote Human Project Owner approved via RPC-2",
            raw_text=json.dumps(envelope.to_dict()),
        )

        try:
            target_gate = DAIOGate(envelope.gate_id)
        except Exception:
            if send_ack and self.client:
                self.client.acknowledge_decision(
                    decision_id=envelope.decision_id,
                    status=TransportDeliveryState.REJECTED_PRECONDITION_FAILED,
                )
            return RemoteApplicationResult(
                applied=False,
                status="REJECTED_PRECONDITION_FAILED",
                reason=f"Invalid target gate_id in envelope: '{envelope.gate_id}'",
                envelope=envelope,
            )

        # 4. Authoritative Atomic Compare-and-Apply via SqliteDAIOWorkStore
        success, status_code, updated_work, dec_hash = store.apply_decision_transition_atomically(
            work_id=envelope.work_id,
            decision=arch_dec,
            acting_role=DAIORole.HUMAN_PROJECT_OWNER,
            expected_gate=target_gate,
            expected_status=DAIOStatus.HUMAN_GATE_REQUIRED,
            expected_stage=envelope.current_phase,
            expected_role=DAIORole.HUMAN_PROJECT_OWNER,
            expected_decision_id=envelope.decision_id,
            metadata_payload={
                "decision_id": envelope.decision_id,
                "protocol_version": envelope.protocol_version,
                "decision": envelope.decision,
                "action": envelope.action,
                "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        )

        if not success:
            ack_state = (
                TransportDeliveryState.DECISION_ALREADY_APPLIED
                if status_code == "DECISION_ALREADY_APPLIED"
                else (
                    TransportDeliveryState.REJECTED_STALE_CONTEXT
                    if status_code in ("REJECTED_STALE_CONTEXT", "REJECTED_WORK_NOT_FOUND")
                    else TransportDeliveryState.REJECTED_PRECONDITION_FAILED
                )
            )
            if send_ack and self.client:
                self.client.acknowledge_decision(
                    decision_id=envelope.decision_id,
                    status=ack_state,
                )
            
            if status_code == "DECISION_ALREADY_APPLIED":
                fail_reason = f"Decision hash '{dec_hash}' has already been applied."
            elif status_code == "REJECTED_WORK_NOT_FOUND":
                fail_reason = f"Work item '{envelope.work_id}' not found in canonical store."
            elif status_code == "REJECTED_STALE_CONTEXT":
                fail_reason = dec_hash or "TOCTOU context mismatch"
            else:
                fail_reason = f"Atomic store returned {status_code}"

            return RemoteApplicationResult(
                applied=False,
                status="REJECTED_STALE_CONTEXT" if status_code == "REJECTED_WORK_NOT_FOUND" else status_code,
                reason=fail_reason,
                work_item=updated_work,
                decision_hash=dec_hash,
                envelope=envelope,
            )

        # 5. Outbound Delivery ACK on Success
        if send_ack and self.client:
            self.client.acknowledge_decision(
                decision_id=envelope.decision_id,
                status=TransportDeliveryState.DECISION_APPLIED,
            )

        return RemoteApplicationResult(
            applied=True,
            status="DECISION_APPLIED",
            reason=f"Decision '{envelope.decision}' successfully applied to '{updated_work.work_id}'. Transitioned to {updated_work.current_gate.value} ({updated_work.status.value}).",
            work_item=updated_work,
            decision_hash=dec_hash,
            envelope=envelope,
        )

    def poll_and_apply(
        self,
        store: DAIOWorkStore,
        expected_work_id: Optional[str] = None,
        project_root: Optional[str] = None,
        send_ack: bool = True,
    ) -> List[RemoteApplicationResult]:
        """
        Polls remote relay, authoritatively revalidates live SQLite state at application time,
        and applies valid decisions to pending Human Gates.
        """
        if not self.client:
            logger.warning("No RemoteDecisionRelayClient configured.")
            return []

        envelopes = self.client.poll_decisions(work_id=expected_work_id)
        results: List[RemoteApplicationResult] = []

        for env in envelopes:
            app_res = self.validate_and_apply(
                envelope=env,
                store=store,
                project_root=project_root,
                send_ack=send_ack,
            )
            results.append(app_res)
            logger.info(f"🏛️ RPC-2B Application Result for [{env.decision_id}]: {app_res.status} ({app_res.reason})")

        return results

