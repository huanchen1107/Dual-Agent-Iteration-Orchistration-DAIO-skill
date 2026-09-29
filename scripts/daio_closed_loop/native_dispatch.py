"""Native WebAuthn-to-DAIO dispatch boundary.

This module deliberately stops at canonical inbox admission.  It does not
create a work ID, gate ID, or mutate the DAIO store before the existing
``DAIORootWorkInbox`` lifecycle accepts a request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime as _dt
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .inbox import DAIORootWorkInbox, RootWorkRequest
from .store import DAIOWorkStore


class NativeDispatchError(ValueError):
    """Fail-closed native dispatch rejection."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_time(value: str) -> _dt.datetime:
    clean = str(value).replace("Z", "+00:00")
    parsed = _dt.datetime.fromisoformat(clean)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalized_task_hash(task: Dict[str, Any]) -> str:
    """Hash only the normalized task fields that will enter RootWorkRequest."""
    required = {
        "change_id": str(task.get("change_id", "")).strip(),
        "requested_action": str(task.get("requested_action", "")).strip(),
        "requested_role": str(task.get("requested_role", "ENGINEERING_EXECUTION")).strip().upper(),
        "allowed_scope": sorted(str(x) for x in (task.get("allowed_scope") or [])),
        "metadata": dict(task.get("metadata") or {}),
    }
    if not required["change_id"] or not required["requested_action"]:
        raise NativeDispatchError("dispatch task requires change_id and requested_action")
    return hashlib.sha256(_canonical_json(required).encode("utf-8")).hexdigest()


@dataclass
class VerifiedWebAuthnIdentity:
    credential_id: str
    user_verified: bool = True
    verified_at: str = field(default_factory=lambda: _now().isoformat())
    verification_method: str = "WEBAUTHN_PASSKEY"


@dataclass
class CredentialBinding:
    credential_id: str
    project_id: str
    chatgpt_project_id: str
    conversation_id: str
    binding_version: str
    revoked: bool = False


