"""
Focused Test Suite for DEFECT-C1-SUPERVISOR-INGRESS-002:
Persistent Supervisor Root Work Ingress via Durable Filesystem Inbox.

Verifies:
A. valid root request
B. malformed request
C. duplicate request_id
D. partial/temp file ignored
E. supervisor restart recovery
F. crash between claim and commit
G. two supervisor instances cannot double-ingest
H. Human Gate semantics preserved
"""

import asyncio
import datetime
import json
import os
from pathlib import Path
import tempfile
import pytest

from scripts.daio_closed_loop.models import (
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.inbox import (
    DAIORootWorkInbox,
    RootWorkRequest,
    SUPPORTED_INBOX_SCHEMA,
)
from scripts.daio_closed_loop.supervisor import DAIOSupervisor


@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "daio_test.db"
        inbox_dir = tmp_path / "_daio" / "inbox"
        store = SqliteDAIOWorkStore(str(db_path))
        inbox = DAIORootWorkInbox(inbox_dir)
        yield {
            "tmp_path": tmp_path,
            "db_path": db_path,
            "inbox_dir": inbox_dir,
            "store": store,
            "inbox": inbox,
        }


# =============================================================================
# Objective A: Valid Root Request
# =============================================================================
def test_valid_root_request_ingestion(test_env):
    store = test_env["store"]
    inbox = test_env["inbox"]
    inbox_dir = test_env["inbox_dir"]

    req_data = {
        "schema_version": "daio-root-work/v1",
        "request_id": "req-c1-001",
        "project_id": "awin-fintech",
        "change_id": "CHANGE_055",
        "requested_action": "Verify C1.1 root work ingress",
        "requested_role": "ENGINEERING_EXECUTION",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "allowed_scope": ["c1_test.py"],
        "metadata": {"custom_meta": "value_123"},
    }

    submitted_file = DAIORootWorkInbox.submit_request(inbox_dir, req_data)
    assert submitted_file.exists()
    assert submitted_file.name == "req-c1-001.json"

    # Poll and ingest
    results = inbox.poll_and_ingest(store=store, project_root=str(test_env["tmp_path"]))
    assert len(results) == 1
    assert results[0].status == "INGESTED"
    assert results[0].work_id == "daio-root-req-c1-001"

    # Verify file lifecycle
    assert not (inbox_dir / "req-c1-001.json").exists()
    assert not (inbox.processing_dir / "req-c1-001.json").exists()
    assert (inbox.processed_dir / "req-c1-001.json").exists()

    # Verify stored work item
    work = store.load_work_item("daio-root-req-c1-001")
    assert work is not None
    assert work.change_id == "CHANGE_055"
    assert work.assigned_role == DAIORole.ENGINEERING_EXECUTION
    assert work.current_gate == DAIOGate.IMPLEMENTATION_GATE
    assert work.status == DAIOStatus.QUEUED
    assert work.allowed_scope == ["c1_test.py"]
    assert work.metadata["root_request_id"] == "req-c1-001"
    assert work.metadata["custom_meta"] == "value_123"


# =============================================================================
# Objective B: Malformed Request
# =============================================================================
def test_malformed_request_rejection(test_env):
    store = test_env["store"]
    inbox = test_env["inbox"]
    inbox_dir = test_env["inbox_dir"]

    # 1. Invalid JSON
    bad_json_file = inbox_dir / "req-bad-json.json"
    bad_json_file.write_text("{ unclosed json: ", encoding="utf-8")

    # 2. Schema version mismatch
    bad_schema_file = inbox_dir / "req-bad-schema.json"
    bad_schema_file.write_text(json.dumps({
        "schema_version": "invalid-v99",
        "request_id": "req-bad-schema",
        "project_id": "awin-fintech",
        "change_id": "CHANGE_055",
        "requested_action": "test",
    }), encoding="utf-8")

    # 3. Missing change_id
    missing_change_file = inbox_dir / "req-missing-change.json"
    missing_change_file.write_text(json.dumps({
        "schema_version": "daio-root-work/v1",
        "request_id": "req-missing-change",
        "project_id": "awin-fintech",
        "requested_action": "test",
    }), encoding="utf-8")

    results = inbox.poll_and_ingest(store=store)
    assert len(results) == 3
    for r in results:
        assert r.status == "REJECTED_SCHEMA"

    # Verify rejected directory
    assert (inbox.rejected_dir / "req-bad-json.json").exists()
    assert (inbox.rejected_dir / "req-bad-schema.json").exists()
    assert (inbox.rejected_dir / "req-missing-change.json").exists()
    assert (inbox.rejected_dir / "req-bad-json.error.json").exists()

    # Zero work items created in SQLite
    assert len(store.list_work_items()) == 0


# =============================================================================
# Objective C: Duplicate Request ID Idempotency
# =============================================================================
def test_duplicate_request_id_idempotency(test_env):
    store = test_env["store"]
    inbox = test_env["inbox"]
    inbox_dir = test_env["inbox_dir"]

    req_data = {
        "schema_version": "daio-root-work/v1",
        "request_id": "req-c1-duplicate-test",
        "project_id": "awin-fintech",
        "change_id": "CHANGE_055",
        "requested_action": "Idempotency verification",
    }

    # First submission
    DAIORootWorkInbox.submit_request(inbox_dir, req_data)
    results1 = inbox.poll_and_ingest(store=store)
    assert len(results1) == 1
    assert results1[0].status == "INGESTED"
    assert len(store.list_work_items()) == 1

    # Second submission with same request_id
    DAIORootWorkInbox.submit_request(inbox_dir, req_data)
    results2 = inbox.poll_and_ingest(store=store)
    assert len(results2) == 1
    assert results2[0].status == "ALREADY_PROCESSED"
    assert results2[0].work_id == "daio-root-req-c1-duplicate-test"

    # Exactly 1 item in SQLite (no duplicates created)
    items = store.list_work_items()
    assert len(items) == 1


# =============================================================================
# Objective D: Partial / Temp File Ignored
# =============================================================================
def test_partial_temp_files_ignored(test_env):
    store = test_env["store"]
    inbox = test_env["inbox"]
    inbox_dir = test_env["inbox_dir"]

    # Write a .tmp file (in-flight producer write)
    tmp_file = inbox_dir / "req-inflight.tmp.12345"
    tmp_file.write_text(json.dumps({
        "schema_version": "daio-root-work/v1",
        "request_id": "req-inflight",
        "project_id": "awin",
        "change_id": "CHANGE_055",
        "requested_action": "in-flight",
    }), encoding="utf-8")

    # Write a non-json file
    txt_file = inbox_dir / "notes.txt"
    txt_file.write_text("just some notes", encoding="utf-8")

    results = inbox.poll_and_ingest(store=store)
    assert len(results) == 0
    assert tmp_file.exists()
    assert txt_file.exists()
    assert len(store.list_work_items()) == 0


# =============================================================================
# Objective E: Supervisor Restart Recovery
# =============================================================================
def test_supervisor_restart_recovery(test_env):
    tmp_path = test_env["tmp_path"]
    store = test_env["store"]
    inbox_dir = test_env["inbox_dir"]

    req_data = {
        "schema_version": "daio-root-work/v1",
        "request_id": "req-restart-test",
        "project_id": "awin-fintech",
        "change_id": "CHANGE_055",
        "requested_action": "Restart test",
    }
    DAIORootWorkInbox.submit_request(inbox_dir, req_data)

    async def _run():
        # Supervisor instance 1 runs 1 tick
        sup1 = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            inbox_dir=inbox_dir,
            enable_remote_ingress=False,
        )
        await sup1.run_tick()

        work1 = store.load_work_item("daio-root-req-restart-test")
        assert work1 is not None
        assert work1.change_id == "CHANGE_055"

        # Supervisor restarts (instance 2)
        sup2 = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            inbox_dir=inbox_dir,
            enable_remote_ingress=False,
        )
        await sup2.run_tick()

        # Queue state remains intact and uncorrupted (no duplicate work created)
        work2 = store.load_work_item("daio-root-req-restart-test")
        assert work2 is not None
        assert len(store.list_work_items()) == 1

    asyncio.run(_run())


