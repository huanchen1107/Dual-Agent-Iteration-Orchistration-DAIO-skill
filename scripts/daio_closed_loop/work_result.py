"""Channel-neutral canonical work-result projection.

The SQLite work store and evidence files remain authoritative.  This module
only builds a bounded, safe projection suitable for an outbound relay and
for authenticated ingress clients to query by canonical Work ID.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .models import DAIOStatus, DAIOWorkItem

SCHEMA_VERSION = "daio-work-result/v1"
_SECRET_PARTS = ("secret", "token", "password", "private", "credential", "authorization")


def _project_id(work: DAIOWorkItem) -> str:
    endpoint = work.architect_endpoint or {}
    project = endpoint.get("project_id") or endpoint.get("chatgpt_project_id")
    project = str(project or work.metadata.get("project_id") or "").strip()
    if not project:
        raise ValueError("canonical work is missing project_id")
    return project


def _safe_evidence(work: DAIOWorkItem) -> list[str]:
    value = (work.metadata or {}).get("evidence_file") or (work.metadata or {}).get("completion_evidence_path")
    if not value:
        return []
    path = Path(str(value))
    # References only; never include arbitrary file contents or absolute paths.
    if path.is_absolute() or ".." in path.parts:
        return []
    return [path.as_posix()]


def _safe_summary(value: Any, limit: int = 4000) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    lowered = text.lower()
    if any(part in lowered for part in _SECRET_PARTS):
        return "[REDACTED]"
    return text[:limit]


@dataclass(frozen=True)
class WorkResultEnvelope:
    schema_version: str
    project_id: str
    work_id: str
    execution_attempt_id: Optional[str]
    lifecycle: str
    provider: Optional[str]
    stdout: Optional[str]
    result_summary: Optional[str]
    evidence_references: list[str]
    completed_at: Optional[str]
    updated_at: str
    work_revision: int
    event_sequence: int
    integrity_sha256: str

    def unsigned_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("integrity_sha256", None)
        return payload

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "WorkResultEnvelope":
        raw = dict(value)
        return cls(
            schema_version=str(raw.get("schema_version", "")),
            project_id=str(raw.get("project_id", "")),
            work_id=str(raw.get("work_id", "")),
            execution_attempt_id=raw.get("execution_attempt_id"),
            lifecycle=str(raw.get("lifecycle", "")),
            provider=raw.get("provider"),
            stdout=raw.get("stdout"),
            result_summary=raw.get("result_summary"),
            evidence_references=list(raw.get("evidence_references") or []),
            completed_at=raw.get("completed_at"),
            updated_at=str(raw.get("updated_at", "")),
            work_revision=int(raw.get("work_revision", 0)),
            event_sequence=int(raw.get("event_sequence", 0)),
            integrity_sha256=str(raw.get("integrity_sha256", "")),
        )


def build_work_result(work: DAIOWorkItem) -> WorkResultEnvelope:
    """Project only facts already present in the canonical work/evidence state."""
    metadata = work.metadata or {}
    evidence_path = metadata.get("completion_evidence_path")
    stdout = None
    if evidence_path:
        root = Path(work.project_root).resolve()
        candidate = (root / str(evidence_path)).resolve()
        if root in candidate.parents and candidate.is_file():
            try:
                evidence = json.loads(candidate.read_text(encoding="utf-8"))
                stdout = evidence.get("stdout", evidence.get("observed_stdout"))
            except (OSError, ValueError, TypeError):
                stdout = None
    terminal = work.status in {DAIOStatus.COMPLETED, DAIOStatus.BLOCKED, DAIOStatus.HUMAN_GATE_REQUIRED}
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "project_id": _project_id(work),
        "work_id": work.work_id,
        "execution_attempt_id": work.execution_attempt_id,
        "lifecycle": work.status.value,
        "provider": metadata.get("provider") or metadata.get("execution_provider"),
        "stdout": _safe_summary(stdout) if terminal else None,
        "result_summary": _safe_summary(metadata.get("last_execution_report") or work.last_decision) if terminal else None,
        "evidence_references": _safe_evidence(work),
        "completed_at": metadata.get("completed_at") if work.status in {DAIOStatus.COMPLETED, DAIOStatus.BLOCKED, DAIOStatus.HUMAN_GATE_REQUIRED} else None,
        "updated_at": work.updated_at,
        "work_revision": work.work_revision,
        "event_sequence": work.event_sequence,
    }
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return WorkResultEnvelope(**unsigned, integrity_sha256=digest)


class WorkResultProjector:
    """Bounded relay projection with project isolation and monotonic updates."""

    def __init__(self) -> None:
        self._items: Dict[tuple[str, str], WorkResultEnvelope] = {}

    def publish(self, envelope: WorkResultEnvelope) -> bool:
        if envelope.schema_version != SCHEMA_VERSION or not envelope.project_id or not envelope.work_id:
            raise ValueError("invalid work-result envelope")
        expected = hashlib.sha256(json.dumps(envelope.unsigned_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if envelope.integrity_sha256 != expected:
            raise ValueError("work-result integrity mismatch")
        key = (envelope.project_id, envelope.work_id)
        current = self._items.get(key)
        incoming_version = (envelope.work_revision, envelope.event_sequence, envelope.updated_at)
        if current and incoming_version < (current.work_revision, current.event_sequence, current.updated_at):
            return False
        self._items[key] = envelope
        return True

    def query(self, project_id: str, work_id: str) -> Optional[WorkResultEnvelope]:
        return self._items.get((project_id, work_id))