class AuthoritativeCredentialBindingRegistry:
    """Authoritative credential-to-project/conversation binding registry."""

    def __init__(self, bindings: Optional[Iterable[CredentialBinding]] = None):
        self._bindings: Dict[str, List[CredentialBinding]] = {}
        for binding in bindings or []:
            self.register(binding)

    def register(self, binding: CredentialBinding) -> None:
        if not all(
            str(getattr(binding, field_name, "")).strip()
            for field_name in (
                "credential_id",
                "project_id",
                "chatgpt_project_id",
                "conversation_id",
                "binding_version",
            )
        ):
            raise NativeDispatchError("credential binding fields are required")
        self._bindings.setdefault(binding.credential_id, []).append(binding)

    def revoke(self, credential_id: str, binding_version: Optional[str] = None) -> None:
        for binding in self._bindings.get(credential_id, []):
            if binding_version is None or binding.binding_version == binding_version:
                binding.revoked = True

    def resolve(
        self,
        credential_id: str,
        *,
        project_id: Optional[str] = None,
        chatgpt_project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> CredentialBinding:
        candidates = [b for b in self._bindings.get(credential_id, []) if not b.revoked]
        if not candidates:
            raise NativeDispatchError("no active authoritative credential binding")
        if len(candidates) != 1:
            raise NativeDispatchError("ambiguous authoritative credential binding")
        binding = candidates[0]
        checks = (
            ("project", project_id, binding.project_id),
            ("ChatGPT Project", chatgpt_project_id, binding.chatgpt_project_id),
            ("conversation", conversation_id, binding.conversation_id),
        )
        for label, supplied, authoritative in checks:
            if supplied is not None and str(supplied) != authoritative:
                raise NativeDispatchError(f"{label} context mismatch")
        return binding


@dataclass
class PreAdmissionDispatchTicket:
    ticket_id: str
    credential_id: str
    project_id: str
    chatgpt_project_id: str
    conversation_id: str
    binding_version: str
    action: str
    task_hash: str
    idempotency_key: str
    issued_at: str
    expires_at: str
    consumed: bool = False
    task: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class InMemoryNativeDispatchRelay:
    """Deterministic relay double used by the executable acceptance suite."""

    def __init__(self):
        self._tickets: Dict[str, PreAdmissionDispatchTicket] = {}

    def put_ticket(self, ticket: PreAdmissionDispatchTicket) -> PreAdmissionDispatchTicket:
        existing = self._tickets.get(ticket.ticket_id)
        if existing and existing.to_dict() != ticket.to_dict():
            raise NativeDispatchError("dispatch ticket ID collision")
        self._tickets[ticket.ticket_id] = ticket
        return ticket

    def find_by_idempotency(self, idempotency_key: str) -> Optional[PreAdmissionDispatchTicket]:
        for ticket in self._tickets.values():
            if ticket.idempotency_key == idempotency_key:
                return ticket
        return None

    def poll(self) -> List[PreAdmissionDispatchTicket]:
        return [ticket for ticket in self._tickets.values() if not ticket.consumed]

    def ack(self, ticket_id: str) -> None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            raise NativeDispatchError("dispatch ticket not found")
        if ticket.consumed:
            raise NativeDispatchError("dispatch ticket already consumed")
        ticket.consumed = True


class NativeDispatchService:
    """Issue and revalidate pre-admission dispatch tickets."""

    def __init__(self, registry: AuthoritativeCredentialBindingRegistry, relay: InMemoryNativeDispatchRelay):
        self.registry = registry
        self.relay = relay

    def issue_ticket(
        self,
        identity: VerifiedWebAuthnIdentity,
        task: Dict[str, Any],
        idempotency_key: str,
        *,
        project_id: Optional[str] = None,
        chatgpt_project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        ttl_seconds: int = 180,
        now: Optional[_dt.datetime] = None,
    ) -> PreAdmissionDispatchTicket:
        if not identity.user_verified:
            raise NativeDispatchError("verified WebAuthn identity required")
        if not str(idempotency_key).strip():
            raise NativeDispatchError("client idempotency key required")
        binding = self.registry.resolve(
            identity.credential_id,
            project_id=project_id,
            chatgpt_project_id=chatgpt_project_id,
            conversation_id=conversation_id,
        )
        task_hash = normalized_task_hash(task)
        existing = self.relay.find_by_idempotency(idempotency_key)
        if existing:
            if existing.task_hash != task_hash or existing.binding_version != binding.binding_version:
                raise NativeDispatchError("idempotency key is bound to a different task or binding")
            if existing.consumed:
                raise NativeDispatchError("dispatch ticket already consumed")
            return existing
        issued = now or _now()
        ticket = PreAdmissionDispatchTicket(
            ticket_id=f"dsp-{secrets.token_urlsafe(18)}",
            credential_id=identity.credential_id,
            project_id=binding.project_id,
            chatgpt_project_id=binding.chatgpt_project_id,
            conversation_id=binding.conversation_id,
            binding_version=binding.binding_version,
            action="dispatch_work",
            task_hash=task_hash,
            idempotency_key=str(idempotency_key),
            issued_at=issued.isoformat(),
            expires_at=(issued + _dt.timedelta(seconds=ttl_seconds)).isoformat(),
            task=dict(task),
        )
        return self.relay.put_ticket(ticket)

    def validate_ticket(self, ticket: PreAdmissionDispatchTicket, *, now: Optional[_dt.datetime] = None) -> CredentialBinding:
        if ticket.action != "dispatch_work":
            raise NativeDispatchError("wrong dispatch ticket action")
        if ticket.consumed:
            raise NativeDispatchError("dispatch ticket already consumed")
        current = now or _now()
        if current > _parse_time(ticket.expires_at):
            raise NativeDispatchError("dispatch ticket expired")
        binding = self.registry.resolve(
            ticket.credential_id,
            project_id=ticket.project_id,
            chatgpt_project_id=ticket.chatgpt_project_id,
            conversation_id=ticket.conversation_id,
        )
        if binding.binding_version != ticket.binding_version:
            raise NativeDispatchError("stale credential binding")
        if normalized_task_hash(ticket.task) != ticket.task_hash:
            raise NativeDispatchError("dispatch task hash mismatch")
        return binding


@dataclass
class NativeDispatchResult:
    status: str
    ticket_id: str
    request_id: Optional[str] = None
    work_id: Optional[str] = None
    reason: Optional[str] = None


class NativeDispatchPoller:
    """Outbound-only relay poller terminating at canonical inbox admission."""

    def __init__(self, service: NativeDispatchService):
        self.service = service

    def poll_once(
        self,
        inbox: DAIORootWorkInbox,
        store: DAIOWorkStore,
        *,
        project_root: Optional[str] = None,
        now: Optional[_dt.datetime] = None,
    ) -> List[NativeDispatchResult]:
        results: List[NativeDispatchResult] = []
        for ticket in list(self.service.relay.poll()):
            try:
                binding = self.service.validate_ticket(ticket, now=now)
                request_id = f"native-dispatch-{ticket.idempotency_key}"
                task = dict(ticket.task)
                request = RootWorkRequest(
                    schema_version="daio-root-work/v1",
                    request_id=request_id,
                    project_id=binding.project_id,
                    change_id=str(task["change_id"]).strip(),
                    requested_action=str(task["requested_action"]).strip(),
                    requested_role=str(task.get("requested_role", "ENGINEERING_EXECUTION")).strip().upper(),
                    allowed_scope=list(task.get("allowed_scope") or []),
                    architect_endpoint={
                        "provider": "CHATGPT_WEB",
                        "project_id": binding.chatgpt_project_id,
                        "chatgpt_project_id": binding.chatgpt_project_id,
                        "conversation_id": binding.conversation_id,
                        "routing_policy": "EXACT_CONVERSATION",
                    },
                    metadata={
                        **dict(task.get("metadata") or {}),
                        "native_dispatch": True,
                        "dispatch_ticket_id": ticket.ticket_id,
                        "credential_id": ticket.credential_id,
                        "binding_version": ticket.binding_version,
                        "client_idempotency_key": ticket.idempotency_key,
                        "task_hash": ticket.task_hash,
                    },
                )
                DAIORootWorkInbox.submit_request(inbox.inbox_dir, request)
                ingested = inbox.poll_and_ingest(store=store, project_root=project_root)
                matching = next((r for r in ingested if r.request_id == request_id), None)
                if matching is None or not matching.work_id:
                    raise NativeDispatchError("canonical inbox admission did not produce a work ID")
                # ACK only after the durable canonical admission result exists.
                self.service.relay.ack(ticket.ticket_id)
                results.append(
                    NativeDispatchResult(
                        status="ADMITTED",
                        ticket_id=ticket.ticket_id,
                        request_id=request_id,
                        work_id=matching.work_id,
                    )
                )
            except Exception as exc:
                results.append(
                    NativeDispatchResult(
                        status="REJECTED" if "expired" in str(exc) or "mismatch" in str(exc) or "binding" in str(exc) else "RETRYABLE",
                        ticket_id=ticket.ticket_id,
                        reason=str(exc),
                    )
                )
        return results
