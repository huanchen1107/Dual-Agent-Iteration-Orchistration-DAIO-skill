"""Allowlisted machine-code classification; no provider text is persisted here."""
import json

from ..handoff_contract import Outcome


def classify_failure(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return Outcome.UNKNOWN_FAILURE
    if not isinstance(payload, dict):
        return Outcome.UNKNOWN_FAILURE
    error = payload.get('error')
    code = payload.get('error_code')
    if isinstance(error, dict):
        code = error.get('code', code)
    return {
        'QUOTA_EXHAUSTED': Outcome.QUOTA_EXHAUSTED,
        'INSUFFICIENT_QUOTA': Outcome.QUOTA_EXHAUSTED,
        'AUTHENTICATION_REQUIRED': Outcome.AUTHENTICATION_REQUIRED,
        'UNAUTHENTICATED': Outcome.AUTHENTICATION_REQUIRED,
        'BACKEND_UNAVAILABLE': Outcome.BACKEND_UNAVAILABLE,
        'SERVICE_UNAVAILABLE': Outcome.BACKEND_UNAVAILABLE,
    }.get(code, Outcome.UNKNOWN_FAILURE) if isinstance(code, str) else Outcome.UNKNOWN_FAILURE
