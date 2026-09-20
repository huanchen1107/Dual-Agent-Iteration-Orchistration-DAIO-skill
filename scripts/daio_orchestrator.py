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
        self.project_root = project_root or os.getcwd()
        self.max_iterations = max_iterations
        self.consecutive_errors_cap = consecutive_errors_cap
        self.auto_git = auto_git
        self.iteration_count = 0
        self.consecutive_errors = 0

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
        return content + UNIVERSAL_PROMPT_APPENDIX.replace("CURRENT_PHASE", self.current_phase)

    async def run_loop(self):
        logger.info(f"Connecting to browser tab matching pattern: {self.url_pattern}")
        ws_url, tab_id, tab_title = discover_tab_by_url(self.url_pattern)
        logger.info(f"Connected to [{tab_title}] via CDP: {ws_url}")

        client = UniversalCDPClient(ws_url)
        await client.connect()

        try:
            while self.iteration_count < self.max_iterations:
                self.iteration_count += 1
                logger.info(f"\n{'='*70}\n>>> DAIO ITERATION #{self.iteration_count} | CURRENT PHASE: {self.current_phase}\n{'='*70}")

                # 1. Execute Work
                if self.exec_cmd:
                    logger.info(f"[Step 1/4] Running execution command: {self.exec_cmd}")
                    code, out = self.run_command(self.exec_cmd)
                    if code != 0:
                        self.consecutive_errors += 1
                        logger.error(f"Execution failed with code {code}:\n{out}")
                        if self.consecutive_errors >= self.consecutive_errors_cap:
                            logger.error("Consecutive error cap reached! Halting for Human Review.")
                            break
                        continue

                # 2. Test Integrity Gate
                if not self.run_tests():
                    self.consecutive_errors += 1
                    logger.error("Test Integrity Gate failed! Halting submission to Architect.")
                    break

                # 3. Git Sync
                self.commit_and_push(self.current_phase)

                # 4. Transmit Report to Web LLM
                logger.info(f"[Step 2/4] Transmitting report to Web LLM via CDP...")
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
                decision = self.parse_architect_decision(reply_text)
                logger.info(f"Parsed Decision:\n{json.dumps(decision, indent=2, ensure_ascii=False)}")

                # 6. Dispatch Next Action
                dec_type = decision.get("decision", "HUMAN_REVIEW").upper()
                next_p = decision.get("next_phase", self.current_phase)

                if dec_type == "APPROVE":
                    logger.info(f"★ APPROVAL GRANTED! Advancing to: {next_p}")
                    self.consecutive_errors = 0
                    if next_p == self.current_phase or not next_p:
                        logger.info("Milestone stabilized. Loop completed.")
                        break
                    self.current_phase = next_p
                elif dec_type == "REVISE":
                    logger.warning(f"Revision requested for {self.current_phase}. Re-executing...")
                    continue
                elif dec_type == "HUMAN_REVIEW" or decision.get("human_approval_required"):
                    logger.warning(f"!!! HUMAN REVIEW REQUIRED AT PHASE: {self.current_phase} !!!")
                    print(f"\nInstruction: {decision.get('instruction', 'Review required')}\n")
                    break
                elif dec_type == "STOP":
                    logger.info("STOP decision received. Research cycle completed.")
                    break
                else:
                    logger.warning(f"Unknown decision type {dec_type}. Pausing.")
                    break

                await asyncio.sleep(2.0)
        finally:
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
        max_iterations=max_iters,
    )
    asyncio.run(daio.run_loop())


if __name__ == "__main__":
    main()
