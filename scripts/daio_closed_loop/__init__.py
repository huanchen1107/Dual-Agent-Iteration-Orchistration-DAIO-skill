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
)
from .store import DAIOWorkStore, SqliteDAIOWorkStore
from .router import DAIORoleRouter
from .orchestrator import DAIOClosedLoopOrchestrator
from .worker import DAIOPersistentWorker, run_persistent_worker

__all__ = [
    "ArchitectDecision",
    "DAIOGate",
    "DAIORole",
    "DAIOStatus",
    "DAIOWorkItem",
    "DAIOWorkStore",
    "SqliteDAIOWorkStore",
    "DAIORoleRouter",
    "DAIOClosedLoopOrchestrator",
    "DAIOPersistentWorker",
    "run_persistent_worker",
]

