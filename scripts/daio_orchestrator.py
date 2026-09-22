"""Universal Dual-Agent Iteration Orchestrator (DAIO) CLI Engine.

Usage:
  python3 daio_orchestrator.py \
    --url "https://chatgpt.com/g/..." \
    --phase "CURRENT_PHASE" \
    --cmd "python3 research/run_task.py" \
    --test "pytest tests/" \
    --max-iterations 15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from daio_bridge import UniversalCDPClient, discover_tab_by_url
from daio_taskboard import TaskboardManager
from daio_recovery import diagnose, checkpoint, write_rehydration_packet
from daio_sync import heartbeat, sync_status, mark_git

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DAIO-ORCHESTRATOR] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("DAIO_Orchestrator")

UNIVERSAL_PROMPT_APPENDIX = """

---
### 【系統指令：請架構師於回覆末尾輸出標準 JSON 控制區塊】
請在完成專業評析後，務必於回覆的最下方提供如下標準 JSON 格式（以 ```json ``` 包裹），以供 DAIO Orchestrator 自動解析狀態並推進下一階段：
```json
{
  "decision": "APPROVE", 
  "current_phase": "CURRENT_PHASE",
  "next_phase": "NEXT_PHASE",
  "action": "RUN",
  "human_approval_required": false,
  "instruction": "簡述下一步任務重點"
}
```
可選之 decision 值：`APPROVE`（進入下一 Phase）、`REVISE`（修改重送）、`REJECT`（重作）、`HUMAN_REVIEW`（需人工裁決）、`STOP`（終止閉環）。
"""


class UniversalDAIO:
    def __init__(
        self,
        url_pattern: str,
        initial_phase: str,
        exec_cmd: Optional[str] = None,
        test_cmd: Optional[str] = "pytest",
        report_file: Optional[str] = None,
        project_root: Optional[str] = None,
        max_iterations: int = 15,
        consecutive_errors_cap: int = 3,
        auto_git: bool = True,
    ):
        self.url_pattern = url_pattern
        self.current_phase = initial_phase
        self.exec_cmd = exec_cmd
        self.test_cmd = test_cmd
        self.report_file = report_file
        self.project_root = str(Path(project_root or os.getcwd()).resolve())
        self.max_iterations = max_iterations
        self.consecutive_errors_cap = consecutive_errors_cap
        self.auto_git = auto_git
        self.iteration_count = 0
        self.consecutive_errors = 0
        self.recovery = diagnose(self.project_root)
        self.rehydration_packet = write_rehydration_packet(self.project_root)
        logger.info("DAIO recovery preflight: %s | HEAD=%s | cached=%s",
                    self.recovery["health"], self.recovery["head"], self.recovery["checkpoint_head"])
        if self.recovery["health"] in ("STALE", "CHECKPOINT_MISSING"):
            logger.warning("Recoverable context state %s detected; generated %s and continuing.",
                           self.recovery["health"], self.rehydration_packet)
        mark_git(self.project_root)
        heartbeat(self.project_root, "engineer", current_phase=self.current_phase)
        self.sync = sync_status(self.project_root)
        logger.info("DAIO three-party sync preflight: %s", self.sync["overall"])
        self.taskboard = TaskboardManager(self.project_root)
        self.taskboard.upsert_task(
            task_id=f"phase_{self.current_phase.lower()}",
            title=f"Phase {self.current_phase} Execution & Audit",
            status="IN_PROGRESS",
            description=f"Active engineering task for {self.current_phase}",
            assigned_agent="Antigravity",
            phase=self.current_phase,
        )

    def run_command(self, cmd: str) -> Tuple[int, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = self.project_root
        logger.info(f"Executing: {cmd}")
        res = subprocess.run(
            cmd,
            shell=True,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            env=env,
        )
        return res.returncode, (res.stdout + "\n" + res.stderr).strip()

    def run_tests(self) -> bool:
        if not self.test_cmd:
            return True
        logger.info(f"Running Test Integrity Gate: {self.test_cmd}")
        code, out = self.run_command(self.test_cmd)
        if code != 0:
            logger.error(f"Test Integrity Gate Failed!\n{out}")
            return False
        logger.info("✓ Test Integrity Gate PASSED.")
        return True

    def commit_and_push(self, phase_name: str) -> bool:
        if not self.auto_git:
            return True
        logger.info(f"Syncing Git deliverables for {phase_name}...")
        self.run_command("git add .")
        self.run_command(f'git commit -m "feat(daio): automated iteration deliverables for {phase_name}"')
        code, out = self.run_command("git push origin main")
        if code != 0:
            logger.warning(f"Git push warning: {out}")
        return True

    def parse_architect_decision(self, response_text: str) -> Dict[str, Any]:
        # 1. Fenced JSON
        json_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        for j_str in reversed(json_matches):
            try:
                data = json.loads(j_str)
                if "decision" in data:
                    return data
            except Exception:
                continue

        # 2. Bare JSON
        bare_matches = re.findall(r"(\{\s*\"decision\"\s*:\s*\"[A-Z_]+\".*?\})", response_text, re.DOTALL)
        for b_str in reversed(bare_matches):
            try:
                data = json.loads(b_str)
                if "decision" in data:
                    return data
            except Exception:
                continue

        # 3. Semantic fallback
        upper_text = response_text.upper()
        if "HUMAN" in upper_text or "WAIT FOR HUMAN" in upper_text:
            return {"decision": "HUMAN_REVIEW", "action": "WAIT", "human_approval_required": True}
        if "STOP" in upper_text:
            return {"decision": "STOP", "action": "STOP", "human_approval_required": False}
        if "PASS" in upper_text or "APPROVE" in upper_text or "同意" in response_text:
            return {"decision": "APPROVE", "current_phase": self.current_phase, "next_phase": self.current_phase, "action": "RUN"}
        if "REVISE" in upper_text or "修正" in response_text:
            return {"decision": "REVISE", "current_phase": self.current_phase, "next_phase": self.current_phase, "action": "RUN"}

        return {"decision": "HUMAN_REVIEW", "instruction": "Could not parse unambiguous decision.", "human_approval_required": True}

    def prepare_report(self) -> str:
        if self.report_file and Path(self.report_file).exists():
            content = Path(self.report_file).read_text(encoding="utf-8")
        else:
            content = f"### Phase {self.current_phase} Execution Completed\n\nAll tasks and automated test integrity gates passed. Please audit and provide next instructions."
        packet = ""
        if self.rehydration_packet and Path(self.rehydration_packet).exists():
            packet = "\n\n---\n" + Path(self.rehydration_packet).read_text(encoding="utf-8")
        return content + packet + UNIVERSAL_PROMPT_APPENDIX.replace("CURRENT_PHASE", self.current_phase)

    async def run_loop(self):
        logger.info(f"Connecting to browser tab matching pattern: {self.url_pattern}")
        ws_url, tab_id, tab_title = discover_tab_by_url(self.url_pattern)
        logger.info(f"Connected to [{tab_title}] via CDP: {ws_url}")

        client = UniversalCDPClient(ws_url)
        await client.connect()

        try:
            while self.iteration_count < self.max_iterations:
                self.iteration_count += 1
                mark_git(self.project_root)
                heartbeat(self.project_root, "engineer", current_phase=self.current_phase, iteration=self.iteration_count)
                logger.info(f"\n{'='*70}\n>>> DAIO ITERATION #{self.iteration_count} | CURRENT PHASE: {self.current_phase}\n{'='*70}")

                # 1. Execute Work
                self.taskboard.upsert_task(
                    task_id=f"phase_{self.current_phase.lower()}",
                    title=f"Phase {self.current_phase} Execution",
                    status="IN_PROGRESS",
                    description=f"Running task command for {self.current_phase}",
                    assigned_agent="Antigravity",
                    phase=self.current_phase,
                )
                if self.exec_cmd:
                    logger.info(f"[Step 1/4] Running execution command: {self.exec_cmd}")
                    code, out = self.run_command(self.exec_cmd)
                    if code != 0:
                        self.consecutive_errors += 1
                        logger.error(f"Execution failed with code {code}:\n{out}")
                        self.taskboard.upsert_task(
                            task_id=f"phase_{self.current_phase.lower()}",
                            title=f"Phase {self.current_phase} Execution",
                            status="BLOCKED",
                            description=f"Execution error code {code}",
                            assigned_agent="Antigravity",
                            phase=self.current_phase,
                        )
                        if self.consecutive_errors >= self.consecutive_errors_cap:
                            logger.error("Consecutive error cap reached! Halting for Human Review.")
                            break
                        continue

                # 2. Test Integrity Gate
                self.taskboard.upsert_task(
                    task_id=f"phase_{self.current_phase.lower()}",
                    title=f"Phase {self.current_phase} Verification",
                    status="TESTING",
                    description="Running automated test integrity gate",
                    assigned_agent="Antigravity",
                    phase=self.current_phase,
                )
                if not self.run_tests():
                    self.consecutive_errors += 1
                    logger.error("Test Integrity Gate failed! Halting submission to Architect.")
                    self.taskboard.upsert_task(
                        task_id=f"phase_{self.current_phase.lower()}",
                        title=f"Phase {self.current_phase} Verification",
                        status="BLOCKED",
                        description="Test gate failed",
                        assigned_agent="Antigravity",
                        phase=self.current_phase,
                    )
                    break

                # 3. Git Sync
                self.commit_and_push(self.current_phase)

                # 4. Transmit Report to Web LLM
                logger.info(f"[Step 2/4] Transmitting report to Web LLM via CDP...")
                self.taskboard.upsert_task(
                    task_id=f"phase_{self.current_phase.lower()}",
                    title=f"Phase {self.current_phase} Audit & Review",
                    status="REVIEW",
                    description="Transmitted to Architect via Chrome CDP. Waiting for review stream...",
                    assigned_agent="Architect (Web LLM)",
                    phase=self.current_phase,
                )
                report_body = self.prepare_report()
                send_res = await client.send_message(report_body)

                if not send_res.get("success"):
                    self.consecutive_errors += 1
                    logger.error(f"CDP Communication error: {send_res.get('error')}")
                    if self.consecutive_errors >= self.consecutive_errors_cap:
                        break
                    await asyncio.sleep(5)
                    continue

                # 5. Parse Decision
                logger.info("[Step 3/4] Parsing Architect's response...")
                reply_text = send_res.get("reply", "")
                heartbeat(self.project_root, "architect", current_phase=self.current_phase, iteration=self.iteration_count, session_ref=self.url_pattern)
                decision = self.parse_architect_decision(reply_text)
                logger.info(f"Parsed Decision:\n{json.dumps(decision, indent=2, ensure_ascii=False)}")

                # 6. Dispatch Next Action
                dec_type = decision.get("decision", "HUMAN_REVIEW").upper()
                next_p = decision.get("next_phase", self.current_phase)
                instr = decision.get("instruction", "No specific instruction.")

                self.taskboard.log_event(
                    iteration=self.iteration_count,
                    phase=self.current_phase,
                    decision=dec_type,
                    agent="Architect",
                    summary=instr,
                )

                if dec_type == "APPROVE":
                    logger.info(f"★ APPROVAL GRANTED! Advancing to: {next_p}")
                    self.taskboard.upsert_task(
                        task_id=f"phase_{self.current_phase.lower()}",
                        title=f"Phase {self.current_phase}",
                        status="DONE",
                        description=f"Approved by Architect: {instr}",
                        assigned_agent="Architect",
                        phase=self.current_phase,
                    )
                    self.consecutive_errors = 0
                    if next_p == self.current_phase or not next_p:
                        logger.info("Milestone stabilized. Loop completed.")
                        break
                    self.current_phase = next_p
                    self.taskboard.upsert_task(
                        task_id=f"phase_{self.current_phase.lower()}",
                        title=f"Phase {self.current_phase}",
                        status="IN_PROGRESS",
                        description=f"Initiating next milestone: {self.current_phase}",
                        assigned_agent="Antigravity",
                        phase=self.current_phase,
                    )
                elif dec_type == "REVISE":
                    logger.warning(f"Revision requested for {self.current_phase}. Re-executing...")
                    self.taskboard.upsert_task(
                        task_id=f"phase_{self.current_phase.lower()}",
                        title=f"Phase {self.current_phase} (Revision)",
                        status="IN_PROGRESS",
                        description=f"Revision requested: {instr}",
                        assigned_agent="Antigravity",
                        phase=self.current_phase,
                    )
                    continue
                elif dec_type == "HUMAN_REVIEW" or decision.get("human_approval_required"):
                    logger.warning(f"!!! HUMAN REVIEW REQUIRED AT PHASE: {self.current_phase} !!!")
                    self.taskboard.upsert_task(
                        task_id=f"phase_{self.current_phase.lower()}",
                        title=f"Phase {self.current_phase}",
                        status="BLOCKED",
                        description=f"Human review required: {instr}",
                        assigned_agent="Human Operator",
                        phase=self.current_phase,
                    )
                    print(f"\nInstruction: {instr}\n")
                    break
                elif dec_type == "STOP":
                    logger.info("STOP decision received. Research cycle completed.")
                    self.taskboard.upsert_task(
                        task_id=f"phase_{self.current_phase.lower()}",
                        title=f"Phase {self.current_phase}",
                        status="DONE",
                        description="Cycle stopped gracefully.",
                        assigned_agent="Architect",
                        phase=self.current_phase,
                    )
                    break
                else:
                    logger.warning(f"Unknown decision type {dec_type}. Pausing.")
                    break

                await asyncio.sleep(2.0)
        finally:
            mark_git(self.project_root)
            heartbeat(self.project_root, "engineer", current_phase=self.current_phase, iteration=self.iteration_count)
            checkpoint(self.project_root, agent="DAIO-Orchestrator", current_phase=self.current_phase, iteration=self.iteration_count)
            await client.close()


def main():
    parser = argparse.ArgumentParser(description="Universal Dual-Agent Iteration Orchestrator (DAIO)")
    parser.add_argument("--config", default=None, help="Path to declarative JSON config file (e.g. daio_config.json)")
    parser.add_argument("--url", default=None, help="Target Web LLM URL substring or pattern")
    parser.add_argument("--phase", default="PHASE_1", help="Initial phase name")
    parser.add_argument("--cmd", default=None, help="Execution command for current phase")
    parser.add_argument("--test", default="pytest tests/", help="Test gate command")
    parser.add_argument("--report", default=None, help="Path to markdown report file")
    parser.add_argument("--max-iterations", type=int, default=15, help="Maximum loop iterations")
    args = parser.parse_args()

    # Load from config file if provided
    cfg = {}
    if args.config and Path(args.config).exists():
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    target_url = args.url or cfg.get("target_browser_url", "chatgpt.com")
    init_phase = cfg.get("current_phase", args.phase)
    exec_cmd = args.cmd or cfg.get("execution_command")
    test_cmd = args.test or cfg.get("test_gate_command", "pytest tests/")
    report_file = args.report or cfg.get("report_file_path")
    max_iters = cfg.get("max_iterations", args.max_iterations)

    daio = UniversalDAIO(
        url_pattern=target_url,
        initial_phase=init_phase,
        exec_cmd=exec_cmd,
        test_cmd=test_cmd,
        report_file=report_file,
        project_root=cfg.get("project_root", "."),
        max_iterations=max_iters,
    )
    asyncio.run(daio.run_loop())


if __name__ == "__main__":
    main()
