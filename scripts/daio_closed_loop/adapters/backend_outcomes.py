"""Allowlisted failure classification with fixed, non-secret diagnostic reasons."""
from dataclasses import dataclass
import json
import re

from ..handoff_contract import Outcome


@dataclass(frozen=True)
class FailureClassification:
    outcome: Outcome
    sanitized_reason: str


_CODE_CLASSIFICATIONS = {
    'QUOTA_EXHAUSTED': FailureClassification(Outcome.CAPACITY_EXHAUSTED, 'PROVIDER_QUOTA_EXHAUSTED'),
    'INSUFFICIENT_QUOTA': FailureClassification(Outcome.CAPACITY_EXHAUSTED, 'PROVIDER_INSUFFICIENT_QUOTA'),
    'RESOURCE_EXHAUSTED': FailureClassification(Outcome.CAPACITY_EXHAUSTED, 'PROVIDER_RESOURCE_EXHAUSTED'),
    'RATE_LIMITED': FailureClassification(Outcome.RATE_LIMITED, 'PROVIDER_RATE_LIMITED'),
    'RATE_LIMIT_EXCEEDED': FailureClassification(Outcome.RATE_LIMITED, 'PROVIDER_RATE_LIMIT_EXCEEDED'),
    'TOO_MANY_REQUESTS': FailureClassification(Outcome.RATE_LIMITED, 'PROVIDER_TOO_MANY_REQUESTS'),
    'TEMPORARILY_UNAVAILABLE': FailureClassification(Outcome.TEMPORARILY_UNAVAILABLE, 'PROVIDER_TEMPORARILY_UNAVAILABLE'),
    'BACKEND_UNAVAILABLE': FailureClassification(Outcome.TEMPORARILY_UNAVAILABLE, 'PROVIDER_BACKEND_UNAVAILABLE'),
    'SERVICE_UNAVAILABLE': FailureClassification(Outcome.TEMPORARILY_UNAVAILABLE, 'PROVIDER_SERVICE_UNAVAILABLE'),
    'AUTHENTICATION_REQUIRED': FailureClassification(Outcome.AUTHENTICATION_REQUIRED, 'PROVIDER_AUTHENTICATION_REQUIRED'),
    'UNAUTHENTICATED': FailureClassification(Outcome.AUTHENTICATION_REQUIRED, 'PROVIDER_UNAUTHENTICATED'),
    'UNAUTHORIZED': FailureClassification(Outcome.AUTHENTICATION_REQUIRED, 'PROVIDER_UNAUTHORIZED'),
    'INCOMPATIBLE': FailureClassification(Outcome.INCOMPATIBLE, 'PROVIDER_INCOMPATIBLE'),
    'UNSUPPORTED_MODEL': FailureClassification(Outcome.INCOMPATIBLE, 'PROVIDER_UNSUPPORTED_MODEL'),
    'MODEL_NOT_FOUND': FailureClassification(Outcome.INCOMPATIBLE, 'PROVIDER_MODEL_NOT_FOUND'),
}


def _machine_code(payload):
    if not isinstance(payload, dict):
        return None
    error = payload.get('error')
    code = payload.get('error_code') or payload.get('code')
    if isinstance(error, dict):
        code = error.get('code', code)
    return code.upper() if isinstance(code, str) else None


def _json_objects(text):
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            yield value


def classify_process_failure(stdout, stderr, returncode):
    """Classify a nonzero provider process without retaining provider text."""
    if returncode == 0:
        return FailureClassification(Outcome.UNKNOWN_FAILURE, 'NON_FAILURE_EXIT')

    for stream in (stdout, stderr):
        for payload in _json_objects(stream or ''):
            classified = _CODE_CLASSIFICATIONS.get(_machine_code(payload))
            if classified:
                return classified

    diagnostic = '\n'.join((stdout or '', stderr or '')).lower()
    patterns = (
        (r'\b(quota exhausted|insufficient[_ -]quota|resource[_ -]exhausted|usage limit (?:reached|exceeded)|capacity exhausted)\b',
         FailureClassification(Outcome.CAPACITY_EXHAUSTED, 'PROVIDER_CAPACITY_EXHAUSTED')),
        (r'\b(rate[_ -]limit(?:ed| exceeded)?|too many requests)\b',
         FailureClassification(Outcome.RATE_LIMITED, 'PROVIDER_RATE_LIMITED')),
        (r'\b(temporarily unavailable|service unavailable|backend unavailable|service is overloaded|server overloaded)\b',
         FailureClassification(Outcome.TEMPORARILY_UNAVAILABLE, 'PROVIDER_TEMPORARILY_UNAVAILABLE')),
        (r'\b(authentication required|login required|not logged in|unauthenticated|unauthorized|please (?:run )?codex login)\b',
         FailureClassification(Outcome.AUTHENTICATION_REQUIRED, 'PROVIDER_AUTHENTICATION_REQUIRED')),
        (r'\b(unsupported model|model not found|model is not supported|incompatible model)\b',
         FailureClassification(Outcome.INCOMPATIBLE, 'PROVIDER_MODEL_INCOMPATIBLE')),
    )
    for pattern, classified in patterns:
        if re.search(pattern, diagnostic):
            return classified
    return FailureClassification(Outcome.UNKNOWN_FAILURE, 'UNRECOGNIZED_PROVIDER_DIAGNOSTIC')


def classify_failure(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return Outcome.UNKNOWN_FAILURE
    if not isinstance(payload, dict):
        return Outcome.UNKNOWN_FAILURE
    code = _machine_code(payload)
    return {
        'QUOTA_EXHAUSTED': Outcome.QUOTA_EXHAUSTED,
        'INSUFFICIENT_QUOTA': Outcome.QUOTA_EXHAUSTED,
        'AUTHENTICATION_REQUIRED': Outcome.AUTHENTICATION_REQUIRED,
        'UNAUTHENTICATED': Outcome.AUTHENTICATION_REQUIRED,
        'BACKEND_UNAVAILABLE': Outcome.BACKEND_UNAVAILABLE,
        'SERVICE_UNAVAILABLE': Outcome.BACKEND_UNAVAILABLE,
    }.get(code, Outcome.UNKNOWN_FAILURE) if isinstance(code, str) else Outcome.UNKNOWN_FAILURE
