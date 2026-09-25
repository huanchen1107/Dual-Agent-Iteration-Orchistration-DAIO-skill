"""
Automated Test Suite for DAIO RPC-1 Status Collector and Two-Plane Models.
"""

import datetime
from pathlib import Path
import tempfile
import pytest

from scripts.daio_closed_loop.models import (
    DAIOGate,
    DAIOProjectStatusResponse,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    DurablePlaneStatus,
    FreshnessEnum,
    LivePlaneStatus,
    SupervisorHeartbeat,
    evaluate_freshness,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.adapters.rpc_status_collector import DAIOStatusCollector


def test_evaluate_freshness_thresholds():
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Fresh (<30s)
    ts_fresh = (now - datetime.timedelta(seconds=10)).isoformat()
    freshness, age = evaluate_freshness(ts_fresh, current_time=now, is_supervisor_running=True)
    assert freshness == FreshnessEnum.FRESH
    assert 9.0 <= age <= 11.0

    # 2. Stale (30s..180s)
    ts_stale = (now - datetime.timedelta(seconds=45)).isoformat()
    freshness, age = evaluate_freshness(ts_stale, current_time=now, is_supervisor_running=True)
    assert freshness == FreshnessEnum.STALE
    assert 44.0 <= age <= 46.0

    # 3. Offline (>180s)
    ts_offline = (now - datetime.timedelta(seconds=200)).isoformat()
    freshness, age = evaluate_freshness(ts_offline, current_time=now, is_supervisor_running=True)
    assert freshness == FreshnessEnum.OFFLINE
    assert age >= 199.0

    # 4. Offline due to supervisor not running
    freshness, age = evaluate_freshness(ts_fresh, current_time=now, is_supervisor_running=False)
    assert freshness == FreshnessEnum.OFFLINE

    # 5. Unknown due to missing or invalid timestamp
    assert evaluate_freshness(None)[0] == FreshnessEnum.UNKNOWN
    assert evaluate_freshness("invalid-date")[0] == FreshnessEnum.UNKNOWN


def test_collector_live_plane_with_active_supervisor():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "_daio" / "daio_work.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        store = SqliteDAIOWorkStore(db_path=str(db_path))

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        hb = SupervisorHeartbeat(
            supervisor_id="sup-test-1",
            pid=99999999,  # High PID unlikely to be running
            project_root=str(tmp_path),
            status="RUNNING",
            started_at=now_utc.isoformat(),
            last_heartbeat_at=now_utc.isoformat(),
        )
        store.record_supervisor_heartbeat(hb)

        # Add work item in HUMAN_GATE_REQUIRED
        work = DAIOWorkItem(
            work_id="work-001",
            project_root=str(tmp_path),
            change_id="change-test-01",
            current_stage="S3",
            current_gate=DAIOGate.HUMAN_GATE,
            assigned_role=DAIORole.HUMAN_PROJECT_OWNER,
            status=DAIOStatus.HUMAN_GATE_REQUIRED,
            human_gate_reason="Scope limit reached",
        )
        store.save_work_item(work)

        collector = DAIOStatusCollector(project_root=str(tmp_path), store=store)
        live = collector.collect_live_plane(current_time=now_utc)

        # Invariant: PID 99999999 is dead on OS, so supervisor_running must be False and OFFLINE
        assert live.supervisor_running is False
        assert live.freshness == FreshnessEnum.OFFLINE
        assert live.human_gate_required is True
        assert live.human_gate_reason == "Scope limit reached"
        assert live.active_work_id == "work-001"


def test_historical_running_suppression_when_stale_or_offline():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "_daio" / "daio_work.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        store = SqliteDAIOWorkStore(db_path=str(db_path))
        past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=300)

        # Supervisor was recorded as "RUNNING" 300s ago
        hb = SupervisorHeartbeat(
            supervisor_id="sup-stale",
            pid=12345,
            project_root=str(tmp_path),
            status="RUNNING",
            started_at=past_time.isoformat(),
            last_heartbeat_at=past_time.isoformat(),
        )
        store.record_supervisor_heartbeat(hb)

        collector = DAIOStatusCollector(project_root=str(tmp_path), store=store)
        live = collector.collect_live_plane()

        # Invariant: Must NOT report running=True when heartbeat is 300s old
        assert live.freshness == FreshnessEnum.OFFLINE
        assert live.supervisor_running is False
        assert live.host_status == "OFFLINE"
        assert "offline" in live.degraded_note.lower() or "expired" in live.degraded_note.lower()


def test_durable_plane_structure():
    collector = DAIOStatusCollector(project_root=".")
    durable = collector.collect_durable_plane()

    assert isinstance(durable.git_branch, str) or durable.git_branch is None
    assert isinstance(durable.working_tree_clean, bool)
    assert isinstance(durable.push_synchronized, bool)
    d_dict = durable.to_dict()
    assert "local_head_sha" in d_dict
    assert "push_synchronized" in d_dict
    assert "working_tree_clean" in d_dict


def test_domain_neutrality_in_rpc_adapters():
    collector_code = Path("scripts/daio_closed_loop/adapters/rpc_status_collector.py").read_text(encoding="utf-8")
    publisher_code = Path("scripts/daio_closed_loop/adapters/rpc_status_publisher.py").read_text(encoding="utf-8")

    forbidden = ["2330.TW", "SMC7S", "Pine", "_AwinFinTechHybridSystem_", "stock", "trading"]
    for token in forbidden:
        assert token not in collector_code, f"Leaked domain token '{token}' in rpc_status_collector.py"
        assert token not in publisher_code, f"Leaked domain token '{token}' in rpc_status_publisher.py"


def test_collector_read_only_safety():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "_daio" / "daio_work.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        store = SqliteDAIOWorkStore(db_path=str(db_path))
        collector = DAIOStatusCollector(project_root=str(tmp_path), store=store)

        # Query multiple times
        resp1 = collector.collect_status()
        resp2 = collector.collect_status()

        # Verify nothing mutated in store
        assert len(store.list_work_items()) == 0
        assert len(store.list_active_supervisors()) == 0
        assert resp1.live_plane.freshness == FreshnessEnum.UNKNOWN
        assert resp2.live_plane.freshness == FreshnessEnum.UNKNOWN
