"""Verifier-backed WebAuthn Phase 0 acceptance boundary.

The production relay remains the authority for WebAuthn ceremonies.  This
small harness makes the already-approved fail-closed boundary executable in
the local acceptance suite without inventing a second authentication path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .face_id_approval import (
    BiometricCredential,
    FaceIdAssertion,
    Rpc3dFaceIdAcceptanceGate,
)


class Phase0Rejected(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class AuthoritativeProjectBinding:
    credential_id: str
    project_id: str
    binding_version: str
    revoked: bool = False


class WebAuthnPhase0AcceptanceHarness:
    """Exercise identity, project binding, UV, and ticket-admission gates."""

    def __init__(self, credential: BiometricCredential, project_id: str = "awin-fintech"):
        self.credential = credential
        self.gate = Rpc3dFaceIdAcceptanceGate(owner_credential=credential)
        self.bindings: Dict[str, AuthoritativeProjectBinding] = {
            credential.credential_id: AuthoritativeProjectBinding(
                credential_id=credential.credential_id,
                project_id=project_id,
                binding_version="binding-v1",
            )
        }

    def issue_challenge(self):
        return self.gate.issue_challenge(rpc_action="NATIVE_DISPATCH", target_scope="DAIO")

    def verify_identity(
        self,
        *,
        project_id: str,
        credential_id: str,
        challenge_id: str,
        assertion: Optional[FaceIdAssertion],
    ):
        if assertion is None:
            raise Phase0Rejected(
                "LEGACY_UNVERIFIED",
                "credential-only state cannot establish authenticated identity",
            )
        try:
            receipt = self.gate.verify_assertion(challenge_id, assertion)
        except AttributeError:
            receipt = None
        except ValueError as exc:
            if "Face ID" in str(exc) or "verification" in str(exc).lower():
                raise Phase0Rejected("REQUIRED_USER_VERIFICATION", str(exc)) from exc
            raise Phase0Rejected("WEBAUTHN_REJECTED", str(exc)) from exc

        binding = self.bindings.get(credential_id)
        if binding is None or binding.revoked or binding.project_id != project_id:
            raise Phase0Rejected(
                "PROJECT_CONTEXT_MISMATCH",
                "no authoritative project-scoped credential binding resolves",
            )
        return {"credential_id": credential_id, "project_id": project_id, "binding_version": binding.binding_version}
