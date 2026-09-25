import os
import json
import tempfile
import pytest
from pathlib import Path

from scripts.daio_closed_loop.adapters.agent_contract import AgentTaskRequest
from scripts.daio_closed_loop.adapters.antigravity_cli_agent import AntigravityCLIAdapter
from scripts.daio_closed_loop.adapters.factory import create_engineering_agent_adapter
from scripts.daio_closed_loop.watchdog import DAIOHandoffWatchdog
from scripts.daio_closed_loop.supervisor import DAIOSupervisor
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore


def test_agent_task_request_default_timeout():
    req = AgentTaskRequest(
        work_id="work-test-timeout",
        change_id="CHG-TIMEOUT",
        requested_action="Test action",
        project_root="/tmp/test",
    )
    assert req.timeout_seconds == 300, "AgentTaskRequest timeout must default to 300s"


def test_antigravity_cli_adapter_default_and_custom_timeout():
    adapter = AntigravityCLIAdapter()
    assert adapter.timeout_seconds == 300, "AntigravityCLIAdapter timeout must default to 300s"

    custom_adapter = AntigravityCLIAdapter(timeout_seconds=600)
    assert custom_adapter.timeout_seconds == 600


def test_factory_timeout_propagation():
    # Default without explicit timeout_seconds in cfg
    adapter = create_engineering_agent_adapter({"provider": "AGY"})
    assert isinstance(adapter, AntigravityCLIAdapter)
    assert adapter.timeout_seconds == 300, "Factory must default AGY adapter timeout to 300s"

    # Custom override via config
    custom_adapter = create_engineering_agent_adapter({"provider": "AGY", "timeout_seconds": 450})
    assert isinstance(custom_adapter, AntigravityCLIAdapter)
    assert custom_adapter.timeout_seconds == 450


def test_watchdog_progress_timeout_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        store = SqliteDAIOWorkStore(db_path=db_path)
        watchdog = DAIOHandoffWatchdog(store=store, project_root=tmpdir)
        assert watchdog.progress_timeout_seconds == 360.0, "Watchdog progress timeout must default to 360s"


def test_supervisor_timeout_propagation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        store = SqliteDAIOWorkStore(db_path=db_path)
        supervisor = DAIOSupervisor(project_root=tmpdir, store=store)
        assert supervisor.lease_ttl_seconds == 480, "Supervisor lease TTL must default to 480s"
        assert supervisor.watchdog.progress_timeout_seconds == 360.0, "Supervisor watchdog progress timeout must default to 360s"
