"""
Generic DAIO Long-Lived Persistent Worker & Queue Dispatcher Daemon.
Implements continuous background polling, exactly-once claim, process restart recovery,
autonomous state machine transitions, and evidence callbacks.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
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
    is_terminal_phase,
)
from .store import DAIOWorkStore, SqliteDAIOWorkStore
from .router import DAIORoleRouter
from .adapters.agent_contract import EngineeringAgentAdapter
from .adapters.executor import EngineeringExecutorAdapter, SubprocessWorkspaceExecutor
from .adapters.bridge import ArchitectBridgeAdapter, ChromeCDPBridgeAdapter, MockArchitectBridgeAdapter
from .adapters.factory import create_engineering_agent_adapter, create_architect_bridge_adapter
from .orchestrator import DAIOClosedLoopOrchestrator


logger = logging.getLogger("DAIO_Persistent_Worker")


class DAIOPersistentWorker:
    """
    True long-lived persistent worker daemon for Generic DAIO.
    Polls the durable SQLite store for pending/runnable work items, acquires atomic leases,
    executes closed loops (including agent proposal, verification, and Architect review turns),
    and automatically chains successor/root work items without human intervention.
    """

    def __init__(
        self,
        project_root: str,
        store: Optional[DAIOWorkStore] = None,
        executor: Optional[EngineeringExecutorAdapter] = None,
        bridge: Optional[ArchitectBridgeAdapter] = None,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        lease_ttl_seconds: int = 300,
        max_rounds_per_work: int = 10,
        default_test_command: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:6]}"
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_ttl_seconds = lease_ttl_seconds
        self.max_rounds_per_work = max_rounds_per_work
        self.default_test_command = default_test_command
        self._running = False
        self._active_work_id: Optional[str] = None

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
            agent_cfg = {"provider": agent_provider}
            if config_file.exists():
                try:
                    cfg = json.loads(config_file.read_text(encoding="utf-8"))
                    if "timeout_seconds" in cfg:
                        agent_cfg["timeout_seconds"] = cfg["timeout_seconds"]
                except Exception:
                    pass
            agent = create_engineering_agent_adapter(agent_cfg)
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


        self.orchestrator = DAIOClosedLoopOrchestrator(
            store=self.store,
            executor=self.executor,
            bridge=self.bridge,
            max_rounds=self.max_rounds_per_work,
            default_test_command=self.default_test_command,
        )

    def stop(self) -> None:
        """Signal the worker to gracefully stop."""
        logger.info(f"🛑 Stopping DAIOPersistentWorker ({self.worker_id})...")
        self._running = False

    async def run_once(self) -> Optional[DAIOWorkItem]:
        """
        Poll for the next available work item, execute it through its closed loop,
        and handle post-completion transitions. Returns the completed work item or None.
        """
        claimed = self.store.claim_next_available_work_item(
            worker_id=self.worker_id,
            ttl_seconds=self.lease_ttl_seconds
        )
        if not claimed:
            return None

        self._active_work_id = claimed.work_id
        logger.info(f"⚡ WORKER_CLAIMED_ITEM: work_id={claimed.work_id}, change_id={claimed.change_id}, gate={claimed.current_gate.value}, status={claimed.status.value}")

        try:
            final_work = await self.orchestrator.run_autonomous_loop(
                work_id=claimed.work_id,
                worker_id=self.worker_id
            )
            logger.info(f"🏁 WORK_ITEM_COMPLETED: work_id={final_work.work_id}, status={final_work.status.value}, decision={final_work.last_decision}")

            # If work completed and authorized next phase, automatically create next work item in durable queue
            if final_work.status == DAIOStatus.COMPLETED and final_work.last_decision == "APPROVE":
                next_phase = final_work.authorized_next_phase
                if next_phase and not is_terminal_phase(next_phase):
                    logger.info(f"⏩ NEXT_PHASE_AUTHORIZED: {next_phase} from {final_work.work_id}")
                    self.orchestrator.resolve_next_work_item(final_work, next_phase)

            return final_work
        finally:
            self._active_work_id = None

    async def start(self, max_iterations: Optional[int] = None) -> List[DAIOWorkItem]:
        """
        Start the continuous background worker loop.
        """
        self._running = True
        completed_items: List[DAIOWorkItem] = []
        iterations = 0

        logger.info(f"🚀 DAIOPersistentWorker STARTED: id={self.worker_id}, root={self.project_root}, poll_interval={self.poll_interval_seconds}s")

        try:
            while self._running:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                try:
                    res = await self.run_once()
                    if res:
                        completed_items.append(res)
                    else:
                        # No work available, wait for next polling tick
                        await asyncio.sleep(self.poll_interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in persistent worker polling tick: {e}", exc_info=True)
                    await asyncio.sleep(self.poll_interval_seconds)
        finally:
            self._running = False
            logger.info(f"🛑 DAIOPersistentWorker EXITED: id={self.worker_id}, total_processed={len(completed_items)}")

        return completed_items


async def run_persistent_worker(
    project_root: str,
    worker_id: Optional[str] = None,
    poll_interval_seconds: float = 2.0,
    max_iterations: Optional[int] = None,
) -> List[DAIOWorkItem]:
    """Top-level entry point to run persistent worker in a target project."""
    worker = DAIOPersistentWorker(
        project_root=project_root,
        worker_id=worker_id,
        poll_interval_seconds=poll_interval_seconds,
    )
    return await worker.start(max_iterations=max_iterations)
