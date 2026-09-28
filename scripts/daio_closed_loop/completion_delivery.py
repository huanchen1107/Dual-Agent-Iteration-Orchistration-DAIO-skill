from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from .models import DAIOStatus, DAIOWorkItem


def _endpoint_identity(work: DAIOWorkItem) -> tuple[str, str]:
    endpoint = work.architect_endpoint or {}
    project_id = str(endpoint.get("chatgpt_project_id") or endpoint.get("project_id") or "").strip()
    conversation_id = str(endpoint.get("conversation_id") or "").strip()
    if not project_id or not conversation_id:
        raise ValueError("Exact originating project_id and conversation_id are required")
    return project_id, conversation_id


def build_delivery(work: DAIOWorkItem) -> Dict[str, Any]:
    if work.status not in {DAIOStatus.COMPLETED, DAIOStatus.HUMAN_GATE_REQUIRED, DAIOStatus.BLOCKED}:
        raise ValueError(f"Work is not at a user-relevant checkpoint: {work.status.value}")
    project_id, conversation_id = _endpoint_identity(work)
    identity = "|".join([
        work.work_id, work.execution_attempt_id or "none", str(work.fencing_token),
        str(work.work_revision), work.status.value, project_id, conversation_id,
    ])
    delivery_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    result = (work.metadata or {}).get("last_execution_report") or work.last_decision or work.status.value
    stdout: Optional[str] = None
    evidence_rel = (work.metadata or {}).get("completion_evidence_path")
    if evidence_rel:
        root = Path(work.project_root).resolve()
        evidence_path = (root / str(evidence_rel)).resolve()
        if root in evidence_path.parents and evidence_path.is_file():
            try:
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                if isinstance(evidence, dict) and isinstance(evidence.get("stdout"), str):
                    stdout = evidence["stdout"][:2000]
            except Exception:
                pass
    payload = {
        "work_id": work.work_id,
        "status": work.status.value,
        "result": str(result)[:2000],
        "stdout": stdout,
        "execution_attempt_id": work.execution_attempt_id,
    }
    return {
        "delivery_id": delivery_id,
        "work_id": work.work_id,
        "execution_attempt_id": work.execution_attempt_id,
        "fencing_token": work.fencing_token,
        "work_revision": work.work_revision,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "payload": payload,
    }


def render_delivery_message(delivery: Dict[str, Any]) -> str:
    payload = delivery["payload"]
    lines = [
        "✅ DAIO work update",
        f"- Work completed: `{payload['status'] == 'COMPLETED'}`",
        f"- Work ID: `{payload['work_id']}`",
        f"- Status: `{payload['status']}`",
        f"- Result: {payload['result']}",
    ]
    if payload.get("stdout") is not None:
        lines.append(f"- stdout: `{payload['stdout']}`")
    return "\n".join(lines)


async def deliver_user_visible_completion(store: Any, bridge: Any, work: DAIOWorkItem) -> bool:
    delivery = build_delivery(work)
    current = store.reserve_user_visible_delivery(delivery)
    if current == "DELIVERED":
        return True
    ok = await bridge.publish_user_visible_completion(
        work, render_delivery_message(delivery), delivery["delivery_id"]
    )
    store.mark_user_visible_delivery(delivery["delivery_id"], "DELIVERED" if ok else "PENDING")
    return ok
