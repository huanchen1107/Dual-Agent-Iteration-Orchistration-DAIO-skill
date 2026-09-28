import asyncio
import json

from scripts.daio_closed_loop.adapters.bridge import MockArchitectBridgeAdapter
from scripts.daio_closed_loop.completion_delivery import deliver_user_visible_completion
from scripts.daio_closed_loop.models import DAIOStatus, DAIOWorkItem
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore


def completed_work(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"stdout": "Hello"}), encoding="utf-8")
    return DAIOWorkItem(
        work_id="work-generic-hello",
        project_root=str(tmp_path),
        change_id="HELLO",
        status=DAIOStatus.COMPLETED,
        execution_attempt_id="attempt-b",
        fencing_token=7,
        work_revision=11,
        architect_endpoint={
            "project_id": "project-generic",
            "conversation_id": "conversation-origin",
            "routing_policy": "EXACT_CONVERSATION",
        },
        metadata={
            "last_execution_report": "Connectivity payload passed",
            "completion_evidence_path": "evidence.json",
        },
    )


def test_completion_is_durable_idempotent_and_contains_stdout(tmp_path):
    store = SqliteDAIOWorkStore(str(tmp_path / "state.db"))
    bridge = MockArchitectBridgeAdapter()
    work = completed_work(tmp_path)

    assert asyncio.run(deliver_user_visible_completion(store, bridge, work))
    assert asyncio.run(deliver_user_visible_completion(store, bridge, work))

    assert len(bridge.completion_history) == 1
    delivery_id, message = bridge.completion_history[0]
    assert delivery_id
    assert "work-generic-hello" in message
    assert "stdout: `Hello`" in message
    conn = store._get_connection()
    row = conn.execute(
        "select status, project_id, conversation_id from daio_user_visible_deliveries"
    ).fetchone()
    assert tuple(row) == ("DELIVERED", "project-generic", "conversation-origin")


def test_wrong_or_ambiguous_origin_fails_closed(tmp_path):
    store = SqliteDAIOWorkStore(str(tmp_path / "state.db"))
    bridge = MockArchitectBridgeAdapter()
    work = completed_work(tmp_path)
    work.architect_endpoint.pop("conversation_id")

    try:
        asyncio.run(deliver_user_visible_completion(store, bridge, work))
    except ValueError as ex:
        assert "conversation_id" in str(ex)
    else:
        raise AssertionError("missing exact origin must fail closed")
    assert bridge.completion_history == []


def test_new_revision_has_new_delivery_identity(tmp_path):
    store = SqliteDAIOWorkStore(str(tmp_path / "state.db"))
    bridge = MockArchitectBridgeAdapter()
    work = completed_work(tmp_path)
    asyncio.run(deliver_user_visible_completion(store, bridge, work))
    work.work_revision += 1
    asyncio.run(deliver_user_visible_completion(store, bridge, work))
    assert len(bridge.completion_history) == 2
