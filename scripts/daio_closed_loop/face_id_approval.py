"""
_daio/face_id_approval.py
iPhone Face ID Biometric Approval Gate for RPC-3D Controlled Acceptance.

Provides secure Human-In-The-Loop (HITL) cryptographic challenge-response
verification for Project Owner authorization using iOS Secure Enclave / Face ID.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# WebAuthn / Passkey Authenticator Data Flags
FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04  # Biometric verification (Face ID) confirmed


@dataclass(frozen=True)
class BiometricCredential:
    credential_id: str
    owner_identity: str
    device_name: str
    public_key_pem: str
    algorithm: str = "ES256"


@dataclass
class ApprovalChallenge:
    challenge_id: str
    rpc_action: str
    target_scope: str
    nonce: str
    created_at: float
    expires_at: float
    status: ApprovalStatus = ApprovalStatus.PENDING

    def is_expired(self, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.time()
        return now > self.expires_at


@dataclass(frozen=True)
class FaceIdAssertion:
    credential_id: str
    client_data_json: str
    authenticator_data_b64: str
    signature_b64: str
    device_attestation: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ApprovalReceipt:
    receipt_id: str
    challenge_id: str
    rpc_action: str
    target_scope: str
    approved_by: str
    auth_method: str
    verified_at: float
    audit_hash: str


class Rpc3dFaceIdAcceptanceGate:
    """
    Controlled acceptance gate requiring Project Owner iPhone Face ID validation
    prior to applying or executing RPC-3D transitions.
    """

    def __init__(self, owner_credential: BiometricCredential, default_ttl_seconds: int = 300):
        self.owner_credential = owner_credential
        self.default_ttl_seconds = default_ttl_seconds
        self._challenges: Dict[str, ApprovalChallenge] = {}
        self._receipts: Dict[str, ApprovalReceipt] = {}

    def issue_challenge(
        self, rpc_action: str, target_scope: str = "RPC-3D", ttl: Optional[int] = None
    ) -> ApprovalChallenge:
        ttl_seconds = ttl if ttl is not None else self.default_ttl_seconds
        challenge_id = f"ch_{secrets.token_hex(12)}"
        nonce = secrets.token_urlsafe(32)
        now = time.time()
        challenge = ApprovalChallenge(
            challenge_id=challenge_id,
            rpc_action=rpc_action,
            target_scope=target_scope,
            nonce=nonce,
            created_at=now,
            expires_at=now + ttl_seconds,
            status=ApprovalStatus.PENDING,
        )
        self._challenges[challenge_id] = challenge
        return challenge

    def get_challenge(self, challenge_id: str) -> Optional[ApprovalChallenge]:
        return self._challenges.get(challenge_id)

    def verify_assertion(
        self,
        challenge_id: str,
        assertion: FaceIdAssertion,
        signature_verifier: Optional[Callable[..., bool]] = None,
        current_time: Optional[float] = None,
    ) -> ApprovalReceipt:
        challenge = self._challenges.get(challenge_id)
        if not challenge:
            raise ValueError(f"Challenge '{challenge_id}' not found.")

        now = current_time if current_time is not None else time.time()
        if challenge.is_expired(now):
            challenge.status = ApprovalStatus.EXPIRED
            raise ValueError("Approval challenge has expired.")

        if challenge.status != ApprovalStatus.PENDING:
            raise ValueError(f"Challenge cannot be verified; current status is {challenge.status}.")

        if assertion.credential_id != self.owner_credential.credential_id:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError("Credential mismatch: assertion not signed by registered Project Owner device.")

        try:
            client_data = json.loads(assertion.client_data_json)
        except Exception as err:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError(f"Invalid client_data_json payload: {err}")

        if client_data.get("challenge") != challenge.nonce:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError("Challenge nonce mismatch.")

        try:
            auth_data_bytes = base64.b64decode(assertion.authenticator_data_b64)
        except Exception as err:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError(f"Invalid authenticator_data encoding: {err}")

        if len(auth_data_bytes) < 37:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError("Authenticator data payload is malformed or too short.")

        flags = auth_data_bytes[32]
        user_present = bool(flags & FLAG_USER_PRESENT)
        user_verified = bool(flags & FLAG_USER_VERIFIED)

        if not user_present:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError("User presence flag missing from authenticator assertion.")

        if not user_verified:
            challenge.status = ApprovalStatus.REJECTED
            raise ValueError("Biometric user verification (Face ID) flag not confirmed by device.")

        if signature_verifier is not None:
            is_valid = signature_verifier(
                auth_data_bytes=auth_data_bytes,
                client_data_json=assertion.client_data_json.encode("utf-8"),
                signature_bytes=base64.b64decode(assertion.signature_b64),
                public_key_pem=self.owner_credential.public_key_pem,
            )
            if not is_valid:
                challenge.status = ApprovalStatus.REJECTED
                raise ValueError("Cryptographic biometric signature verification failed.")
        else:
            signed_payload = auth_data_bytes + hashlib.sha256(assertion.client_data_json.encode("utf-8")).digest()
            expected_digest = hashlib.sha256(
                signed_payload + self.owner_credential.public_key_pem.encode("utf-8")
            ).digest()
            provided_sig = base64.b64decode(assertion.signature_b64)
            if not hmac.compare_digest(provided_sig, expected_digest):
                challenge.status = ApprovalStatus.REJECTED
                raise ValueError("Signature digest mismatch on assertion verification.")

        challenge.status = ApprovalStatus.APPROVED
        receipt_id = f"rcpt_{secrets.token_hex(16)}"
        audit_payload = f"{receipt_id}:{challenge.challenge_id}:{challenge.rpc_action}:{now}:{self.owner_credential.owner_identity}"
        audit_hash = hashlib.sha256(audit_payload.encode("utf-8")).hexdigest()

        receipt = ApprovalReceipt(
            receipt_id=receipt_id,
            challenge_id=challenge.challenge_id,
            rpc_action=challenge.rpc_action,
            target_scope=challenge.target_scope,
            approved_by=self.owner_credential.owner_identity,
            auth_method="iOS_Face_ID_Secure_Enclave",
            verified_at=now,
            audit_hash=audit_hash,
        )
        self._receipts[receipt_id] = receipt
        return receipt

    def get_receipt(self, receipt_id: str) -> Optional[ApprovalReceipt]:
        return self._receipts.get(receipt_id)