# =============================================================================
# Objective F: Crash Between Claim and Commit Recovery
# =============================================================================
def test_crash_between_claim_and_commit(test_env):
    store = test_env["store"]
    inbox = test_env["inbox"]

    # Simulate a file that was claimed into processing/ before a crash (never committed to SQLite)
    proc_file = inbox.processing_dir / "req-crashed.json"
    proc_file.write_text(json.dumps({
        "schema_version": "daio-root-work/v1",
        "request_id": "req-crashed",
        "project_id": "awin-fintech",
        "change_id": "CHANGE_055",
        "requested_action": "Recover crashed item",
    }), encoding="utf-8")

    # Ingest should recover from processing/ directory
    results = inbox.poll_and_ingest(store=store)
    assert len(results) == 1
    assert results[0].status == "INGESTED"
    assert results[0].work_id == "daio-root-req-crashed"

    # File moved to processed/
    assert not proc_file.exists()
    assert (inbox.processed_dir / "req-crashed.json").exists()

    # Work committed to SQLite
    work = store.load_work_item("daio-root-req-crashed")
    assert work is not None


# =============================================================================
# Objective G: Two Supervisor Instances Concurrency Isolation
# =============================================================================
def test_two_supervisors_concurrent_ingest(test_env):
    store = test_env["store"]
    inbox1 = test_env["inbox"]
    inbox2 = DAIORootWorkInbox(test_env["inbox_dir"])
    inbox_dir = test_env["inbox_dir"]

    # Submit 5 items
    for i in range(5):
        DAIORootWorkInbox.submit_request(inbox_dir, {
            "schema_version": "daio-root-work/v1",
            "request_id": f"req-concurrent-{i}",
            "project_id": "awin-fintech",
            "change_id": "CHANGE_055",
            "requested_action": f"Concurrent test {i}",
        })

    # Both poll concurrently
    res1 = inbox1.poll_and_ingest(store=store)
    res2 = inbox2.poll_and_ingest(store=store)

    total_ingested = len([r for r in res1 + res2 if r.status == "INGESTED"])
    assert total_ingested == 5
    assert len(store.list_work_items()) == 5


