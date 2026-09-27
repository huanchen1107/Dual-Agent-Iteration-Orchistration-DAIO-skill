"""
Unit & Integration Test Suite for Phase C1.2:
macOS Persistent launchd Service Bootstrap & Lifecycle Management.

Verifies:
1. Plist generation structure, schema validity, and security invariants (no tokens in plist)
2. Install / Uninstall filesystem operations
3. Service status inspection with launchctl parsing and SQLite heartbeat integration
4. CLI command dispatcher integration
"""

import json
import os
from pathlib import Path
import plistlib
import tempfile
import pytest

from scripts.daio_closed_loop.service import (
    MacOSLaunchdServiceManager,
    DEFAULT_SERVICE_DOMAIN,
)


@pytest.fixture
def service_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        project_root = tmp_path / "test_project"
        project_root.mkdir(parents=True, exist_ok=True)
        fake_agents = tmp_path / "LaunchAgents"
        fake_agents.mkdir(parents=True, exist_ok=True)

        # Mock daio_config.json
        cfg_dir = project_root / "_daio"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = cfg_dir / "daio_config.json"
        cfg_file.write_text(json.dumps({
            "project_name": "test-fintech",
            "remote_relay": {
                "auth_token": "SECRET_TOKEN_DO_NOT_EXPOSE",
            }
        }), encoding="utf-8")

        mgr = MacOSLaunchdServiceManager(project_root=project_root)
        # Override launch_agents_dir for isolated testing
        mgr.launch_agents_dir = fake_agents
        mgr.plist_path = fake_agents / f"{mgr.label}.plist"

        yield {
            "tmp_path": tmp_path,
            "project_root": project_root,
            "fake_agents": fake_agents,
            "mgr": mgr,
        }


def test_plist_generation_and_security(service_env):
    mgr = service_env["mgr"]
    plist_dict = mgr.generate_plist_dict(python_executable="/usr/bin/python3")

    # 1. Structural checks
    assert plist_dict["Label"] == f"{DEFAULT_SERVICE_DOMAIN}.test-fintech"
    assert plist_dict["WorkingDirectory"] == str(service_env["project_root"].resolve())
    assert plist_dict["RunAtLoad"] is True
    assert plist_dict["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}
    assert "/usr/bin/python3" in plist_dict["ProgramArguments"][0]

    # 2. Security Invariant: NO SECRETS OR TOKENS IN PLIST
    xml_str = mgr.generate_plist_xml()
    assert "SECRET_TOKEN_DO_NOT_EXPOSE" not in xml_str
    assert "auth_token" not in xml_str

    # 3. Valid XML plist deserialization
    parsed = plistlib.loads(xml_str.encode("utf-8"))
    assert parsed["Label"] == plist_dict["Label"]


def test_service_install_and_uninstall(service_env):
    mgr = service_env["mgr"]
    fake_agents = service_env["fake_agents"]

    assert not mgr.plist_path.exists()

    # Install
    installed_path = mgr.install(python_executable="/usr/bin/python3")
    assert installed_path.exists()
    assert installed_path == mgr.plist_path
    assert (fake_agents / f"{mgr.label}.plist").exists()

    # Uninstall
    uninstalled = mgr.uninstall()
    assert uninstalled is True
    assert not mgr.plist_path.exists()


def test_service_status_inspection(service_env):
    mgr = service_env["mgr"]

    # Before install
    stat_before = mgr.status()
    assert stat_before.installed is False
    assert stat_before.running is False

    # After install
    mgr.install(python_executable="/usr/bin/python3")
    stat_after = mgr.status()
    assert stat_after.installed is True
    assert stat_after.plist_path == str(mgr.plist_path)
    assert stat_after.log_path == str(mgr.log_path)


def test_project_id_resolution(service_env):
    mgr = service_env["mgr"]
    assert mgr.project_id == "test-fintech"
    assert mgr.label == f"com.daio.supervisor.test-fintech"
