"""
DAIO Autonomous Supervisor & Queue / Watchdog Daemon.
Integrates Work Queue Poller, Successor/Handoff Watchdog, Worker Liveness, and Progress Monitors.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
import hashlib
from typing import Any, Dict, List, Optional
import uuid

from .models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    HandoffState,
    HandoffWatch,
    SupervisorHeartbeat,
    is_terminal_phase,
)
from .store import DAIOWorkStore, SqliteDAIOWorkStore
from .watchdog import DAIOHandoffWatchdog
from .worker import DAIOPersistentWorker
from .orchestrator import DAIOClosedLoopOrchestrator
from .adapters.executor import EngineeringExecutorAdapter, SubprocessWorkspaceExecutor
from .adapters.bridge import ArchitectBridgeAdapter, ChromeCDPBridgeAdapter, MockArchitectBridgeAdapter
from .adapters.factory import create_engineering_agent_adapter

logger = logging.getLogger("DAIO_Supervisor")


class DAIOSupervisor:
    """
    Long-lived autonomous supervisor daemon.
    Runs background polling, watchdog evaluations, worker execution, and automated stall recovery.
    """

    def __init__(
        self,
        project_root: str,
        store: Optional[DAIOWorkStore] = None,
        executor: Optional[EngineeringExecutorAdapter] = None,
        bridge: Optional[ArchitectBridgeAdapter] = None,
        supervisor_id: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        lease_ttl_seconds: int = 300,
        watchdog_discovery_timeout: float = 30.0,
        watchdog_claim_timeout: float = 45.0,
        watchdog_progress_timeout: float = 120.0,
        max_recovery_attempts: int = 3,
        default_test_command: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.supervisor_id = supervisor_id or f"supervisor-{uuid.uuid4().hex[:6]}"
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_ttl_seconds = lease_ttl_seconds
        self.default_test_command = default_test_command
        self._running = False

        # Resolve store
        if store:
            self.store = store
        else:
            db_file = self.project_root / "_daio" / "daio_work.db"
            if not db_file.exists():
                db_file = self.project_root / "_daio" / "daio_work_state.db"
            self.store = SqliteDAIOWorkStore(db_path=str(db_file))

        # Resolve config
        config_file = self.project_root / "_daio" / "daio_config.json"
        if not config_file.exists():
            config_file = self.project_root / "daio_config.json"

        endpoint_config = {}
        cdp_port = 9222
        agent_provider = "AUTO"
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                endpoint_config = cfg.get("architect_endpoint", {})
                cdp_port = cfg.get("cdp_port", cdp_port)
                if not self.default_test_command:
                    self.default_test_command = cfg.get("test_gate_command")
                agent_provider = cfg.get("provider", "AUTO")
            except Exception as ex:
                logger.warning(f"Could not load config file {config_file}: {ex}")

        # Resolve executor
        if executor:
            self.executor = executor
        else:
            agent = create_engineering_agent_adapter({"provider": agent_provider})
            self.executor = SubprocessWorkspaceExecutor(project_root=str(self.project_root), agent_adapter=agent)

        # Resolve bridge
        if bridge:
            self.bridge = bridge
        else:
            self.bridge = ChromeCDPBridgeAdapter(endpoint=endpoint_config, cdp_port=cdp_port)

        self.orchestrator = DAIOClosedLoopOrchestrator(
            store=self.store,
            executor=self.executor,
            bridge=self.bridge,
            default_test_command=self.default_test_command,
        )

        self.worker = DAIOPersistentWorker(
            project_root=str(self.project_root),
            store=self.store,
            executor=self.executor,
            bridge=self.bridge,
            worker_id=f"worker-{self.supervisor_id}",
            poll_interval_seconds=poll_interval_seconds,
            lease_ttl_seconds=lease_ttl_seconds,
            default_test_command=self.default_test_command,
        )

        self.watchdog = DAIOHandoffWatchdog(
            store=self.store,
            project_root=str(self.project_root),
            orchestrator=self.orchestrator,
            bridge=self.bridge,
            discovery_timeout_seconds=watchdog_discovery_timeout,
            claim_timeout_seconds=watchdog_claim_timeout,
            progress_timeout_seconds=watchdog_progress_timeout,
            max_recovery_attempts=max_recovery_attempts,
        )

        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.pid = os.getpid()

    def stop(self) -> None:
        """Signal the supervisor to stop."""
        logger.info(f"🛑 Stopping DAIOSupervisor ({self.supervisor_id})...")
        self._running = False
        self.worker.stop()
        try:
            hb = self.store.load_supervisor_heartbeat(self.supervisor_id)
            if hb:
                hb.status = "STOPPED"
                hb.last_heartbeat_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self.store.record_supervisor_heartbeat(hb)
        except Exception:
            pass

    async def run_tick(self) -> Dict[str, Any]:
        """
        Execute one complete supervisor tick:
        1. Auto-register watches for completed works with authorized next_phase.
        2. Evaluate active watchdog monitors & execute bounded stall recoveries.
        3. Poll and process next available work item.
        4. Update durable supervisor heartbeat.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now.isoformat()

        # 1. Register watches for any completed items with unmonitored next_phase
        all_items = self.store.list_work_items()
        queue_depth = len([it for it in all_items if it.status in {DAIOStatus.QUEUED, DAIOStatus.AWAITING_REVIEW, DAIOStatus.IN_PROGRESS}])

        for it in all_items:
            if it.status == DAIOStatus.COMPLETED and it.authorized_next_phase:
                if not is_terminal_phase(it.authorized_next_phase):
                    self.watchdog.register_handoff(
                        parent_work=it,
                        expected_next_phase=it.authorized_next_phase,
                        now=now,
                    )

        # 2. Evaluate active watches and recover any stalls
        watch_results = self.watchdog.evaluate_watches(now=now)

        # 2b. Recover any unapplied Architect decisions on blocked/gated items
        for it in all_items:
            if it.status in {DAIOStatus.HUMAN_GATE_REQUIRED, DAIOStatus.BLOCKED}:
                last_dec_meta = it.metadata.get("last_architect_decision", {}) if isinstance(it.metadata, dict) else {}
                turn_dec = None
                if hasattr(self.store, "get_turn_history_for_work"):
                    turns = self.store.get_turn_history_for_work(it.work_id)
                    for t in reversed(turns):
                        if t.get("role") == DAIORole.LEAD_ARCHITECT_REVIEW.value and isinstance(t.get("payload"), dict):
                            turn_dec = t.get("payload")
                            break

                eff_dec = turn_dec or last_dec_meta
                if (
                    eff_dec.get("decision") == "REVISE"
                    and eff_dec.get("action") == "RUN"
                    and not eff_dec.get("human_approval_required", False)
                ):
                    inst_clean = (eff_dec.get("instruction") or "Recovered REVISE execution").strip()
                    dec_hash = hashlib.sha256(f"{it.work_id}:REVISE:{eff_dec.get('current_phase', it.change_id)}:RUN:{inst_clean}".encode()).hexdigest()[:12]
                    if hasattr(self.store, "is_decision_applied") and not self.store.is_decision_applied(dec_hash):
                        logger.info(f"🔄 Recovering unapplied Architect REVISE decision for {it.work_id} (hash={dec_hash})")
                        dec = ArchitectDecision(
                            decision="REVISE",
                            current_phase=eff_dec.get("current_phase", it.change_id),
                            next_phase=eff_dec.get("next_phase"),
                            action=eff_dec.get("action", "RUN"),
                            human_approval_required=False,
                            instruction=inst_clean,
                        )
                        await self.orchestrator.process_incoming_architect_decision(it.work_id, dec)

        # 3. Worker polling & execution
        worker_result = await self.worker.run_once()

        # 4. Record durable supervisor heartbeat
        last_prog = now_iso if worker_result else None
        hb = SupervisorHeartbeat(
            supervisor_id=self.supervisor_id,
            pid=self.pid,
            project_root=str(self.project_root),
            status="RUNNING",
            started_at=self.started_at,
            last_heartbeat_at=now_iso,
            last_bridge_heartbeat_at=now_iso if self.bridge else None,
            last_agent_heartbeat_at=now_iso if self.executor else None,
            last_progress_at=last_prog,
            active_work_id=worker_result.work_id if worker_result else self.worker._active_work_id,
            queue_depth=queue_depth,
            metadata={"watch_count": len(watch_results)}
        )
        try:
            self.store.record_supervisor_heartbeat(hb)
        except Exception as ex:
            logger.warning(f"Could not record supervisor heartbeat: {ex}")

        return {
            "supervisor_id": self.supervisor_id,
            "timestamp": now_iso,
            "watch_evaluations": watch_results,
            "worker_processed_item": worker_result.work_id if worker_result else None,
        }

    async def start(self, max_iterations: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Start the supervisor continuous monitoring loop.
        """
        self._running = True
        tick_history: List[Dict[str, Any]] = []
        iterations = 0

        logger.info(f"🚀 DAIOSupervisor STARTED: id={self.supervisor_id}, pid={self.pid}, root={self.project_root}")

        try:
            while self._running:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                try:
                    res = await self.run_tick()
                    tick_history.append(res)
                    if not res.get("worker_processed_item"):
                        await asyncio.sleep(self.poll_interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in supervisor tick: {e}", exc_info=True)
                    await asyncio.sleep(self.poll_interval_seconds)
        finally:
            self._running = False
            logger.info(f"🛑 DAIOSupervisor EXITED: id={self.supervisor_id}, ticks={len(tick_history)}")

        return tick_history

    def get_status(self) -> str:
        """Get formatted supervisor status summary with full telemetry."""
        watchdog_summary = self.watchdog.get_status_summary()
        items = self.store.list_work_items()
        queue_depth = len([it for it in items if it.status in {DAIOStatus.QUEUED, DAIOStatus.AWAITING_REVIEW, DAIOStatus.IN_PROGRESS}])
        active_items = [it for it in items if it.status == DAIOStatus.IN_PROGRESS]
        active_work_desc = ", ".join([it.work_id for it in active_items]) if active_items else "NONE"

        hb = self.store.load_supervisor_heartbeat(self.supervisor_id)
        hb_age_s = "UNKNOWN"
        last_bridge = "UNKNOWN"
        last_agent = "UNKNOWN"
        last_prog = "UNKNOWN"

        if hb:
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            hb_dt = datetime.datetime.fromisoformat(hb.last_heartbeat_at)
            hb_age_s = f"{int((now_dt - hb_dt).total_seconds())}s ago"
            last_bridge = hb.last_bridge_heartbeat_at or "NONE"
            last_agent = hb.last_agent_heartbeat_at or "NONE"
            last_prog = hb.last_progress_at or "NONE"

        summary = [
            f"=== DAIO SUPERVISOR STATUS ===",
            f"Supervisor ID           : {self.supervisor_id} (PID: {self.pid})",
            f"Supervisor Heartbeat    : {hb_age_s}",
            f"Worker State            : {'ACTIVE' if self._running else 'IDLE'}",
            f"Queue Depth             : {queue_depth}",
            f"Active Work             : {active_work_desc}",
            f"Last Bridge Heartbeat   : {last_bridge}",
            f"Last AntigravityCLI HB  : {last_agent}",
            f"Last Progress Timestamp : {last_prog}",
            "",
            watchdog_summary,
        ]
        return "\n".join(summary)


async def run_supervisor(
    project_root: str,
    supervisor_id: Optional[str] = None,
    poll_interval_seconds: float = 2.0,
    max_iterations: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Top-level entry point to run supervisor in a target project."""
    supervisor = DAIOSupervisor(
        project_root=project_root,
        supervisor_id=supervisor_id,
        poll_interval_seconds=poll_interval_seconds,
    )
    return await supervisor.start(max_iterations=max_iterations)
