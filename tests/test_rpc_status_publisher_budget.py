"""Acceptance tests for quota-safe RPC-1 status publication."""

import asyncio
import datetime
import io
import json
from types import SimpleNamespace
from unittest.mock import patch
import urllib.error

from scripts.daio_closed_loop.adapters.rpc_status_publisher import DAIOStatusPublisher
from scripts.daio_closed_loop.models import (
    DAIOProjectStatusResponse,
    DurablePlaneStatus,
    FreshnessEnum,
    LivePlaneStatus,
)
from scripts.daio_closed_loop.supervisor import DAIOSupervisor


class _Response:
    def __init__(self, code=200, body=b'{"status":"OK"}'):
        self.code = code
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.code

    def read(self):
        return self.body


class _Collector:
    def __init__(self):
        self.active_work_id = None
        self.host_status = "ONLINE"

    def collect_status(self):
        return DAIOProjectStatusResponse(
            live_plane=LivePlaneStatus(
                project_name="DAIO",
                host="mac",
                host_status=self.host_status,
                freshness=FreshnessEnum.FRESH,
                supervisor_running=True,
                active_work_id=self.active_work_id,
            ),
            durable_plane=DurablePlaneStatus(
                repository="repo",
                local_head_sha="abc123",
                push_synchronized=True,
            ),
            provenance={"protocol_version": "daio-rpc/v1", "server_timestamp": "volatile"},
        )


def _publisher(collector):
    return DAIOStatusPublisher(
        collector=collector,
        relay_url="https://relay.example",
        publish_token="token",
        interval_seconds=300,
        backoff_base_seconds=30,
        backoff_max_seconds=120,
    )


def test_heartbeat_throttling_and_unchanged_state_suppression():
    collector = _Collector()
    publisher = _publisher(collector)
    with patch(
        "urllib.request.urlopen", return_value=_Response()
    ) as urlopen:
        assert publisher.publish_once(now_monotonic=0)[0] is True
        assert publisher.publish_once(now_monotonic=1)[0] is False
        assert "Suppressed unchanged" in publisher.publish_once(now_monotonic=1)[1]
        assert publisher.publish_once(now_monotonic=300)[0] is True
        assert urlopen.call_count == 2


def test_material_state_change_publishes_immediately():
    collector = _Collector()
    publisher = _publisher(collector)
    with patch("urllib.request.urlopen", return_value=_Response()) as urlopen:
        assert publisher.publish_once(now_monotonic=0)[0] is True
        collector.active_work_id = "daio-root-1"
        assert publisher.publish_once(now_monotonic=1)[0] is True
        collector.host_status = "OFFLINE"
        assert publisher.publish_once(now_monotonic=2)[0] is True
        assert urlopen.call_count == 3


def test_quota_error_uses_bounded_backoff_and_recovers():
    collector = _Collector()
    publisher = _publisher(collector)
    quota_error = urllib.error.HTTPError(
        url="https://relay.example/api/v1/publish",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"KV put() limit exceeded for the day."}'),
    )
    with patch("urllib.request.urlopen", side_effect=[quota_error, _Response()]) as urlopen:
        ok, detail, _ = publisher.publish_once(now_monotonic=0)
        assert ok is False
        assert "KV put" in detail
        assert publisher.remote_status_degraded is True
        blocked = publisher.publish_once(now_monotonic=1)
        assert blocked[0] is False
        assert "backoff active" in blocked[1]
        recovered = publisher.publish_once(now_monotonic=30)
        assert recovered[0] is True
        assert publisher.remote_status_degraded is False
        assert urlopen.call_count == 2


def test_local_supervisor_continues_when_remote_status_fails():
    class _Store:
        def list_work_items(self):
            return []

        def record_supervisor_heartbeat(self, _heartbeat):
            return None

    class _Inbox:
        def poll_and_ingest(self, **_kwargs):
            return []

    class _Watchdog:
        def evaluate_watches(self, **_kwargs):
            return []

        def get_status_summary(self):
            return "watchdog"

    class _Worker:
        _active_work_id = None

        async def run_once(self):
            return None

    class _FailingPublisher:
        remote_status_degraded = True
        last_failure_detail = "quota"

        def publish_once(self):
            raise RuntimeError("remote status unavailable")

    supervisor = object.__new__(DAIOSupervisor)
    supervisor.project_root = SimpleNamespace()
    supervisor.supervisor_id = "test-supervisor"
    supervisor.poll_interval_seconds = 0.01
    supervisor.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    supervisor.pid = 1
    supervisor.inbox = _Inbox()
    supervisor.store = _Store()
    supervisor.watchdog = _Watchdog()
    supervisor.remote_relay_adapter = None
    supervisor.worker = _Worker()
    supervisor.bridge = object()
    supervisor.executor = object()
    supervisor.status_publisher = _FailingPublisher()

    result = asyncio.run(supervisor.run_tick())
    assert result["worker_processed_item"] is None
