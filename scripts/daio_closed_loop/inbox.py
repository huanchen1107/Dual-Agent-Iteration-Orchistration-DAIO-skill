"""
Filesystem-Backed Durable Root Work Ingress for DAIO Persistent Supervisor (DEFECT-C1-SUPERVISOR-INGRESS-002).

Enables unattended, durable submission of root DAIO work requests via atomic file drops:
- _daio/inbox/
- _daio/inbox/processing/
- _daio/inbox/processed/
- _daio/inbox/rejected/

Guarantees:
- Atomic file-claim before parsing/processing
- Schema validation gate before SQLite insertion
- Strict request_id deduplication & idempotency
- Crash/restart recovery of in-flight processing items without duplicate work creation
- Direct integration with canonical DAIO store & orchestrator APIs
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
import datetime
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .models import (
    DAIOGate,
    DAIORole,
    DAIOStatus,
    DAIOWorkItem,
)
from .store import DAIOWorkStore

logger = logging.getLogger("DAIO_Inbox")

SUPPORTED_INBOX_SCHEMA = "daio-root-work/v1"
VALID_ROLES = {
    DAIORole.ENGINEERING_EXECUTION.value,
    DAIORole.LEAD_ARCHITECT_REVIEW.value,
    "ENGINEERING_EXECUTION",
    "LEAD_ARCHITECT_REVIEW",
}


@dataclass
class RootWorkRequest:
    schema_version: str
    request_id: str
    project_id: str
    change_id: str
    requested_action: str
    requested_role: str = DAIORole.ENGINEERING_EXECUTION.value
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    allowed_scope: List[str] = field(default_factory=list)
    architect_endpoint: Dict[str, Any] = field(default_factory=dict)
    current_gate: Optional[str] = None
    parent_work_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RootWorkRequest:
        return cls(
            schema_version=str(data.get("schema_version", "")),
            request_id=str(data.get("request_id", "")).strip(),
            project_id=str(data.get("project_id", "")).strip(),
            change_id=str(data.get("change_id", "")).strip(),
            requested_action=str(data.get("requested_action", "")).strip(),
            requested_role=str(data.get("requested_role", DAIORole.ENGINEERING_EXECUTION.value)).strip().upper(),
            created_at=str(data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat())),
            allowed_scope=list(data.get("allowed_scope", [])),
            architect_endpoint=dict(data.get("architect_endpoint", {})),
            current_gate=data.get("current_gate"),
            parent_work_id=data.get("parent_work_id"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class InboxIngestResult:
    request_id: str
    status: str  # "INGESTED", "ALREADY_PROCESSED", "REJECTED_SCHEMA", "CLAIM_FAILED", "RECOVERED"
    work_id: Optional[str] = None
    error_reason: Optional[str] = None
    file_name: Optional[str] = None


class DAIORootWorkInbox:
    """
    Filesystem-backed durable root work inbox manager for DAIOSupervisor.
    """

    def __init__(self, inbox_dir: Path | str) -> None:
        self.inbox_dir = Path(inbox_dir).resolve()
        self.processing_dir = self.inbox_dir / "processing"
        self.processed_dir = self.inbox_dir / "processed"
        self.rejected_dir = self.inbox_dir / "rejected"
        self.ensure_directories()

    def ensure_directories(self) -> None:
        """Ensures all 4 inbox lifecycle directories exist."""
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.rejected_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def submit_request(
        cls,
        inbox_dir: Path | str,
        request_data: Dict[str, Any] | RootWorkRequest,
    ) -> Path:
        """
        Producer helper: writes to a temporary file first, then atomically renames to <request_id>.json.
        """
        inbox_p = Path(inbox_dir).resolve()
        inbox_p.mkdir(parents=True, exist_ok=True)

        if isinstance(request_data, RootWorkRequest):
            payload = request_data.to_dict()
            req_id = request_data.request_id
        else:
            payload = dict(request_data)
            req_id = payload.get("request_id") or f"req-{uuid.uuid4().hex[:8]}"
            if "request_id" not in payload:
                payload["request_id"] = req_id
            if "schema_version" not in payload:
                payload["schema_version"] = SUPPORTED_INBOX_SCHEMA

        target_file = inbox_p / f"{req_id}.json"
        tmp_file = inbox_p / f"{req_id}.tmp.{uuid.uuid4().hex[:6]}"

        # Write to temp file then atomic replace
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_file, target_file)
        logger.info(f"📥 Root work request submitted to inbox: {target_file.name}")
        return target_file

    def validate_envelope(self, data: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[RootWorkRequest]]:
        """Validates envelope against strict schema and semantics."""
        if not isinstance(data, dict):
            return False, "Payload must be a JSON object", None

        schema_ver = data.get("schema_version")
        if schema_ver != SUPPORTED_INBOX_SCHEMA:
            return False, f"Invalid schema_version '{schema_ver}'. Expected '{SUPPORTED_INBOX_SCHEMA}'", None

        req_id = str(data.get("request_id", "")).strip()
        if not req_id:
            return False, "Missing or empty 'request_id'", None

        project_id = str(data.get("project_id", "")).strip()
        if not project_id:
            return False, "Missing or empty 'project_id'", None

        change_id = str(data.get("change_id", "")).strip()
        if not change_id:
            return False, "Missing or empty 'change_id'", None

        action = str(data.get("requested_action", "")).strip()
        if not action:
            return False, "Missing or empty 'requested_action'", None

        role = str(data.get("requested_role", DAIORole.ENGINEERING_EXECUTION.value)).strip().upper()
        if role not in VALID_ROLES:
            return False, f"Invalid requested_role '{role}'. Expected one of {sorted(list(VALID_ROLES))}", None

        try:
            req = RootWorkRequest.from_dict(data)
            return True, None, req
        except Exception as ex:
            return False, f"Envelope parsing error: {ex}", None

    def poll_and_ingest(
        self,
        store: DAIOWorkStore,
        project_root: Optional[str] = None,
    ) -> List[InboxIngestResult]:
        """
        Main supervisor polling step:
        1. Recover any in-flight orphaned files in processing/
        2. Discover new *.json files in inbox/
        3. Atomically claim into processing/
        4. Validate schema
        5. Check idempotency against durable store
        6. Create and save canonical DAIOWorkItem
        7. Move to processed/ or rejected/
        """
        self.ensure_directories()
        results: List[InboxIngestResult] = []

        # 1. First, process any recovered files left in processing/ (e.g. from crash before commit)
        for proc_file in sorted(self.processing_dir.glob("*.json")):
            res = self._process_claimed_file(proc_file, store=store, project_root=project_root, is_recovery=True)
            results.append(res)

        # 2. Discover new candidate files in inbox/
        # Strictly ignore .tmp* files and non-.json files
        for item in sorted(self.inbox_dir.iterdir()):
            if item.is_file() and item.suffix == ".json" and not item.name.startswith("."):
                claimed_path = self.processing_dir / item.name
                try:
                    # Atomic claim: rename into processing/
                    os.replace(item, claimed_path)
                except (OSError, FileNotFoundError):
                    # Claimed by another supervisor instance or already moved
                    continue

                res = self._process_claimed_file(claimed_path, store=store, project_root=project_root, is_recovery=False)
                results.append(res)

        return results

    def _process_claimed_file(
        self,
        file_path: Path,
        store: DAIOWorkStore,
        project_root: Optional[str] = None,
        is_recovery: bool = False,
    ) -> InboxIngestResult:
        """Processes an atomically claimed file from processing/."""
        req_id = file_path.stem
        try:
            raw_text = file_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as ex:
            # Malformed JSON -> reject
            rej_path = self.rejected_dir / file_path.name
            rej_err_path = self.rejected_dir / f"{file_path.stem}.error.json"
            try:
                os.replace(file_path, rej_path)
                rej_err_path.write_text(json.dumps({
                    "request_id": req_id,
                    "rejected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "reason": f"Malformed JSON content: {ex}",
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
            return InboxIngestResult(
                request_id=req_id,
                status="REJECTED_SCHEMA",
                error_reason=f"Malformed JSON content: {ex}",
                file_name=file_path.name,
            )

        # Validate Schema
        valid, err_reason, envelope = self.validate_envelope(data)
        if not valid or not envelope:
            rej_path = self.rejected_dir / file_path.name
            rej_err_path = self.rejected_dir / f"{file_path.stem}.error.json"
            try:
                os.replace(file_path, rej_path)
                rej_err_path.write_text(json.dumps({
                    "request_id": req_id,
                    "rejected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "reason": err_reason,
                    "raw_payload": data,
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
            return InboxIngestResult(
                request_id=req_id,
                status="REJECTED_SCHEMA",
                error_reason=err_reason,
                file_name=file_path.name,
            )

        # Strict Idempotency Check:
        # Check if a work item derived from this request_id already exists in store
        target_work_id = f"daio-root-{envelope.request_id}"
        existing_work = store.load_work_item(target_work_id)
        if not existing_work:
            # Also search existing work items for metadata["root_request_id"] == req_id
            all_items = store.list_work_items(change_id=envelope.change_id)
            for it in all_items:
                if isinstance(it.metadata, dict) and it.metadata.get("root_request_id") == envelope.request_id:
                    existing_work = it
                    target_work_id = it.work_id
                    break

        if existing_work:
            # Request was already committed in SQLite
            proc_path = self.processed_dir / file_path.name
            os.replace(file_path, proc_path)
            logger.info(f"🔁 Duplicate/Already processed request_id '{envelope.request_id}' mapped to existing work '{existing_work.work_id}'")
            return InboxIngestResult(
                request_id=envelope.request_id,
                status="ALREADY_PROCESSED" if not is_recovery else "RECOVERED",
                work_id=existing_work.work_id,
                file_name=file_path.name,
            )

        # Convert to canonical DAIOWorkItem
        assigned_role = DAIORole.LEAD_ARCHITECT_REVIEW if "ARCHITECT" in envelope.requested_role else DAIORole.ENGINEERING_EXECUTION
        initial_gate = DAIOGate.CONTRACT_GATE
        if envelope.current_gate:
            for g in DAIOGate:
                if g.value == envelope.current_gate:
                    initial_gate = g
                    break
        elif assigned_role == DAIORole.ENGINEERING_EXECUTION:
            initial_gate = DAIOGate.IMPLEMENTATION_GATE

        p_root = project_root or envelope.metadata.get("project_root") or str(self.inbox_dir.parent.parent)

        work = DAIOWorkItem(
            work_id=target_work_id,
            project_root=p_root,
            change_id=envelope.change_id,
            current_stage=envelope.change_id,
            current_gate=initial_gate,
            assigned_role=assigned_role,
            requested_action=envelope.requested_action,
            allowed_scope=envelope.allowed_scope,
            architect_endpoint=envelope.architect_endpoint,
            parent_work_id=envelope.parent_work_id,
            status=DAIOStatus.QUEUED,
            metadata={
                **envelope.metadata,
                "root_request_id": envelope.request_id,
                "inbox_ingested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "schema_version": envelope.schema_version,
            }
        )

        # Commit to SQLite store
        store.save_work_item(work)

        # Move claimed file from processing/ -> processed/
        proc_path = self.processed_dir / file_path.name
        os.replace(file_path, proc_path)

        logger.info(f"✨ Inbox successfully ingested new root work item: {work.work_id} (change={work.change_id}, status={work.status.value})")
        return InboxIngestResult(
            request_id=envelope.request_id,
            status="INGESTED",
            work_id=work.work_id,
            file_name=file_path.name,
        )
