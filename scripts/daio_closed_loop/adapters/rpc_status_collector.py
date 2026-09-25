"""
Generic DAIO RPC Status Collector (Remote Project Cockpit Access Adapter).
Collects read-only Two-Plane project state from canonical DAIO WorkStore and Git.
"""

from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any, Dict, List, Optional

from ..models import (
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
from ..store import DAIOWorkStore, SqliteDAIOWorkStore


class DAIOStatusCollector:
    """
    Read-only adapter collecting canonical live and durable DAIO project state.
    Strictly domain-neutral: zero business-logic dependencies.
    """

    def __init__(
        self,
        project_root: str,
        store: Optional[DAIOWorkStore] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self._store = store
        self._config = config or self._load_daio_config()

    def _load_daio_config(self) -> Dict[str, Any]:
        """Loads generic configuration from _daio/daio_config.json if present."""
        cfg_path = self.project_root / "_daio" / "daio_config.json"
        if cfg_path.exists():
            try:
                return json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _get_store(self) -> Optional[DAIOWorkStore]:
        """Lazily initializes read-only SqliteDAIOWorkStore if not explicitly provided."""
        if self._store is not None:
            return self._store

        candidates = [
            self.project_root / "_daio" / "daio_work.db",
            self.project_root / "_daio" / "daio_work_state.db",
        ]
        for db_file in candidates:
            if db_file.exists():
                try:
                    self._store = SqliteDAIOWorkStore(db_path=str(db_file))
                    return self._store
                except Exception:
                    pass
        return None

    def _is_pid_alive(self, pid: Optional[int]) -> bool:
        """Verifies if a process PID is currently alive on the host OS."""
        if pid is None or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError, PermissionError):
            return False

    def collect_live_plane(self, current_time: Optional[datetime.datetime] = None) -> LivePlaneStatus:
        """
        Collects live plane execution telemetry from the canonical DAIO WorkStore.
        Evaluates real freshness and enforces running-state invariants.
        """
        host_name = platform.node() or "unknown-host"
        project_name = self._config.get("project_name") or self.project_root.name

        store = self._get_store()
        if store is None:
            return LivePlaneStatus(
                project_name=project_name,
                host=host_name,
                host_status="UNKNOWN",
                freshness=FreshnessEnum.UNKNOWN,
                supervisor_running=False,
                degraded_note="No active DAIO database found at project root.",
            )

        # 1. Retrieve supervisor heartbeat
        supervisors = store.list_active_supervisors()
        latest_hb: Optional[SupervisorHeartbeat] = supervisors[0] if supervisors else None
        if latest_hb is None:
            latest_hb = store.load_supervisor_heartbeat()

        # 2. Check process liveness
        pid_alive = False
        reported_pid = None
        hb_timestamp = None

        if latest_hb:
            reported_pid = latest_hb.pid
            pid_alive = self._is_pid_alive(reported_pid)
            hb_timestamp = latest_hb.last_heartbeat_at

        # 3. Evaluate Freshness
        freshness, age_sec = evaluate_freshness(
            heartbeat_timestamp=hb_timestamp,
            current_time=current_time,
            is_supervisor_running=pid_alive,
        )

        # 4. Determine authoritative running status & host status
        is_running = False
        host_status = "UNKNOWN"
        degraded_note = None

        if freshness == FreshnessEnum.FRESH and pid_alive:
            is_running = True
            host_status = "ONLINE"
        elif freshness == FreshnessEnum.STALE:
            is_running = pid_alive
            host_status = "ONLINE" if pid_alive else "STALE"
            degraded_note = f"Supervisor heartbeat is stale ({age_sec}s ago). Live iteration unconfirmed."
        elif freshness == FreshnessEnum.OFFLINE:
            is_running = False
            host_status = "OFFLINE"
            degraded_note = f"Supervisor is offline (age: {age_sec}s, pid_alive: {pid_alive})."
        else:
            is_running = False
            host_status = "UNKNOWN"
            degraded_note = "Heartbeat telemetry uninitialized or cannot be established."

        # 5. Retrieve active work items & human gate state
        items: List[DAIOWorkItem] = store.list_work_items()
        active_item: Optional[DAIOWorkItem] = None
        queue_depth = len(items)

        # Look for in-progress or human gate work items
        for w in items:
            if w.status in (DAIOStatus.IN_PROGRESS, DAIOStatus.HUMAN_GATE_REQUIRED):
                active_item = w
                break
        if active_item is None and items:
            active_item = items[0]

        active_work_id = active_item.work_id if active_item else None
        active_work_name = active_item.change_id if active_item else None
        current_phase = active_item.current_stage if active_item else None
        current_gate = active_item.current_gate.value if active_item else None
        assigned_role = active_item.assigned_role.value if active_item else None
        human_gate_req = False
        human_gate_reason = None

        if active_item:
            human_gate_req = (
                active_item.status == DAIOStatus.HUMAN_GATE_REQUIRED
                or active_item.current_gate == DAIOGate.HUMAN_GATE
                or active_item.assigned_role == DAIORole.HUMAN_PROJECT_OWNER
            )
            human_gate_reason = active_item.human_gate_reason

        # 6. Retrieve active recovery epoch / handoff watch
        watches = store.list_active_handoff_watches()
        active_epoch = watches[0].recovery_epoch_id if watches else None

        return LivePlaneStatus(
            project_name=project_name,
            host=host_name,
            host_status=host_status,
            freshness=freshness,
            last_heartbeat_timestamp=hb_timestamp,
            heartbeat_age_seconds=age_sec,
            supervisor_running=is_running,
            supervisor_pid=reported_pid if is_running else None,
            active_work_id=active_work_id,
            active_work_item=active_work_name,
            current_phase=current_phase,
            current_gate=current_gate,
            assigned_role=assigned_role,
            human_gate_required=human_gate_req,
            human_gate_reason=human_gate_reason,
            recovery_epoch_id=active_epoch,
            active_agent="Antigravity",
            queue_depth=queue_depth,
            degraded_note=degraded_note,
        )

    def _run_git(self, args: List[str]) -> Optional[str]:
        """Runs a read-only git command in project root."""
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return res.stdout.strip()
            return None
        except Exception:
            return None

    def collect_durable_plane(self) -> DurablePlaneStatus:
        """
        Collects durable plane state directly from the local Git repository.
        Truthfully calculates commit SHA, push synchronization, and working-tree cleanliness.
        """
        # 1. Local HEAD SHA & Branch
        head_sha = self._run_git(["rev-parse", "HEAD"])
        git_branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])

        # 2. Remote repository URL & origin SHA
        remote_url = self._run_git(["config", "--get", "remote.origin.url"])
        repo_name = None
        if remote_url:
            # Extract owner/repo cleanly from https or ssh url
            clean_url = remote_url.replace(".git", "")
            if ":" in clean_url and not clean_url.startswith("http"):
                repo_name = clean_url.split(":")[-1]
            elif "github.com/" in clean_url:
                repo_name = clean_url.split("github.com/")[-1]
            else:
                repo_name = clean_url

        remote_sha = self._run_git(["rev-parse", f"origin/{git_branch}"]) if git_branch else None
        if not remote_sha:
            remote_sha = self._run_git(["rev-parse", "@{u}"])

        # 3. Working tree status
        status_porcelain = self._run_git(["status", "--porcelain"])
        working_tree_clean = (status_porcelain == "") if status_porcelain is not None else False

        # 4. Ahead / Behind count
        ahead_count = 0
        behind_count = 0
        counts = self._run_git(["rev-list", "--left-right", "--count", f"HEAD...origin/{git_branch}"]) if git_branch else None
        if counts:
            parts = counts.split()
            if len(parts) == 2:
                try:
                    ahead_count = int(parts[0])
                    behind_count = int(parts[1])
                except ValueError:
                    pass

        # 5. Push synchronization calculation
        push_sync = (
            bool(head_sha and remote_sha and head_sha == remote_sha)
            and working_tree_clean
            and (ahead_count == 0)
        )

        # 6. Latest durable milestone / completed change
        # Derives from commit message if available or configured milestone
        last_commit_msg = self._run_git(["log", "-1", "--pretty=%B"])
        latest_change = None
        if last_commit_msg:
            first_line = last_commit_msg.strip().split("\n")[0]
            latest_change = first_line[:80]

        return DurablePlaneStatus(
            repository=repo_name or self._config.get("repository"),
            git_branch=git_branch,
            local_head_sha=head_sha,
            remote_origin_sha=remote_sha,
            ahead_count=ahead_count,
            behind_count=behind_count,
            working_tree_clean=working_tree_clean,
            push_synchronized=push_sync,
            latest_durable_milestone=f"HEAD {head_sha[:7]}" if head_sha else None,
            latest_completed_change=latest_change,
        )

    def collect_status(self, current_time: Optional[datetime.datetime] = None) -> DAIOProjectStatusResponse:
        """Collects canonical Two-Plane status response with provenance metadata."""
        live = self.collect_live_plane(current_time=current_time)
        durable = self.collect_durable_plane()

        now_iso = (current_time or datetime.datetime.now(datetime.timezone.utc)).isoformat()
        provenance = {
            "protocol_version": "daio-rpc/v1",
            "collector": "DAIOStatusCollector",
            "collected_at": now_iso,
            "project_root": str(self.project_root),
        }

        return DAIOProjectStatusResponse(
            live_plane=live,
            durable_plane=durable,
            provenance=provenance,
        )
