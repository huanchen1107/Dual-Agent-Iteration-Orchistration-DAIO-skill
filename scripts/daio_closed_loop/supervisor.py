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
import signal
import sys
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
from .adapters.factory import create_engineering_agent_adapter, create_architect_bridge_adapter
from .adapters.remote_relay import RemoteDecisionAdapter, RemoteDecisionRelayClient
from .adapters.rpc_status_collector import DAIOStatusCollector
from .adapters.rpc_status_publisher import DAIOStatusPublisher

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
        remote_relay_adapter: Optional[RemoteDecisionAdapter] = None,
        enable_remote_ingress: bool = True,
        supervisor_id: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        lease_ttl_seconds: int = 480,
        watchdog_discovery_timeout: float = 30.0,
        watchdog_claim_timeout: float = 45.0,
        watchdog_progress_timeout: float = 360.0,
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
        cfg_dict: Dict[str, Any] = {}
        if config_file.exists():
            try:
                cfg_dict = json.loads(config_file.read_text(encoding="utf-8"))
                endpoint_config = cfg_dict.get("architect_endpoint", {})
                cdp_port = cfg_dict.get("cdp_port", cdp_port)
                if not self.default_test_command:
                    self.default_test_command = cfg_dict.get("test_gate_command")
                agent_provider = cfg_dict.get("provider", "AUTO")
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
            arch_cfg = cfg_dict.get("architect", {})
            if "endpoint" not in arch_cfg and endpoint_config:
                arch_cfg["endpoint"] = endpoint_config
            if "cdp_port" not in arch_cfg and cdp_port:
                arch_cfg["cdp_port"] = cdp_port
            self.bridge = create_architect_bridge_adapter(arch_cfg)


        # Resolve remote relay adapter (RPC-2 / RPC-3 persistent ingress)
        if remote_relay_adapter:
            self.remote_relay_adapter = remote_relay_adapter
        elif enable_remote_ingress:
            self.remote_relay_adapter = self._init_remote_relay_adapter(cfg_dict)
        else:
            self.remote_relay_adapter = None

        # Resolve remote status publisher (keeps Cloudflare Cockpit FRESH & ONLINE)
        self.status_publisher: Optional[DAIOStatusPublisher] = None
        if self.remote_relay_adapter and getattr(self.remote_relay_adapter, "client", None):
            try:
                collector = DAIOStatusCollector(
                    project_root=str(self.project_root),
                    store=self.store,
                )
                self.status_publisher = DAIOStatusPublisher(
                    collector=collector,
                    relay_url=self.remote_relay_adapter.client.endpoint_url,
                    publish_token=self.remote_relay_adapter.client.auth_token,
                    interval_seconds=self.poll_interval_seconds,
                )
            except Exception as ex:
                logger.warning(f"Could not initialize DAIOStatusPublisher: {ex}")

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

    def _init_remote_relay_adapter(self, cfg: Dict[str, Any]) -> Optional[RemoteDecisionAdapter]:
        """Auto-configures RemoteDecisionAdapter from config or environment variables."""
        rr_cfg = cfg.get("remote_relay") if isinstance(cfg.get("remote_relay"), dict) else {}
        relay_url = (
            cfg.get("relay_url")
            or rr_cfg.get("endpoint_url")
            or os.environ.get("DAIO_RELAY_URL")
            or os.environ.get("DAIO_RPC_RELAY_URL")
        )
        relay_secret = (
            cfg.get("relay_secret")
            or rr_cfg.get("auth_token")
            or os.environ.get("DAIO_RELAY_SECRET")
            or os.environ.get("DAIO_RELAY_TOKEN")
            or os.environ.get("DAIO_RPC_PUBLISH_TOKEN")
        )
        project_id = (
            cfg.get("project_id")
            or cfg.get("project_name")
            or rr_cfg.get("project_id")
            or os.environ.get("DAIO_PROJECT_ID")
            or "awin-fintech"
        )

        if relay_url and relay_secret:
            try:
                client = RemoteDecisionRelayClient(
                    endpoint_url=relay_url,
                    project_id=project_id,
                    auth_token=relay_secret,
                )
                logger.info(f"🌐 Remote decision ingress poller initialized: {relay_url} (project: {project_id})")
                return RemoteDecisionAdapter(project_id=project_id, client=client)
            except Exception as ex:
                logger.warning(f"Could not initialize RemoteDecisionAdapter: {ex}")
        return None

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

        # 2c. Remote decision ingress polling (RPC-2 / RPC-3 persistent ingress)
        remote_decisions_processed = []
        if self.remote_relay_adapter:
            try:
                polled_envelopes = self.remote_relay_adapter.client.poll_decisions()
                for env in polled_envelopes:
                    logger.info(f"📥 Remote decision detected on edge: {env.decision_id} (work_id={env.work_id}, decision={env.decision})")
                    app_res = self.remote_relay_adapter.validate_and_apply(
                        envelope=env,
                        store=self.store,
                        project_root=str(self.project_root),
                        send_ack=True,
                    )
                    remote_decisions_processed.append({
                        "decision_id": env.decision_id,
                        "work_id": env.work_id,
                        "applied": app_res.applied,
                        "status": app_res.status,
                        "reason": app_res.reason,
                        "decision_hash": app_res.decision_hash,
                    })
            except Exception as ex:
                logger.warning(f"⚠️ Remote decision poller warning (non-fatal): {ex}")

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
            metadata={
                "watch_count": len(watch_results),
                "remote_ingress_configured": bool(self.remote_relay_adapter),
            }
        )
        try:
            self.store.record_supervisor_heartbeat(hb)
        except Exception as ex:
            logger.warning(f"Could not record supervisor heartbeat: {ex}")

        # 5. Continuous Live Status Publishing to Cloudflare Relay
        if self.status_publisher:
            try:
                self.status_publisher.publish_once()
            except Exception as ex:
                logger.debug(f"Cloudflare status publication non-fatal: {ex}")

        return {
            "supervisor_id": self.supervisor_id,
            "timestamp": now_iso,
            "watch_evaluations": watch_results,
            "remote_decisions_processed": remote_decisions_processed,
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


def is_pid_alive(pid: Optional[int]) -> bool:
    """Verifies if a process PID is currently alive on the host OS."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def start_supervisor_daemon(
    project_root: str,
    supervisor_id: Optional[str] = None,
    poll_interval_seconds: float = 2.0,
    pid_file: Optional[str] = None,
    log_file: Optional[str] = None,
) -> int:
    """
    Spawns DAIOSupervisor as a true detached double-fork UNIX daemon on macOS/Linux.
    Survives parent process and terminal termination.
    """
    root_p = Path(project_root).resolve()
    evidence_dir = root_p / "_daio" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    pid_path = Path(pid_file) if pid_file else root_p / "_daio" / "supervisor.pid"
    log_path = Path(log_file) if log_file else evidence_dir / "supervisor_daemon.log"

    # Check if already running
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
            if is_pid_alive(existing_pid):
                logger.info(f"Supervisor daemon already running with PID {existing_pid}")
                return existing_pid
        except Exception:
            pass

    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent returns first child PID
        return pid

    # First child: create new session
    os.setsid()
    os.umask(0)

    # Second fork: decouple from session leader
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Grandchild: write PID file and redirect stdio
    daemon_pid = os.getpid()
    pid_path.write_text(str(daemon_pid), encoding="utf-8")

    log_fp = open(log_path, "a", encoding="utf-8")
    os.dup2(log_fp.fileno(), sys.stdout.fileno())
    os.dup2(log_fp.fileno(), sys.stderr.fileno())
    try:
        devnull = open(os.devnull, "r")
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    except Exception:
        pass

    import signal

    def _handle_sigterm(signum, frame):
        logger.info(f"🛑 Received signal {signum}. Stopping supervisor daemon PID {daemon_pid}...")
        try:
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    logger.info(f"🌟 DAIOSupervisor daemon spawned: PID={daemon_pid}, log={log_path}")

    try:
        asyncio.run(run_supervisor(
            project_root=str(root_p),
            supervisor_id=supervisor_id,
            poll_interval_seconds=poll_interval_seconds,
        ))
    finally:
        try:
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass
        sys.exit(0)


def stop_supervisor_daemon(project_root: str, pid_file: Optional[str] = None) -> bool:
    """Stops the running supervisor daemon by PID."""
    import time
    root_p = Path(project_root).resolve()
    pid_path = Path(pid_file) if pid_file else root_p / "_daio" / "supervisor.pid"

    if not pid_path.exists():
        logger.info("No supervisor PID file found.")
        return False

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        if is_pid_alive(pid):
            import signal
            os.kill(pid, signal.SIGTERM)
            for _ in range(25):
                if not is_pid_alive(pid):
                    break
                time.sleep(0.1)
            logger.info(f"Stopped supervisor daemon PID {pid}")
        if pid_path.exists():
            pid_path.unlink()
        return True
    except Exception as ex:
        logger.warning(f"Error stopping supervisor daemon: {ex}")
        if pid_path.exists():
            pid_path.unlink()
        return False


def get_supervisor_daemon_status(project_root: str, pid_file: Optional[str] = None) -> Dict[str, Any]:
    """Returns daemon running status and PID."""
    root_p = Path(project_root).resolve()
    pid_path = Path(pid_file) if pid_file else root_p / "_daio" / "supervisor.pid"

    if not pid_path.exists():
        return {"running": False, "pid": None}

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        alive = is_pid_alive(pid)
        return {"running": alive, "pid": pid if alive else None}
    except Exception:
        return {"running": False, "pid": None}
