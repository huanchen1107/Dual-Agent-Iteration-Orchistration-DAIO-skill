"""
Generic DAIO Closed Loop Module (v2.1).
Autonomous Dual-Agent Closed-Loop Engine with Durable State & Conversation-Aware Routing.
"""

from .models import (
    ArchitectDecision,
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
    HandoffState,
    HandoffWatch,
)
from .store import DAIOWorkStore, SqliteDAIOWorkStore
from .router import DAIORoleRouter
from .orchestrator import DAIOClosedLoopOrchestrator
from .worker import DAIOPersistentWorker, run_persistent_worker
from .watchdog import DAIOHandoffWatchdog
from .supervisor import DAIOSupervisor, run_supervisor

__all__ = [
    "ArchitectDecision",
    "DAIOGate",
    "DAIORole",
    "DAIOStatus",
    "DAIOWorkItem",
    "HandoffState",
    "HandoffWatch",
    "DAIOWorkStore",
    "SqliteDAIOWorkStore",
    "DAIORoleRouter",
    "DAIOClosedLoopOrchestrator",
    "DAIOPersistentWorker",
    "run_persistent_worker",
    "DAIOHandoffWatchdog",
    "DAIOSupervisor",
    "run_supervisor",
]