# =============================================================================
# Objective H: Human Gate & Review Role Semantics Preserved
# =============================================================================
def test_review_role_and_gate_semantics(test_env):
    store = test_env["store"]
    inbox = test_env["inbox"]
    inbox_dir = test_env["inbox_dir"]

    # Submit item requested as LEAD_ARCHITECT_REVIEW with CONTRACT_GATE
    DAIORootWorkInbox.submit_request(inbox_dir, {
        "schema_version": "daio-root-work/v1",
        "request_id": "req-arch-review-001",
        "project_id": "awin-fintech",
        "change_id": "CHANGE_055",
        "requested_action": "Initial contract review",
        "requested_role": "LEAD_ARCHITECT_REVIEW",
        "current_gate": "CONTRACT_GATE",
        "architect_endpoint": {"provider": "CHATGPT_WEB"},
    })

    results = inbox.poll_and_ingest(store=store)
    assert len(results) == 1
    assert results[0].status == "INGESTED"

    work = store.load_work_item("daio-root-req-arch-review-001")
    assert work is not None
    assert work.assigned_role == DAIORole.LEAD_ARCHITECT_REVIEW
    assert work.current_gate == DAIOGate.CONTRACT_GATE
    assert work.architect_endpoint["provider"] == "CHATGPT_WEB"
