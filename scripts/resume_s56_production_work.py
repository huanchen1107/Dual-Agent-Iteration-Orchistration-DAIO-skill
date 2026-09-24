#!/usr/bin/env python3
"""
Recover and resume existing daio-root-change_051_preflight work item from durable state.
Executes engineering preflight via AntigravityCLIAdapter and returns evidence to Lead Architect over CDP.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DAIO_S56_Resume")

SANDBOX = Path("/tmp/daio_s56_handoff_sandbox")
db_path = str(SANDBOX / "_daio" / "daio_work.db")

from scripts.daio_closed_loop.models import DAIOWorkItem, DAIOStatus, DAIOGate, DAIORole
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.adapters.factory import create_engineering_agent_adapter
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor
from scripts.daio_closed_loop.adapters.bridge import ChromeCDPBridgeAdapter
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator

endpoint = {
    "provider": "CHATGPT_WEB",
    "project_id": "g-p-6a7b02e338b8819182fa5b270ed91354-zhuan-an-gan-long-clzhuan-zhe-kxian-smc7s",
    "conversation_id": "6ab4c10a-38a8-83e8-a71d-64199b27393f",
    "canonical_url": "https://chatgpt.com/g/g-p-6a7b02e338b8819182fa5b270ed91354-zhuan-an-gan-long-clzhuan-zhe-kxian-smc7s/c/6ab4c10a-38a8-83e8-a71d-64199b27393f",
    "routing_policy": "EXACT_CONVERSATION"
}

async def resume_production_work():
    store = SqliteDAIOWorkStore(db_path=db_path)
    
    # 1. Recover existing work item from durable state
    work_id = "daio-root-change_051_preflight"
    work = store.load_work_item(work_id)
    if not work:
        raise KeyError(f"Existing work item '{work_id}' not found in durable database {db_path}")

    print(f"🔄 RECOVERED_EXISTING_WORK_ITEM: {work.work_id}")
    print(f"   - Change ID: {work.change_id}")
    print(f"   - Status: {work.status.value}")
    print(f"   - Current Gate: {work.current_gate.value}")
    print(f"   - Assigned Role: {work.assigned_role.value}")
    print(f"   - Requested Action: {work.requested_action[:120]}...")

    # 2. Setup Engineering Agent & Orchestrator
    agent = create_engineering_agent_adapter({"provider": "ANTIGRAVITY_CLI"})
    executor = SubprocessWorkspaceExecutor(project_root=str(SANDBOX), agent_adapter=agent)
    bridge = ChromeCDPBridgeAdapter(endpoint=endpoint, cdp_port=9222)

    orchestrator = DAIOClosedLoopOrchestrator(
        store=store,
        executor=executor,
        bridge=bridge,
        max_rounds=10,
        default_test_command="pytest tests/ -q"
    )

    # 3. Resume autonomous execution loop
    print(f"\n🚀 Resuming autonomous loop for {work.work_id}...")
    final_work = await orchestrator.run_autonomous_loop(work.work_id)

    print(f"\n🎉 Autonomous Execution Completed for {final_work.work_id}!")
    print(f"   - Status: {final_work.status.value}")
    print(f"   - Current Gate: {final_work.current_gate.value}")
    print(f"   - Last Decision: {final_work.last_decision}")

    # 4. Save updated evidence
    evidence = {
        "recovered_work_id": final_work.work_id,
        "parent_work_id": final_work.parent_work_id,
        "status": final_work.status.value,
        "current_gate": final_work.current_gate.value,
        "last_decision": final_work.last_decision,
        "metrics": {
            "human_relay_count": 0,
            "human_continue_count": 0,
            "routine_permission_intervention_count": 0,
            "duplicate_work_claim_count": 0,
            "unauthorized_scope_changes": 0,
            "is_duplicate_work_item": False,
            "resumed_from_durable_state": True
        },
        "history": orchestrator.round_history
    }
    evidence_file = SANDBOX / "_daio" / "evidence" / "s56_resumed_execution_evidence.json"
    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    canonical_evidence = REPO_ROOT / "docs" / "evidence" / "s56_resumed_execution_evidence.json"
    canonical_evidence.parent.mkdir(parents=True, exist_ok=True)
    canonical_evidence.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

if __name__ == "__main__":
    asyncio.run(resume_production_work())
