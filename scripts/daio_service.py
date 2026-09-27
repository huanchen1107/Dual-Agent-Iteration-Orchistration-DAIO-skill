#!/usr/bin/env python3
"""
DAIO macOS Persistent Service CLI (Milestone C1.2).

Usage:
  python3 scripts/daio_service.py install   # Generate and install launchd plist
  python3 scripts/daio_service.py start     # Start persistent supervisor via launchctl
  python3 scripts/daio_service.py stop      # Stop persistent supervisor
  python3 scripts/daio_service.py restart   # Restart service
  python3 scripts/daio_service.py status    # Check service health, PID, and heartbeat
  python3 scripts/daio_service.py uninstall # Unload and delete LaunchAgent plist
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

# Add root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from scripts.daio_closed_loop.service import MacOSLaunchdServiceManager


def main() -> int:
    parser = argparse.ArgumentParser(description="DAIO macOS Persistent Service Manager (Milestone C1.2)")
    parser.add_argument(
        "action",
        choices=["install", "start", "stop", "restart", "status", "uninstall", "generate-plist"],
        help="Service lifecycle action",
    )
    parser.add_argument(
        "--root",
        default=str(root_dir),
        help="Project root directory (default: workspace root)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Custom launchd service label",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    args = parser.parse_args()
    mgr = MacOSLaunchdServiceManager(project_root=args.root, service_label=args.label)

    if args.action == "generate-plist":
        xml = mgr.generate_plist_xml()
        print(xml)
        return 0

    elif args.action == "install":
        p = mgr.install()
        if args.json:
            print(json.dumps({"success": True, "plist_path": str(p), "label": mgr.label}))
        else:
            print(f"✅ DAIO LaunchAgent installed: {p}")
            print(f"To start the service outside Antigravity IDE, run:")
            print(f"  python3 {__file__} start")
        return 0

    elif args.action == "start":
        ok, msg = mgr.start()
        if args.json:
            print(json.dumps({"success": ok, "message": msg, "label": mgr.label}))
        else:
            print(f"{'✅' if ok else '⚠️'} Start result: {msg}")
        return 0 if ok else 1

    elif args.action == "stop":
        ok, msg = mgr.stop()
        if args.json:
            print(json.dumps({"success": ok, "message": msg, "label": mgr.label}))
        else:
            print(f"{'✅' if ok else '⚠️'} Stop result: {msg}")
        return 0 if ok else 1

    elif args.action == "restart":
        ok, msg = mgr.restart()
        if args.json:
            print(json.dumps({"success": ok, "message": msg, "label": mgr.label}))
        else:
            print(f"{'✅' if ok else '⚠️'} Restart result: {msg}")
        return 0 if ok else 1

    elif args.action == "status":
        stat = mgr.status()
        if args.json:
            print(json.dumps({
                "label": stat.label,
                "installed": stat.installed,
                "running": stat.running,
                "pid": stat.pid,
                "last_exit_code": stat.last_exit_code,
                "plist_path": stat.plist_path,
                "log_path": stat.log_path,
                "supervisor_heartbeat_age": stat.supervisor_heartbeat_age,
            }, indent=2))
        else:
            print("=" * 60)
            print(f"DAIO macOS Persistent Service Status")
            print("=" * 60)
            print(f"Service Label        : {stat.label}")
            print(f"Installed Plist      : {stat.installed} ({stat.plist_path or 'NONE'})")
            print(f"Service Running      : {'🟢 YES' if stat.running else '🔴 NO'}")
            print(f"Service PID          : {stat.pid or 'NONE'}")
            print(f"Supervisor Heartbeat : {stat.supervisor_heartbeat_age or 'NONE'}")
            print(f"Service Log Path     : {stat.log_path}")
            print("=" * 60)
        return 0

    elif args.action == "uninstall":
        ok = mgr.uninstall()
        if args.json:
            print(json.dumps({"success": ok, "label": mgr.label}))
        else:
            print(f"🗑️ Service uninstalled: {mgr.label}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
