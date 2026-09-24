import os
import tempfile
import pytest
from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore

def test_sqlite_work_store_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "work.db")
        store = SqliteDAIOWorkStore(db_path=db_path)
        
        item = DAIOWorkItem(
            work_id="work-001",
            project_root=tmpdir,
            change_id="change-01",
            current_gate=DAIOGate.CONTRACT_GATE,
            assigned_role=DAIORole.LEAD_ARCHITECT_REVIEW,
            status=DAIOStatus.QUEUED,
            architect_endpoint={"provider": "CHATGPT_WEB", "conversation_id": "conv-test"}
        )
        store.save_work_item(item)
        
        loaded = store.load_work_item("work-001")
        assert loaded is not None
        assert loaded.work_id == "work-001"
        assert loaded.architect_endpoint["conversation_id"] == "conv-test"
        assert loaded.status == DAIOStatus.QUEUED

def test_sqlite_work_store_lease_locking():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "work.db")
        store = SqliteDAIOWorkStore(db_path=db_path)
        
        item = DAIOWorkItem(
            work_id="work-002",
            project_root=tmpdir,
            change_id="change-02",
            status=DAIOStatus.IN_PROGRESS
        )
        store.save_work_item(item)
        
        lease_id = store.acquire_lease("work-002", worker_id="worker-1", ttl_seconds=60)
        assert lease_id is not None
        
        # Second worker cannot acquire while valid
        lease_id_2 = store.acquire_lease("work-002", worker_id="worker-2", ttl_seconds=60)
        assert lease_id_2 is None
        
        # Release lease
        assert store.release_lease("work-002", lease_id) is True
        
        # Now worker 2 can acquire
        lease_id_2 = store.acquire_lease("work-002", worker_id="worker-2", ttl_seconds=60)
        assert lease_id_2 is not None
