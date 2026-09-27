"""
macOS launchd Persistent User Service Lifecycle Manager for DAIO (Milestone C1.2).

Provides out-of-band persistent service management completely decoupled from Antigravity IDE:
- Generates secure ~/Library/LaunchAgents/com.daio.supervisor.<project_id>.plist
- Never embeds secrets/tokens in plaintext inside plist (uses secure config/env)
- Bounded restart policy (KeepAlive with crash restart, clean exit termination)
- Supports install, start, stop, restart, status, and uninstall actions
- Maintains durable PID, heartbeat, and log telemetry in _daio/evidence/
"""

from __future__ import annotations
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("DAIO_Service")

DEFAULT_SERVICE_DOMAIN = "com.daio.supervisor"


@dataclass
class ServiceStatusResult:
    label: str
    installed: bool
    running: bool
    pid: Optional[int] = None
    last_exit_code: Optional[int] = None
    plist_path: Optional[str] = None
    log_path: Optional[str] = None
    supervisor_heartbeat_age: Optional[str] = None
    details: Dict[str, Any] = None


class MacOSLaunchdServiceManager:
    """
    Manages user-level macOS launchd agent lifecycle for DAIOSupervisor.
    """

    def __init__(self, project_root: str | Path, service_label: Optional[str] = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.project_id = self._resolve_project_id()
        self.label = service_label or f"{DEFAULT_SERVICE_DOMAIN}.{self.project_id}"
        self.launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        self.plist_path = self.launch_agents_dir / f"{self.label}.plist"
        self.evidence_dir = self.project_root / "_daio" / "evidence"
        self.log_path = self.evidence_dir / "supervisor_service.log"
        self.err_log_path = self.evidence_dir / "supervisor_service.err.log"

    def _resolve_project_id(self) -> str:
        """Resolves project ID from daio_config.json or directory name."""
        cfg_file = self.project_root / "_daio" / "daio_config.json"
        if not cfg_file.exists():
            cfg_file = self.project_root / "daio_config.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                p_id = cfg.get("project_id") or cfg.get("project_name")
                if p_id:
                    return str(p_id).replace(" ", "-").lower()
            except Exception:
                pass
        return self.project_root.name.replace(" ", "-").lower()

    def generate_plist_dict(self, python_executable: Optional[str] = None) -> Dict[str, Any]:
        """
        Builds canonical launchd plist dictionary.
        Security: Secrets/tokens are strictly excluded from plist payload.
        """
        py_exec = python_executable or sys.executable

        # Resolve runner script
        runner_script = self.project_root / "_daio" / "scripts" / "run_rpc3e_supervisor.py"
        if not runner_script.exists():
            runner_script = self.project_root / "scripts" / "run_rpc3e_supervisor.py"
        if not runner_script.exists():
            # Module execution fallback
            args = [py_exec, "-m", "scripts.daio_closed_loop.supervisor"]
        else:
            args = [py_exec, str(runner_script)]

        # Environment variables (PATH, PYTHONPATH, HOME only - NO TOKENS)
        env_vars = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
            "HOME": str(Path.home()),
            "PYTHONUNBUFFERED": "1",
            "PROJECT_ROOT": str(self.project_root),
        }
        if "PYTHONPATH" in os.environ:
            env_vars["PYTHONPATH"] = os.environ["PYTHONPATH"]

        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        plist_data = {
            "Label": self.label,
            "ProgramArguments": args,
            "WorkingDirectory": str(self.project_root),
            "EnvironmentVariables": env_vars,
            "RunAtLoad": True,
            "KeepAlive": {
                "SuccessfulExit": False,
                "Crashed": True,
            },
            "StandardOutPath": str(self.log_path),
            "StandardErrorPath": str(self.err_log_path),
            "ProcessType": "Standard",
        }
        return plist_data

    def generate_plist_xml(self, python_executable: Optional[str] = None) -> str:
        """Generates XML plist string."""
        d = self.generate_plist_dict(python_executable=python_executable)
        return plistlib.dumps(d).decode("utf-8")

    def install(self, python_executable: Optional[str] = None, overwrite: bool = True) -> Path:
        """
        Installs the plist file to ~/Library/LaunchAgents/<label>.plist.
        """
        self.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        if self.plist_path.exists() and not overwrite:
            raise FileExistsError(f"Plist already exists at {self.plist_path}")

        xml_content = self.generate_plist_xml(python_executable=python_executable)
        self.plist_path.write_text(xml_content, encoding="utf-8")
        logger.info(f"✅ DAIO macOS LaunchAgent plist installed: {self.plist_path}")
        return self.plist_path

    def uninstall(self) -> bool:
        """Unloads and removes plist file."""
        self.stop()
        if self.plist_path.exists():
            self.plist_path.unlink()
            logger.info(f"🗑️ DAIO macOS LaunchAgent plist removed: {self.plist_path}")
            return True
        return False

    def start(self) -> Tuple[bool, str]:
        """
        Loads and starts service via launchctl.
        """
        if not self.plist_path.exists():
            self.install()

        uid = os.getuid()
        # Modern macOS 11+ launchctl bootstrap / load
        cmd = ["launchctl", "bootstrap", f"gui/{uid}", str(self.plist_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            logger.info(f"🚀 DAIO LaunchAgent started: {self.label}")
            return True, "Service bootstrapped successfully"

        # Fallback to legacy launchctl load for compatibility
        fallback_cmd = ["launchctl", "load", "-w", str(self.plist_path)]
        res_fb = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if res_fb.returncode == 0:
            logger.info(f"🚀 DAIO LaunchAgent loaded: {self.label}")
            return True, "Service loaded via fallback"

        err_msg = res.stderr or res_fb.stderr or "Unknown launchctl error"
        logger.warning(f"Could not load launchctl service: {err_msg}")
        return False, err_msg

    def stop(self) -> Tuple[bool, str]:
        """
        Unloads and stops service via launchctl.
        """
        uid = os.getuid()
        cmd = ["launchctl", "bootout", f"gui/{uid}/{self.label}"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            logger.info(f"🛑 DAIO LaunchAgent stopped: {self.label}")
            return True, "Service bootout successful"

        # Fallback legacy unload
        if self.plist_path.exists():
            cmd_fb = ["launchctl", "unload", str(self.plist_path)]
            res_fb = subprocess.run(cmd_fb, capture_output=True, text=True)
            if res_fb.returncode == 0:
                logger.info(f"🛑 DAIO LaunchAgent unloaded: {self.label}")
                return True, "Service unloaded via fallback"

        return False, res.stderr or "Service was not running"

    def restart(self) -> Tuple[bool, str]:
        """Restarts service."""
        self.stop()
        return self.start()

    def status(self) -> ServiceStatusResult:
        """
        Queries launchctl and durable supervisor database for complete service health.
        """
        installed = self.plist_path.exists()
        running = False
        pid: Optional[int] = None
        last_exit: Optional[int] = None
        details: Dict[str, Any] = {}

        if installed:
            uid = os.getuid()
            # Try launchctl print
            res = subprocess.run(["launchctl", "print", f"gui/{uid}/{self.label}"], capture_output=True, text=True)
            if res.returncode == 0:
                details["launchctl_print"] = res.stdout
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("pid = "):
                        try:
                            pid = int(line.split("=")[1].strip())
                            running = True
                        except Exception:
                            pass
                    elif line.startswith("last exit code = "):
                        try:
                            last_exit = int(line.split("=")[1].strip())
                        except Exception:
                            pass
            else:
                # Try launchctl list
                res_list = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
                if res_list.returncode == 0:
                    for line in res_list.stdout.splitlines():
                        if self.label in line:
                            parts = line.split()
                            if len(parts) >= 3:
                                if parts[0].isdigit():
                                    pid = int(parts[0])
                                    running = True
                                if parts[1].isdigit():
                                    last_exit = int(parts[1])

        # Check durable SQLite heartbeat
        hb_age = None
        db_file = self.project_root / "_daio" / "daio_work.db"
        if not db_file.exists():
            db_file = self.project_root / "_daio" / "daio_work_state.db"
        if db_file.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT last_heartbeat_at, pid, status FROM daio_supervisor_heartbeats ORDER BY last_heartbeat_at DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    import datetime
                    hb_dt = datetime.datetime.fromisoformat(row["last_heartbeat_at"])
                    now_dt = datetime.datetime.now(datetime.timezone.utc)
                    age_s = int((now_dt - hb_dt).total_seconds())
                    hb_age = f"{age_s}s ago"
                    if not pid and row["pid"]:
                        pid = row["pid"]
                    if age_s < 30:
                        running = True
                conn.close()
            except Exception:
                pass

        return ServiceStatusResult(
            label=self.label,
            installed=installed,
            running=running,
            pid=pid,
            last_exit_code=last_exit,
            plist_path=str(self.plist_path) if installed else None,
            log_path=str(self.log_path),
            supervisor_heartbeat_age=hb_age,
            details=details,
        )
