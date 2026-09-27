"""
Tests for DAIOSupervisor Daemon Process Lifecycle, Heartbeat Publishing, and Robust Detached Execution.
Verifies DAIO-DEFECT-RPC3E-002 resolution.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from scripts.daio_closed_loop.models import (
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.supervisor import (
    DAIOSupervisor,
    is_pid_alive,
    get_supervisor_daemon_status,
    stop_supervisor_daemon,
)
from scripts.daio_closed_loop.adapters.remote_relay import RemoteDecisionAdapter


def test_is_pid_alive_local_process():
    current_pid = os.getpid()
    assert is_pid_alive(current_pid) is True
    # Negative/invalid PID
    assert is_pid_alive(0) is False
    assert is_pid_alive(-1) is False
    assert is_pid_alive(99999999) is False


def test_supervisor_daemon_status_and_stop_lifecycle(tmp_path):
    # 1. Stopped state
    st = get_supervisor_daemon_status(str(tmp_path))
    assert st["running"] is False
    assert st["pid"] is None

    # 2. Simulated running PID file
    pid_file = tmp_path / "_daio" / "supervisor.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    my_pid = os.getpid()
    pid_file.write_text(str(my_pid), encoding="utf-8")

    st = get_supervisor_daemon_status(str(tmp_path))
    assert st["running"] is True
    assert st["pid"] == my_pid

    # 3. Clean stop removes PID file
    with patch("os.kill") as mock_kill:
        ok = stop_supervisor_daemon(str(tmp_path))
        assert ok is True
        assert pid_file.exists() is False


def test_supervisor_publishes_status_continuously_in_run_tick(tmp_path):
    """Proves supervisor automatically calls status_publisher.publish_once() during each tick."""
    async def _test():
        store = SqliteDAIOWorkStore(str(tmp_path / "daio_work.db"))
        mock_client = MagicMock()
        mock_client.endpoint_url = "https://mock-relay.workers.dev"
        mock_client.auth_token = "mock-secret-token"
        mock_client.poll_decisions.return_value = []

        adapter = RemoteDecisionAdapter(project_id="awin-fintech", client=mock_client)

        supervisor = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            remote_relay_adapter=adapter,
        )

        assert supervisor.status_publisher is not None

        # Mock publish_once on the status_publisher
        supervisor.status_publisher.publish_once = MagicMock(return_value=(True, "OK", None))

        tick_result = await supervisor.run_tick()
        assert tick_result["supervisor_id"] == supervisor.supervisor_id
        assert supervisor.status_publisher.publish_once.called is True

    asyncio.run(_test())


def test_supervisor_status_publishing_exception_is_non_fatal(tmp_path):
    """Proves remote network timeouts during live status publishing cannot crash the supervisor loop."""
    async def _test():
        store = SqliteDAIOWorkStore(str(tmp_path / "daio_work.db"))
        mock_client = MagicMock()
        mock_client.endpoint_url = "https://mock-relay.workers.dev"
        mock_client.auth_token = "mock-secret-token"
        mock_client.poll_decisions.return_value = []

        adapter = RemoteDecisionAdapter(project_id="awin-fintech", client=mock_client)

        supervisor = DAIOSupervisor(
            project_root=str(tmp_path),
            store=store,
            remote_relay_adapter=adapter,
        )

        # Force status_publisher to raise exception
        supervisor.status_publisher.publish_once = MagicMock(side_effect=RuntimeError("Cloudflare 504 Gateway Timeout"))

        # Must not raise exception
        tick_result = await supervisor.run_tick()
        assert tick_result["supervisor_id"] == supervisor.supervisor_id

    asyncio.run(_test())
