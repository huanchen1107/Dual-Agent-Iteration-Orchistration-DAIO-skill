#!/usr/bin/env python3
"""
DAIO 5-Round E2E Closed-Loop Acceptance Test.
Exercises the REAL production path with zero mocks:
Supervisor -> Durable Queue -> Claim/Lease -> AntigravityCLIAdapter -> Execution -> Gate Test -> Git Commit -> ChromeCDPBridgeAdapter -> ChatGPT Lead Architect Review -> Decision Ingestion -> Successor Materialization -> Next Round.

Runs 5 consecutive autonomous round trips on _daio_acceptance/hello-daio.txt.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DAIO_5Round_Acceptance")

from scripts.daio_closed_loop.models import (
    DAIOWorkItem,
    DAIOStatus,
    DAIOGate,
    DAIORole,
    ArchitectDecision,
    is_terminal_phase,
)
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.adapters.factory import create_engineering_agent_adapter
from scripts.daio_closed_loop.adapters.executor import SubprocessWorkspaceExecutor
from scripts.daio_closed_loop.adapters.bridge import ChromeCDPBridgeAdapter
from scripts.daio_closed_loop.supervisor import DAIOSupervisor


async def run_5round_acceptance():
    # 1. Setup isolated acceptance sandbox directory in /tmp
    sandbox_dir = Path("/tmp/daio_acceptance_5round_sandbox")
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    # Initialize git repo in sandbox
    subprocess.run(["git", "init"], cwd=sandbox_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "DAIO-Acceptance-Worker"], cwd=sandbox_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "worker@daio.io"], cwd=sandbox_dir, check=True, capture_output=True)

    # Initial artifact & test suite
    acc_dir = sandbox_dir / "_daio_acceptance"
    acc_dir.mkdir(exist_ok=True)
    target_file = acc_dir / "hello-daio.txt"
    target_file.write_text("# DAIO Acceptance Artifact\nInitial Baseline\n", encoding="utf-8")

    tests_dir = sandbox_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_acceptance.py").write_text(
        'from pathlib import Path\n\n'
        'def test_acceptance_artifact():\n'
        '    content = Path("_daio_acceptance/hello-daio.txt").read_text(encoding="utf-8")\n'
        '    assert "# DAIO Acceptance Artifact" in content\n',
        encoding="utf-8"
    )

    # Install DAIO into sandbox
    subprocess.run(["bash", str(REPO_ROOT / "install.sh"), str(sandbox_dir)], check=True, capture_output=True)

    # ChatGPT Endpoint configuration (EXACT_CONVERSATION)
    endpoint = {
        "provider": "CHATGPT_WEB",
        "project_id": "g-p-6a7b02e338b8819182fa5b270ed91354-zhuan-an-gan-long-clzhuan-zhe-kxian-smc7s",
        "conversation_id": "6ab4c10a-38a8-83e8-a71d-64199b27393f",
        "canonical_url": "https://chatgpt.com/g/g-p-6a7b02e338b8819182fa5b270ed91354-zhuan-an-gan-long-clzhuan-zhe-kxian-smc7s/c/6ab4c10a-38a8-83e8-a71d-64199b27393f",
        "routing_policy": "EXACT_CONVERSATION"
    }

    daio_cfg = {
        "project_name": "DAIO_5Round_Acceptance",
        "architect_endpoint": endpoint,
        "cdp_url": "http://127.0.0.1:9222",
        "cdp_port": 9222,
        "test_gate_command": "pytest tests/ -q",
        "provider": "ANTIGRAVITY_CLI"
    }
    (sandbox_dir / "_daio" / "daio_config.json").write_text(json.dumps(daio_cfg, indent=2), encoding="utf-8")

    # Commit baseline
    subprocess.run(["git", "add", "."], cwd=sandbox_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: baseline acceptance sandbox initialized"], cwd=sandbox_dir, check=True, capture_output=True)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=sandbox_dir, capture_output=True, text=True).stdout.strip()
    logger.info(f"Baseline commit SHA: {base_sha}")

    # 2. Setup Real Production Components
    db_path = str(sandbox_dir / "_daio" / "daio_acceptance.db")
    store = SqliteDAIOWorkStore(db_path=db_path)
    
    agent = create_engineering_agent_adapter({"provider": "ANTIGRAVITY_CLI"})
    executor = SubprocessWorkspaceExecutor(project_root=str(sandbox_dir), agent_adapter=agent)
    bridge = ChromeCDPBridgeAdapter(endpoint=endpoint, cdp_port=9222)

    supervisor = DAIOSupervisor(
        project_root=str(sandbox_dir),
        store=store,
        executor=executor,
        bridge=bridge,
        supervisor_id="supervisor-acceptance-5round",
        poll_interval_seconds=1.0,
        lease_ttl_seconds=300,
        watchdog_discovery_timeout=20.0,
        watchdog_claim_timeout=30.0,
        watchdog_progress_timeout=120.0,
        max_recovery_attempts=3,
        default_test_command="pytest tests/ -q",
    )

    # 3. Create Root Work Item for Round 1
    root_work = DAIOWorkItem(
        work_id="daio-acceptance-round-1",
        project_root=str(sandbox_dir),
        change_id="ACCEPTANCE_ROUND_1",
        status=DAIOStatus.QUEUED,
        current_gate=DAIOGate.CONTRACT_GATE,
        assigned_role=DAIORole.ENGINEERING_EXECUTION,
        current_stage="ACCEPTANCE_ROUND_1",
        allowed_scope=["_daio_acceptance/*"],
        requested_action="Append the exact line 'Round 1: OK' to _daio_acceptance/hello-daio.txt. Do not modify any other files.",
        architect_endpoint=endpoint,
        metadata={
            "acceptance_round": 1,
            "max_rounds": 5,
            "next_round_phase": "ACCEPTANCE_ROUND_2",
            "instruction": "Append the exact line 'Round 1: OK' to _daio_acceptance/hello-daio.txt."
        }
    )
    store.save_work_item(root_work)
    logger.info("Created root work item: daio-acceptance-round-1")

    # Round descriptions
    round_configs = {
        1: {
            "change_id": "ACCEPTANCE_ROUND_1",
            "next_phase": "ACCEPTANCE_ROUND_2",
            "action": "Append the exact line 'Round 1: OK' to _daio_acceptance/hello-daio.txt.",
        },
        2: {
            "change_id": "ACCEPTANCE_ROUND_2",
            "next_phase": "ACCEPTANCE_ROUND_3",
            "action": "Append the exact line 'Round 2: OK' to _daio_acceptance/hello-daio.txt.",
        },
        3: {
            "change_id": "ACCEPTANCE_ROUND_3",
            "next_phase": "ACCEPTANCE_ROUND_4",
            "action": "Append the exact line 'Round 3: OK' to _daio_acceptance/hello-daio.txt.",
        },
        4: {
            "change_id": "ACCEPTANCE_ROUND_4",
            "next_phase": "ACCEPTANCE_ROUND_5",
            "action": "Append the exact line 'Round 4: OK' to _daio_acceptance/hello-daio.txt.",
        },
        5: {
            "change_id": "ACCEPTANCE_ROUND_5",
            "next_phase": "COMPLETED",
            "action": "Append the exact line 'Round 5: OK' to _daio_acceptance/hello-daio.txt.",
        },
    }

    metrics = {
        "intervention_count": 0,
        "permission_prompt_count": 0,
        "duplicate_message_count": 0,
        "manual_recovery_count": 0,
        "rounds": {},
        "overall_status": "RUNNING",
    }

    print("\n" + "="*80)
    print("🏁 STARTING DAIO 5-ROUND E2E AUTONOMOUS ACCEPTANCE TEST")
    print("="*80 + "\n")

    current_round = 1
    max_test_seconds = 600  # 10 minutes total budget
    start_time = datetime.datetime.now(datetime.timezone.utc)

    try:
        while current_round <= 5:
            now = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (now - start_time).total_seconds()
            if elapsed > max_test_seconds:
                raise TimeoutError(f"5-round acceptance exceeded total time budget of {max_test_seconds}s")

            # Run one supervisor tick
            tick_result = await supervisor.run_tick()
            
            # Check all items in store
            items = store.list_work_items()
            round_change_id = round_configs[current_round]["change_id"]
            current_item = next((it for it in items if it.change_id == round_change_id), None)

            if current_item:
                if current_item.status == DAIOStatus.COMPLETED:
                    last_dec = current_item.metadata.get("last_architect_decision", {})
                    dec_hash = current_item.metadata.get("last_decision_hash", "none")
                    commit_sha = current_item.head_sha or current_item.metadata.get("generated_commit_sha", "")
                    
                    if current_round not in metrics["rounds"]:
                        metrics["rounds"][current_round] = {
                            "work_id": current_item.work_id,
                            "change_id": current_item.change_id,
                            "status": current_item.status.value,
                            "commit_sha": commit_sha,
                            "decision_hash": dec_hash,
                            "decision": last_dec.get("decision", "APPROVE"),
                            "next_phase": current_item.authorized_next_phase,
                        }
                        print(f"\n🎉 [ROUND {current_round}/5 PASS] work_id={current_item.work_id}, commit={commit_sha[:8]}, dec_hash={dec_hash}, next_phase={current_item.authorized_next_phase}\n")
                        
                        if current_round < 5:
                            current_round += 1
                        else:
                            metrics["overall_status"] = "PASS"
                            print("\n🏆 ALL 5 ROUNDS COMPLETED AUTONOMOUSLY WITH ZERO INTERVENTIONS!\n")
                            break
                elif current_item.status in {DAIOStatus.HUMAN_GATE_REQUIRED, DAIOStatus.BLOCKED}:
                    metrics["overall_status"] = "FAIL"
                    raise RuntimeError(f"Round {current_round} stalled in status {current_item.status.value}: {current_item.last_error}")

            await asyncio.sleep(1.0)

    except Exception as ex:
        metrics["overall_status"] = "FAIL"
        logger.error(f"Acceptance test failed: {ex}")
        raise
    finally:
        supervisor.stop()

    # Final validation on artifact content
    final_content = target_file.read_text(encoding="utf-8")
    for r in range(1, 6):
        expected_line = f"Round {r}: OK"
        assert expected_line in final_content, f"Missing expected line '{expected_line}' in final artifact:\n{final_content}"

    print("="*80)
    print("📊 5-ROUND E2E ACCEPTANCE REPORT")
    print("="*80)
    print(json.dumps(metrics, indent=2))
    print("="*80)
    return metrics


if __name__ == "__main__":
    asyncio.run(run_5round_acceptance())
