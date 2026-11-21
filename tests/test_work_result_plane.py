import json

import pytest

from scripts.daio_closed_loop.models import DAIOStatus, DAIOWorkItem
from scripts.daio_closed_loop.work_result import (
    SCHEMA_VERSION,
    WorkResultProjector,
    build_work_result,
)


def make_work(tmp_path, *, project="project-a", status=DAIOStatus.IN_PROGRESS, revision=1, event=1):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"stdout": "Hello", "secret_token": "must-not-leak"}), encoding="utf-8")
    return DAIOWorkItem(
        work_id="work-1",
        project_root=str(tmp_path),
        change_id="CHANGE",
        status=status,
        execution_attempt_id="attempt-1",
        updated_at=f"2026-09-29T00:00:0{revision}+00:00",
        work_revision=revision,
        event_sequence=event,
        architect_endpoint={"project_id": project},
        metadata={
            "provider": "ANTIGRAVITY_CLI",
            "last_execution_report": "completed safely",
            "completion_evidence_path": "evidence.json",
        },
    )


def test_completed_work_projects_canonical_result_and_safe_evidence(tmp_path):
    work = make_work(tmp_path, status=DAIOStatus.COMPLETED)
    envelope = build_work_result(work)
    assert envelope.schema_version == SCHEMA_VERSION
    assert envelope.lifecycle == "COMPLETED"
    assert envelope.stdout == "Hello"
    assert envelope.evidence_references == ["evidence.json"]
    assert "must-not-leak" not in json.dumps(envelope.to_dict())


def test_pending_work_has_lifecycle_without_fabricated_result(tmp_path):
    envelope = build_work_result(make_work(tmp_path))
    assert envelope.lifecycle == "IN_PROGRESS"
    assert envelope.stdout is None
    assert envelope.result_summary is None


def test_unknown_work_id_fails_safely(tmp_path):
    projector = WorkResultProjector()
    assert projector.query("project-a", "unknown") is None


def test_cross_project_work_id_is_rejected(tmp_path):
    projector = WorkResultProjector()
    projector.publish(build_work_result(make_work(tmp_path, project="project-a")))
    assert projector.query("project-b", "work-1") is None


def test_invalid_integrity_is_rejected(tmp_path):
    projector = WorkResultProjector()
    envelope = build_work_result(make_work(tmp_path, status=DAIOStatus.COMPLETED))
    object.__setattr__(envelope, "integrity_sha256", "bad")
    with pytest.raises(ValueError, match="integrity"):
        projector.publish(envelope)


def test_duplicate_publication_is_idempotent(tmp_path):
    projector = WorkResultProjector()
    envelope = build_work_result(make_work(tmp_path, status=DAIOStatus.COMPLETED))
    assert projector.publish(envelope) is True
    assert projector.publish(envelope) is True
    assert projector.query("project-a", "work-1") == envelope


def test_stale_publication_cannot_overwrite_newer_result(tmp_path):
    projector = WorkResultProjector()
    newer = build_work_result(make_work(tmp_path, status=DAIOStatus.COMPLETED, revision=2, event=2))
    older = build_work_result(make_work(tmp_path, status=DAIOStatus.IN_PROGRESS, revision=1, event=1))
    assert projector.publish(newer) is True
    assert projector.publish(older) is False
    assert projector.query("project-a", "work-1").lifecycle == "COMPLETED"


def test_republication_after_projection_restart_is_safe(tmp_path):
    envelope = build_work_result(make_work(tmp_path, status=DAIOStatus.COMPLETED))
    first = WorkResultProjector()
    assert first.publish(envelope) is True
    restarted = WorkResultProjector()
    assert restarted.publish(envelope) is True
    assert restarted.query("project-a", "work-1") == envelope


def test_status_plane_is_not_used_by_result_projector(tmp_path):
    envelope = build_work_result(make_work(tmp_path, status=DAIOStatus.COMPLETED))
    assert "STATUS_KV" not in json.dumps(envelope.to_dict())


def test_result_projection_contains_no_unrestricted_evidence_contents(tmp_path):
    envelope = build_work_result(make_work(tmp_path, status=DAIOStatus.COMPLETED))
    payload = envelope.to_dict()
    assert payload["evidence_references"] == ["evidence.json"]
    assert "secret_token" not in json.dumps(payload)
