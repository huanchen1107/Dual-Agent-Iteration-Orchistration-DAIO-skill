"""
Durable Work State & Lease Storage Engine for Generic DAIO Closed Loop.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from .models import DAIOGate, DAIORole, DAIOStatus, DAIOWorkItem


class DAIOWorkStore(ABC):
    """Abstract interface for DAIO work item and lease state persistence."""

    @abstractmethod
    def save_work_item(self, item: DAIOWorkItem) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_work_item(self, work_id: str) -> Optional[DAIOWorkItem]:
        raise NotImplementedError

    @abstractmethod
    def list_work_items(self, change_id: Optional[str] = None) -> List[DAIOWorkItem]:
        raise NotImplementedError

    @abstractmethod
    def acquire_lease(self, work_id: str, worker_id: str, ttl_seconds: int = 60) -> Optional[str]:
        raise NotImplementedError

    @abstractmethod
    def release_lease(self, work_id: str, lease_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def claim_next_available_work_item(self, worker_id: str, ttl_seconds: int = 300) -> Optional[DAIOWorkItem]:
        raise NotImplementedError


class SqliteDAIOWorkStore(DAIOWorkStore):
    """
    SQLite-backed implementation of DAIOWorkStore.
    Ensures that DAIO work items and execution leases survive process termination and agent switching.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._shared_conn = None
        if db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:")
            self._shared_conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daio_work_items (
                work_id TEXT PRIMARY KEY,
                project_root TEXT NOT NULL,
                change_id TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                current_gate TEXT NOT NULL,
                assigned_role TEXT NOT NULL,
                requested_action TEXT NOT NULL,
                allowed_scope TEXT NOT NULL,
                base_sha TEXT NOT NULL,
                head_sha TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                lease_id TEXT,
                lease_expires_at TEXT,
                next_role TEXT,
                human_gate_reason TEXT,
                human_relay_count INTEGER NOT NULL DEFAULT 0,
                architect_endpoint TEXT NOT NULL DEFAULT '{}',
                parent_work_id TEXT,
                last_decision TEXT,
                authorized_next_phase TEXT,
                claimed_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daio_turn_history (
                turn_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL,
                role TEXT NOT NULL,
                action_summary TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(work_id) REFERENCES daio_work_items(work_id)
            )
        """)
        # Auto-migration for schema evolutions
        cursor.execute("PRAGMA table_info(daio_work_items)")
        existing_cols = {col["name"] for col in cursor.fetchall()}
        if "human_relay_count" not in existing_cols:
            cursor.execute("ALTER TABLE daio_work_items ADD COLUMN human_relay_count INTEGER NOT NULL DEFAULT 0")
        if "architect_endpoint" not in existing_cols:
            cursor.execute("ALTER TABLE daio_work_items ADD COLUMN architect_endpoint TEXT NOT NULL DEFAULT '{}'")
        if "parent_work_id" not in existing_cols:
            cursor.execute("ALTER TABLE daio_work_items ADD COLUMN parent_work_id TEXT")
        if "last_decision" not in existing_cols:
            cursor.execute("ALTER TABLE daio_work_items ADD COLUMN last_decision TEXT")
        if "authorized_next_phase" not in existing_cols:
            cursor.execute("ALTER TABLE daio_work_items ADD COLUMN authorized_next_phase TEXT")
        if "claimed_by" not in existing_cols:
            cursor.execute("ALTER TABLE daio_work_items ADD COLUMN claimed_by TEXT")

        conn.commit()
        if not self._shared_conn:
            conn.close()

    def save_work_item(self, item: DAIOWorkItem) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO daio_work_items (
                work_id, project_root, change_id, current_stage, current_gate,
                assigned_role, requested_action, allowed_scope, base_sha,
                head_sha, status, attempt_count, max_attempts, lease_id,
                lease_expires_at, next_role, human_gate_reason, human_relay_count,
                architect_endpoint, parent_work_id, last_decision,
                authorized_next_phase, claimed_by, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_id) DO UPDATE SET
                current_stage=excluded.current_stage,
                current_gate=excluded.current_gate,
                assigned_role=excluded.assigned_role,
                requested_action=excluded.requested_action,
                allowed_scope=excluded.allowed_scope,
                base_sha=excluded.base_sha,
                head_sha=excluded.head_sha,
                status=excluded.status,
                attempt_count=excluded.attempt_count,
                max_attempts=excluded.max_attempts,
                lease_id=excluded.lease_id,
                lease_expires_at=excluded.lease_expires_at,
                next_role=excluded.next_role,
                human_gate_reason=excluded.human_gate_reason,
                human_relay_count=excluded.human_relay_count,
                architect_endpoint=excluded.architect_endpoint,
                parent_work_id=excluded.parent_work_id,
                last_decision=excluded.last_decision,
                authorized_next_phase=excluded.authorized_next_phase,
                claimed_by=excluded.claimed_by,
                updated_at=excluded.updated_at,
                metadata=excluded.metadata
        """, (
            item.work_id,
            item.project_root,
            item.change_id,
            item.current_stage,
            item.current_gate.value,
            item.assigned_role.value,
            item.requested_action,
            json.dumps(item.allowed_scope),
            item.base_sha,
            item.head_sha,
            item.status.value,
            item.attempt_count,
            item.max_attempts,
            item.lease_id,
            item.lease_expires_at,
            item.next_role.value if item.next_role else None,
            item.human_gate_reason,
            item.human_relay_count,
            json.dumps(item.architect_endpoint),
            item.parent_work_id,
            item.last_decision,
            item.authorized_next_phase,
            item.claimed_by,
            item.created_at,
            item.updated_at,
            json.dumps(item.metadata),
        ))
        conn.commit()
        if not self._shared_conn:
            conn.close()

    def record_turn_history(
        self,
        turn_id: str,
        work_id: str,
        role: str,
        action_summary: str,
        commit_sha: str,
        status: str,
        payload: Dict[str, Any],
    ) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO daio_turn_history (
                turn_id, work_id, role, action_summary, commit_sha, status, created_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn_id) DO NOTHING
        """, (
            turn_id,
            work_id,
            role,
            action_summary,
            commit_sha,
            status,
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            json.dumps(payload),
        ))
        conn.commit()
        if not self._shared_conn:
            conn.close()

    def load_work_item(self, work_id: str) -> Optional[DAIOWorkItem]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM daio_work_items WHERE work_id = ?", (work_id,))
        row = cursor.fetchone()
        if not row:
            if not self._shared_conn:
                conn.close()
            return None
        res = self._row_to_work_item(row)
        if not self._shared_conn:
            conn.close()
        return res

    def list_work_items(self, change_id: Optional[str] = None) -> List[DAIOWorkItem]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if change_id:
            cursor.execute("SELECT * FROM daio_work_items WHERE change_id = ?", (change_id,))
        else:
            cursor.execute("SELECT * FROM daio_work_items")
        rows = cursor.fetchall()
        res = [self._row_to_work_item(r) for r in rows]
        if not self._shared_conn:
            conn.close()
        return res

    def list_all_work_items(self) -> List[DAIOWorkItem]:
        return self.list_work_items()

    def acquire_lease(self, work_id: str, worker_id: str, ttl_seconds: int = 60) -> Optional[str]:
        """Acquire a lease lock on work_id if not already locked by another active lease."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT lease_id, lease_expires_at FROM daio_work_items WHERE work_id = ?", (work_id,))
        row = cursor.fetchone()
        if not row:
            if not self._shared_conn:
                conn.close()
            return None

        now = datetime.datetime.now(datetime.timezone.utc)
        current_lease_id = row["lease_id"]
        expires_at_str = row["lease_expires_at"]

        # Check if existing lease is active
        if current_lease_id and expires_at_str:
            try:
                expires_at = datetime.datetime.fromisoformat(expires_at_str)
                if expires_at > now:
                    if not self._shared_conn:
                        conn.close()
                    return None  # Still locked
            except Exception:
                pass

        # Grant new lease
        new_lease_id = f"lease-{uuid.uuid4().hex[:8]}"
        new_expires_at = (now + datetime.timedelta(seconds=ttl_seconds)).isoformat()
        cursor.execute("""
            UPDATE daio_work_items
            SET lease_id = ?, lease_expires_at = ?, claimed_by = ?, updated_at = ?
            WHERE work_id = ?
        """, (new_lease_id, new_expires_at, worker_id, now.isoformat(), work_id))
        conn.commit()
        if not self._shared_conn:
            conn.close()
        return new_lease_id

    def release_lease(self, work_id: str, lease_id: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE daio_work_items
            SET lease_id = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE work_id = ? AND lease_id = ?
        """, (datetime.datetime.now(datetime.timezone.utc).isoformat(), work_id, lease_id))
        conn.commit()
        affected = cursor.rowcount > 0
        if not self._shared_conn:
            conn.close()
        return affected

    def claim_next_available_work_item(self, worker_id: str, ttl_seconds: int = 300) -> Optional[DAIOWorkItem]:
        """
        Atomically claim the next runnable work item from the durable queue using SQLite transaction locking.
        Guarantees exactly-once claim across concurrent workers (duplicate_work_claim_count == 0).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now.isoformat()
        new_lease_id = f"lease-{uuid.uuid4().hex[:8]}"
        new_expires_at = (now + datetime.timedelta(seconds=ttl_seconds)).isoformat()

        try:
            cursor.execute("BEGIN IMMEDIATE")

            # Find next runnable item (FIFO)
            cursor.execute("""
                SELECT work_id FROM daio_work_items
                WHERE status IN ('QUEUED', 'AWAITING_REVIEW', 'IN_PROGRESS')
                  AND (lease_id IS NULL OR lease_expires_at < ?)
                ORDER BY created_at ASC
                LIMIT 1
            """, (now_iso,))
            row = cursor.fetchone()
            if not row:
                conn.commit()
                if not self._shared_conn:
                    conn.close()
                return None

            claimed_work_id = row["work_id"]

            cursor.execute("""
                UPDATE daio_work_items
                SET lease_id = ?, lease_expires_at = ?, claimed_by = ?, updated_at = ?
                WHERE work_id = ?
            """, (new_lease_id, new_expires_at, worker_id, now_iso, claimed_work_id))
            conn.commit()

            cursor.execute("SELECT * FROM daio_work_items WHERE work_id = ?", (claimed_work_id,))
            claimed_row = cursor.fetchone()
            res = self._row_to_work_item(claimed_row) if claimed_row else None
            if not self._shared_conn:
                conn.close()
            return res

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if not self._shared_conn:
                conn.close()
            logger.error(f"Error during claim_next_available_work_item: {e}")
            return None

    def _row_to_work_item(self, row: sqlite3.Row) -> DAIOWorkItem:
        keys = row.keys()
        return DAIOWorkItem(
            work_id=row["work_id"],
            project_root=row["project_root"],
            change_id=row["change_id"],
            current_stage=row["current_stage"],
            current_gate=DAIOGate(row["current_gate"]),
            assigned_role=DAIORole(row["assigned_role"]),
            requested_action=row["requested_action"],
            allowed_scope=json.loads(row["allowed_scope"]),
            base_sha=row["base_sha"],
            head_sha=row["head_sha"],
            status=DAIOStatus(row["status"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            lease_id=row["lease_id"],
            lease_expires_at=row["lease_expires_at"],
            next_role=DAIORole(row["next_role"]) if row["next_role"] else None,
            human_gate_reason=row["human_gate_reason"],
            human_relay_count=row["human_relay_count"] if "human_relay_count" in keys else 0,
            architect_endpoint=json.loads(row["architect_endpoint"]) if "architect_endpoint" in keys and row["architect_endpoint"] else {},
            parent_work_id=row["parent_work_id"] if "parent_work_id" in keys else None,
            last_decision=row["last_decision"] if "last_decision" in keys else None,
            authorized_next_phase=row["authorized_next_phase"] if "authorized_next_phase" in keys else None,
            claimed_by=row["claimed_by"] if "claimed_by" in keys else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata"]),
        )

