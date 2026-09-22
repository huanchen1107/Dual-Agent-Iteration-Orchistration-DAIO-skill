"""DAIO Visual Taskboard Generator & State Manager.

Generates:
1. taskboard.json (Machine-readable state)
2. TASKBOARD.md (Markdown Kanban table + Market Data Hub + Blind Replay Matrix)
3. taskboard.html (Rich interactive Dark-Mode Kanban Dashboard + Live Inspector + Data Hub + Replay Studio)
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class TaskboardManager:
    def __init__(self, output_dir: str = "."):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.output_dir / "taskboard.json"
        self.md_file = self.output_dir / "TASKBOARD.md"
        self.html_file = self.output_dir / "taskboard.html"
        self.tasks: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.dialogue_history: List[Dict[str, Any]] = []
        self.active_turn: str = "Antigravity"
        self.active_turn_description: str = ""
        self.active_work_detail: Dict[str, Any] = {}
        self.market_data_inventory: Dict[str, Any] = {}
        self.blind_replay_matrix: Dict[str, Any] = {}
        self.sync_health: Dict[str, Any] = {}
        self.project_sections: Dict[str, Any] = {}
        self.updated_at: str = datetime.now().isoformat()
        self.load()

    def load(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.updated_at = data.get("updated_at", datetime.now().isoformat())
                    self.tasks = data.get("tasks", [])
                    self.history = data.get("history", [])
                    self.dialogue_history = data.get("dialogue_history", [])
                    self.active_turn = data.get("active_turn", "Antigravity")
                    self.active_turn_description = data.get("active_turn_description", "")
                    self.active_work_detail = data.get("active_work_detail", {})
                    self.market_data_inventory = data.get("market_data_inventory", {})
                    self.blind_replay_matrix = data.get("blind_replay_matrix", {})
            except Exception:
                pass
        self._ensure_dynamic_sections()

    def _ensure_dynamic_sections(self):
        """Populate or update market data inventory and blind replay matrix if available."""
        # -1. Optional project adapter sections (domain-neutral core boundary)
        try:
            from scripts.daio_adapter import collect_sections
            self.project_sections = collect_sections(self.output_dir)
        except Exception:
            self.project_sections = {}

        # 0. DAIO three-party sync health
        try:
            from scripts.daio_sync import sync_status, healing_plan
            self.sync_health = sync_status(self.output_dir)
            self.sync_health["healing_plan"] = healing_plan(self.output_dir)
        except Exception:
            self.sync_health = {}

        # Compatibility aliases for legacy dashboard renderers.
        # Data now comes only from an explicitly enabled project adapter.
        self.market_data_inventory = self.project_sections.get("market_data_inventory", {})
        self.blind_replay_matrix = self.project_sections.get("blind_replay_matrix", {})

    def save(self):
        self._ensure_dynamic_sections()
        data = {
            "updated_at": datetime.now().isoformat(),
            "active_turn": self.active_turn,
            "active_turn_description": self.active_turn_description,
            "dialogue_history": self.dialogue_history,
            "tasks": self.tasks,
            "history": self.history,
            "active_work_detail": self.active_work_detail,
            "market_data_inventory": self.market_data_inventory,
            "blind_replay_matrix": self.blind_replay_matrix,
            "sync_health": self.sync_health,
            "project_sections": self.project_sections,
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.generate_markdown()
        self.generate_html()

    def set_active_work_detail(
        self,
        phase: str,
        title: str,
        steps: List[Dict[str, str]],
        metrics: Optional[Dict[str, Any]] = None,
        narrative: str = "",
    ):
        """Set rich active execution details for live UI rendering."""
        self.active_work_detail = {
            "phase": phase,
            "title": title,
            "steps": steps,
            "metrics": metrics or {},
            "narrative": narrative,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.save()

    def upsert_task(
        self,
        task_id: str,
        title: str,
        status: str,  # "TODO", "IN_PROGRESS", "TESTING", "REVIEW", "DONE", "BLOCKED"
        description: str = "",
        assigned_agent: str = "Antigravity",
        phase: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in self.tasks:
            if t["id"] == task_id:
                t["title"] = title
                t["status"] = status
                t["description"] = description
                t["assigned_agent"] = assigned_agent
                t["phase"] = phase
                t["updated_at"] = now
                if metadata:
                    t.setdefault("metadata", {}).update(metadata)
                self.save()
                return

        self.tasks.append({
            "id": task_id,
            "title": title,
            "status": status,
            "description": description,
            "assigned_agent": assigned_agent,
            "phase": phase,
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {},
        })
        self.save()

    def log_event(self, iteration: int, phase: str, decision: str, agent: str, summary: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history.append({
            "timestamp": now,
            "iteration": iteration,
            "phase": phase,
            "decision": decision,
            "agent": agent,
            "summary": summary,
        })
        self.save()

    def generate_markdown(self):
        lines = [
            "# 📋 DAIO Dual-Agent Interactive Taskboard & System Status",
            f"*Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
            "## 🔄 DAIO Sync Health\n",
            f"- Overall: `{self.sync_health.get('overall', 'UNKNOWN')}` | Canonical HEAD: `{self.sync_health.get('head', 'UNKNOWN')}`\n",
            "| Participant | State | Checkpoint HEAD | Last Heartbeat |",
            "| :--- | :---: | :--- | :--- |",
            *[f"| {name} | `{item.get('state','UNKNOWN')}` | `{item.get('checkpoint_head','NONE')}` | {item.get('heartbeat_at','-')} |" for name,item in self.sync_health.get("participants",{}).items()],
            "",
            "## 🎯 專案里程碑與看板狀態 (Kanban Status)\n",
            "| ID | Phase | Task Title | Status | Agent | Last Update |",
            "| :--- | :--- | :--- | :---: | :---: | :--- |",
        ]
        status_icons = {
            "TODO": "📝 TODO",
            "IN_PROGRESS": "⚙️ IN_PROGRESS",
            "TESTING": "🧪 TESTING",
            "REVIEW": "🧐 REVIEW (Architect)",
            "DONE": "✅ DONE",
            "BLOCKED": "🛑 BLOCKED",
        }
        for t in self.tasks:
            st = status_icons.get(t["status"], t["status"])
            lines.append(f"| `{t['id']}` | **{t['phase']}** | {t['title']} | {st} | `{t['assigned_agent']}` | {t['updated_at']} |")

        # Optional domain UI is opaque to DAIO core.
        try:
            from scripts.daio_adapter import render_sections
            adapter_rendered = render_sections(self.output_dir, self.project_sections)
            if adapter_rendered.get("markdown"):
                lines.append(adapter_rendered["markdown"])
        except Exception:
            pass

        lines.append("\n## 📜 雙 Agent 歷史審計決策串流 (Recent Decision Stream)\n")
        lines.append("| Time | Iter # | Phase | Decision | Auditor Agent | Summary |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
        for h in reversed(self.history[-15:]):
            lines.append(f"| {h['timestamp']} | #{h['iteration']} | **{h['phase']}** | `{h['decision']}` | {h['agent']} | {h['summary'][:60]}... |")

        with open(self.md_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def generate_html(self):
        columns = [
            ("TODO", "Backlog & Planned", "#64748b", "📝"),
            ("IN_PROGRESS", "In Progress (Execution)", "#3b82f6", "⚙️"),
            ("TESTING", "Test Integrity Gate", "#8b5cf6", "🧪"),
            ("REVIEW", "Architect Review (CDP)", "#f59e0b", "🧐"),
            ("DONE", "Approved & Verified", "#10b981", "✅"),
            ("BLOCKED", "Human Review / Blocked", "#ef4444", "🛑"),
        ]

        cols_html = ""
        for status_key, title, color, icon in columns:
            col_tasks = [t for t in self.tasks if t["status"] == status_key]
            cards_html = ""
            for t in col_tasks:
                meta_tags = "".join(f'<span class="badge">{k}: {v}</span>' for k, v in t.get("metadata", {}).items())
                cards_html += f"""
                <div class="card" style="border-left-color: {color};">
                    <div class="card-header">
                        <span class="phase-tag">{t.get('phase', '')}</span>
                        <span class="agent-tag">{t.get('assigned_agent', '')}</span>
                    </div>
                    <div class="card-title">{t.get('title', '')}</div>
                    <div class="card-desc">{t.get('description', '')}</div>
                    <div class="card-footer">
                        <span class="timestamp">{t.get('updated_at', '')}</span>
                        <div class="meta-tags">{meta_tags}</div>
                    </div>
                </div>
                """
            if not cards_html:
                cards_html = '<div class="empty-col">No active tasks</div>'

            cols_html += f"""
            <div class="column">
                <div class="col-header" style="border-bottom-color: {color};">
                    <span>{icon} {title}</span>
                    <span class="count-badge" style="background-color: {color}22; color: {color};">{len(col_tasks)}</span>
                </div>
                <div class="col-body">
                    {cards_html}
                </div>
            </div>
            """


        # DAIO three-party synchronization health panel
        sync_cards = ""
        state_symbol = {"SYNCED":"●","LAGGING":"●","MISSING":"●"}
        for name,item in self.sync_health.get("participants",{}).items():
            state=item.get("state","UNKNOWN")
            action=next((a.get("action") for a in self.sync_health.get("healing_plan",{}).get("actions",[]) if a.get("participant")==name),"NONE")
            sync_cards += f"""
            <div class="sync-health-card sync-{state.lower()}">
                <div class="sync-health-name">{state_symbol.get(state,"●")} {name.upper()}</div>
                <div class="sync-health-state">{state}</div>
                <div class="sync-health-meta">HEAD: {str(item.get('checkpoint_head','NONE'))[:12]}</div>
                <div class="sync-health-meta">Heartbeat: {item.get('heartbeat_at','-')}</div>
                <div class="sync-health-action">Healing: {action}</div>
            </div>"""
        sync_health_html = f"""
        <div class="sync-health-panel">
            <div class="sync-health-header">
                <strong>🔄 DAIO Three-Party Sync Health</strong>
                <span>Overall: {self.sync_health.get('overall','UNKNOWN')} · Canonical HEAD: {str(self.sync_health.get('head','UNKNOWN'))[:12]}</span>
            </div>
            <div class="sync-health-grid">{sync_cards}</div>
        </div>
        """

        # Compute progress metrics dynamically
        review_task = next((t for t in self.tasks if t.get("status") in ["REVIEW", "BLOCKED"]), None)
        active_task = next((t for t in self.tasks if t.get("status") in ["IN_PROGRESS", "TESTING"]), None)
        done_tasks = [t for t in self.tasks if t.get("status") == "DONE"]
        last_done_task = done_tasks[-1] if done_tasks else None
        
        last_approved_issue = last_done_task.get("issue_number", last_done_task.get("id", "")) if last_done_task else ""
        review_issue = review_task.get("issue_number", review_task.get("id", "")) if review_task else ""
        active_issue = active_task.get("issue_number", active_task.get("id", "")) if active_task else ""

        if self.tasks:
            dynamic_milestones = []
            for t in self.tasks:
                phase_id = t.get("phase", t.get("id", ""))
                iss = t.get("issue_number", "")
                title = t.get("title", "")
                if ":" in title:
                    short_label = (f"[{iss}] " if iss else "") + title.split(":", 1)[0].strip() + ": " + title.split(":", 1)[1].strip()[:8]
                else:
                    short_label = (f"[{iss}] " if iss else "") + title[:15]
                dynamic_milestones.append((t.get("id"), short_label, t.get("status", "TODO"), t.get("phase", "")))

            completed_count = sum(1 for _, _, status, _ in dynamic_milestones if status == "DONE")
            total_milestones = len(dynamic_milestones)
            progress_pct = int(round((completed_count / total_milestones) * 100)) if total_milestones > 0 else 0

            stepper_items_html = ""
            for t_id, label, status, phase_id in dynamic_milestones:
                if status == "DONE":
                    cls = "step-done"
                    icon = "✓"
                    badge = "DONE"
                elif status in ["IN_PROGRESS", "TESTING", "REVIEW"]:
                    cls = "step-active"
                    icon = "⚡"
                    badge = "ACTIVE"
                else:
                    cls = "step-pending"
                    icon = "🔒"
                    badge = "PLAN"
                stepper_items_html += f"""
                <div class="stepper-item {cls}">
                    <div class="step-circle">{icon}</div>
                    <div class="step-label">{label}</div>
                    <span class="step-status">{badge}</span>
                </div>
                """
            all_done = (completed_count == total_milestones and total_milestones > 0)
        else:
            completed_count = 0
            total_milestones = 0
            progress_pct = 0
            stepper_items_html = ""
            all_done = False

        if all_done:
            top_btn_html = '<button class="btn btn-approve btn-top-quick btn-completed" disabled><span>✨ 本期全數任務已批准封版</span></button>'
        elif review_task:
            top_btn_html = f'<button class="btn btn-approve btn-top-quick" onclick="handleHumanDecision(\'APPROVE\', \'{review_issue}\')"><span>✅ 批准當前審批門 [{review_issue}]</span></button>'
        elif last_done_task:
            top_btn_html = f'<button class="btn btn-approve btn-top-quick btn-completed" disabled><span>✨ [{last_approved_issue} 已批准生效] 正在執行 {active_issue or "下階段"}</span></button>'
        else:
            top_btn_html = '<button class="btn btn-approve btn-top-quick" onclick="handleHumanDecision(\'APPROVE\')"><span>✅ 快速批准當前階段</span></button>'

        progress_html = f"""
        <div class="progress-container">
            <div class="progress-header">
                <div class="progress-title">
                    <span style="display: flex; align-items: center; gap: 8px;">🚀 <strong>專案整體推進進度 (Overall Pipeline)</strong></span>
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <strong style="color: #38bdf8; font-size: 16px;">{completed_count} / {total_milestones} 里程碑完成 ({progress_pct}%)</strong>
                        {top_btn_html}
                    </div>
                </div>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: {progress_pct}%;">
                    <div class="progress-shine"></div>
                </div>
            </div>
            <div class="stepper-bar">
                {stepper_items_html}
            </div>
        </div>
        """

        # Determine active turn
        active_task = next((t for t in self.tasks if t.get("status") in ["IN_PROGRESS", "TESTING", "REVIEW"]), None)
        active_agent = "Antigravity (Lead Engineer)"
        standby_agent = "ChatGPT (Lead Architect)"
        turn_action = "Executing algorithms & test suite"
        
        if active_task and active_task.get("status") == "REVIEW":
            active_agent = "ChatGPT (Lead Architect)"
            standby_agent = "Antigravity (Lead Engineer)"
            turn_action = "Auditing evidence & making architectural verdict"
        elif active_task:
            active_agent = f"{active_task.get('assigned_agent', 'Antigravity')} (Lead Engineer)"
            standby_agent = "ChatGPT (Lead Architect)"
            turn_action = f"Working on {active_task.get('title')}"

        last_event = self.history[-1] if self.history else {"agent": "System", "summary": "System initialized.", "timestamp": ""}

        # Build Dialogue Feed HTML dynamically
        bubbles_html = ""
        if self.dialogue_history:
            for d in self.dialogue_history:
                speaker = d.get("speaker", "")
                role = d.get("role", "")
                avatar = d.get("avatar", "🤖")
                ts = d.get("timestamp", "")
                txt = d.get("text", "").replace("\n", "<br/>")
                if "Architect" in role or "ChatGPT" in speaker:
                    bubble_cls = "architect-bubble"
                elif "Human" in role or "Owner" in role:
                    bubble_cls = "human-bubble"
                else:
                    bubble_cls = "engineer-bubble"
                bubbles_html += f"""
                <div class="chat-bubble {bubble_cls}">
                    <div class="bubble-header">
                        <span class="avatar">{avatar}</span>
                        <strong>{speaker}</strong>
                        <span class="role-badge">{role}</span>
                        <span class="bubble-time">{ts}</span>
                    </div>
                    <div class="bubble-text">
                        {txt}
                    </div>
                </div>
                """

        dialogue_html = f"""
        <div class="dialogue-stage">
            <div class="turn-banner">
                <div class="turn-indicator">
                    <span class="pulse-dot"></span>
                    <span>當前行動回合 (Active Turn)：<strong style="color: #38bdf8;">{active_agent}</strong></span>
                </div>
                <div class="turn-status-badge">
                    <span>⚡ 狀態：{turn_action}</span>
                </div>
            </div>
            <div class="chat-bubbles-container">
                {bubbles_html}
            </div>
        </div>
        """

        # Build Active Work Inspector HTML
        inspector_html = ""
        if self.active_work_detail:
            wd = self.active_work_detail
            steps_items = ""
            for s in wd.get("steps", []):
                st_icon = "✅" if s.get("status") == "DONE" else ("⚡" if s.get("status") == "IN_PROGRESS" else "⏳")
                st_cls = "step-done-row" if s.get("status") == "DONE" else ("step-active-row" if s.get("status") == "IN_PROGRESS" else "step-pending-row")
                steps_items += f"""
                <div class="inspector-step-item {st_cls}">
                    <span class="step-icon">{st_icon}</span>
                    <div class="step-content">
                        <strong>{s.get('name', '')}</strong>
                        <p>{s.get('detail', '')}</p>
                    </div>
                </div>
                """
            
            metrics_chips = ""
            for m_k, m_v in wd.get("metrics", {}).items():
                metrics_chips += f"""
                <div class="metric-chip">
                    <span class="metric-label">{m_k}</span>
                    <span class="metric-val">{m_v}</span>
                </div>
                """
            
            if all_done:
                prompt_text = "✨ 全數階段任務已全數批准並完成驗證！"
                human_buttons_html = '<button class="btn btn-approve btn-completed" disabled><span class="btn-icon">✨</span> 所有任務已完成</button>'
            elif review_task:
                prompt_text = f"🚨 <strong>[{review_issue}] 審批門待裁定</strong>：ChatGPT 架構師已提交審計報告，請 Human Owner 裁定："
                human_buttons_html = f'<button class="btn btn-approve" onclick="handleHumanDecision(\'APPROVE\', \'{review_issue}\')"><span class="btn-icon">✅</span> 批准通過 [{review_issue}]</button><button class="btn btn-revise" onclick="handleHumanDecision(\'REVISE\', \'{review_issue}\')"><span class="btn-icon">🔄</span> 要求修改</button><button class="btn btn-pause" onclick="handleHumanDecision(\'PAUSE\')"><span class="btn-icon">⏸️</span> 暫停</button>'
            elif last_done_task:
                prompt_text = f"✨ <strong>[{last_approved_issue}] 批准已正式生效！</strong> 工程端正在自動執行 [{active_issue or '下階段任務'}]，無需重複批准。"
                human_buttons_html = f'<button class="btn btn-approve btn-completed" disabled><span class="btn-icon">✨</span> [{last_approved_issue}] 批准已生效</button><button class="btn btn-pause" onclick="handleHumanDecision(\'PAUSE\')"><span class="btn-icon">⏸️</span> 暫停循環 (Pause Orchestrator)</button>'
            else:
                prompt_text = f"當前進度進行中（{completed_count}/{total_milestones}）："
                human_buttons_html = '<button class="btn btn-approve" onclick="handleHumanDecision(\'APPROVE\')"><span class="btn-icon">✅</span> 快速批准當前階段</button><button class="btn btn-pause" onclick="handleHumanDecision(\'PAUSE\')"><span class="btn-icon">⏸️</span> 暫停</button>'

            inspector_html = f"""
            <div class="work-inspector-card">
                <div class="inspector-header">
                    <div class="inspector-title">
                        <span class="pulse-dot"></span>
                        <span>🔍 即時工程執行細節 (Live Work Inspector) — <strong style="color: #38bdf8;">{wd.get('phase', '')}</strong></span>
                    </div>
                    <span class="inspector-badge">{wd.get('updated_at', '')}</span>
                </div>
                <div class="inspector-narrative">{wd.get('narrative', '')}</div>
                {f'<div class="metric-chips-row">{metrics_chips}</div>' if metrics_chips else ''}
                <div class="inspector-steps-list">
                    {steps_items}
                </div>

                <div class="human-actions-bar">
                    <div class="action-prompt-text">
                        <span>⚖️ <strong>人類審批治理門 (Human Governance Gate)</strong>：{prompt_text}</span>
                    </div>
                    <div class="action-buttons-group">
                        {human_buttons_html}
                    </div>
                </div>
            </div>
            """

        # Optional project adapter HTML; DAIO core does not know domain schema.
        adapter_html = ""
        try:
            from daio_adapter import render_sections
            adapter_html = render_sections(self.output_dir, self.project_sections).get("html", "")
        except Exception:
            adapter_html = ""

        history_rows = ""
        for h in reversed(self.history[-15:]):
            badge_cls = "approved" if h.get("decision") == "APPROVE" else ("review" if "HUMAN" in h.get("decision", "") else "revise")
            history_rows += f"""
            <tr>
                <td>{h.get('timestamp', '')}</td>
                <td>#{h.get('iteration', '')}</td>
                <td><strong>{h.get('phase', '')}</strong></td>
                <td><span class="decision-badge {badge_cls}">{h.get('decision', '')}</span></td>
                <td>{h.get('agent', '')}</td>
                <td>{h.get('summary', '')}</td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DAIO Dual-Agent Visual Taskboard & Live Dialogue</title>
    <style>
        :root {{
            --bg-primary: #0b1329;
            --bg-secondary: #131f37;
            --bg-card: #1a2846;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border-color: #243556;
            --accent: #38bdf8;
            --architect-color: #f59e0b;
            --engineer-color: #38bdf8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: var(--bg-primary); color: var(--text-primary); padding: 20px; min-height: 100vh; overflow-x: hidden; }}
        @media (max-width: 600px) {{ body {{ padding: 12px; }} }}

        header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border-color); }}
        .header-title {{ font-size: 20px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }}
        .live-pulse {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #10b981; box-shadow: 0 0 10px #10b981; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
        
        /* Dialogue Stage Styles */
        .dialogue-stage {{ background: linear-gradient(135deg, #131f37 0%, #0f172a 100%); border: 1px solid var(--border-color); border-radius: 12px; padding: 18px; margin-bottom: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
        .turn-banner {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; padding-bottom: 12px; margin-bottom: 14px; border-bottom: 1px solid #1e293b; }}
        .turn-indicator {{ font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
        .pulse-dot {{ width: 8px; height: 8px; background: #38bdf8; border-radius: 50%; box-shadow: 0 0 8px #38bdf8; flex-shrink: 0; }}
        .turn-status-badge {{ background: #1e293b; border: 1px solid var(--border-color); padding: 4px 12px; border-radius: 20px; font-size: 12px; color: #cbd5e1; }}
        
        .chat-bubbles-container {{ display: flex; flex-direction: column; gap: 12px; max-height: 520px; overflow-y: auto; padding-right: 4px; }}
        .chat-bubble {{ background: var(--bg-card); border-radius: 10px; padding: 14px 16px; border-left: 4px solid; width: 100%; box-shadow: 0 2px 8px rgba(0,0,0,0.2); transition: transform 0.15s ease; }}
        .chat-bubble:hover {{ transform: translateX(2px); }}
        .architect-bubble {{ border-left-color: var(--architect-color); background: linear-gradient(135deg, #1a2846 0%, #1a233a 100%); }}
        .engineer-bubble {{ border-left-color: var(--engineer-color); background: linear-gradient(135deg, #132742 0%, #0f1e33 100%); }}
        .human-bubble {{ border-left-color: #10b981; background: linear-gradient(135deg, #0d2824 0%, #0a1f1c 100%); }}
        .human-bubble strong {{ color: #34d399; }}
        .bubble-header {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; font-size: 13px; }}
        .role-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.08); color: var(--text-secondary); }}
        .bubble-time {{ margin-left: auto; font-size: 11px; color: #64748b; }}
        .bubble-text {{ font-size: 13px; line-height: 1.6; color: #e2e8f0; word-break: break-word; }}
        
        /* Kanban Board Styles */
        .board {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 32px; }}
        @media (max-width: 1200px) {{
            .board {{ display: flex; overflow-x: auto; scroll-snap-type: x mandatory; padding-bottom: 14px; gap: 14px; -webkit-overflow-scrolling: touch; }}
            .column {{ min-width: 280px; flex: 0 0 280px; scroll-snap-align: start; }}
        }}
        .column {{ background: var(--bg-secondary); border-radius: 12px; border: 1px solid var(--border-color); display: flex; flex-direction: column; min-height: 480px; }}
        .col-header {{ padding: 14px 16px; font-weight: 600; font-size: 14px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid; background: #101a2e; border-top-left-radius: 12px; border-top-right-radius: 12px; }}
        .count-badge {{ padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 700; }}
        .col-body {{ padding: 12px; display: flex; flex-direction: column; gap: 10px; flex: 1; overflow-y: auto; max-height: 600px; }}
        
        .card {{ background: var(--bg-card); border-radius: 8px; padding: 12px; border: 1px solid var(--border-color); border-left-width: 4px; transition: transform 0.15s ease; }}
        .card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 11px; }}
        .phase-tag {{ background: #0284c722; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-weight: 600; }}
        .agent-tag {{ background: #64748b22; color: #cbd5e1; padding: 2px 6px; border-radius: 4px; }}
        .card-title {{ font-size: 13px; font-weight: 600; margin-bottom: 6px; color: #f1f5f9; line-height: 1.4; }}
        .card-desc {{ font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; line-height: 1.4; }}
        .card-footer {{ display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: #64748b; border-top: 1px solid #1e293b; padding-top: 6px; flex-wrap: wrap; gap: 4px; }}
        .badge {{ background: #334155; color: #94a3b8; padding: 1px 5px; border-radius: 4px; margin-left: 2px; }}
        .empty-col {{ color: #475569; font-size: 12px; text-align: center; margin-top: 40px; font-style: italic; }}

        /* Progress Bar & Dynamic Stepper Styles */
        .progress-container {{ background: linear-gradient(135deg, #131f37 0%, #0f172a 100%); border: 1px solid var(--border-color); border-radius: 12px; padding: 18px 20px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
        .progress-header {{ margin-bottom: 12px; }}
        .progress-title {{ font-size: 14px; font-weight: 600; color: #f1f5f9; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; width: 100%; }}
        .progress-bar-bg {{ width: 100%; height: 12px; background: #1e293b; border-radius: 6px; overflow: hidden; position: relative; border: 1px solid #334155; margin: 12px 0 16px 0; }}
        .progress-bar-fill {{ height: 100%; background: linear-gradient(90deg, #0284c7 0%, #38bdf8 50%, #10b981 100%); border-radius: 6px; position: relative; transition: width 0.5s ease; box-shadow: 0 0 12px rgba(56, 189, 248, 0.5); }}
        .progress-shine {{ position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent); animation: shine 2.5s infinite; }}
        @keyframes shine {{ 0% {{ transform: translateX(-100%); }} 100% {{ transform: translateX(100%); }} }}
        
        .stepper-bar {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }}
        @media (max-width: 600px) {{ .stepper-bar {{ grid-template-columns: repeat(2, 1fr); }} }}
        .stepper-item {{ display: flex; flex-direction: column; align-items: center; text-align: center; padding: 8px 6px; border-radius: 8px; background: var(--bg-card); border: 1px solid var(--border-color); position: relative; transition: transform 0.15s; min-width: 0; }}
        .stepper-item:hover {{ transform: translateY(-2px); }}
        .step-circle {{ width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; margin-bottom: 4px; flex-shrink: 0; }}
        .step-label {{ font-size: 11px; font-weight: 600; color: #cbd5e1; margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width: 100%; }}
        .step-status {{ font-size: 9px; padding: 1px 4px; border-radius: 3px; font-weight: 700; }}
        
        .stepper-item.step-done {{ border-color: #10b98144; background: #064e3b15; }}
        .stepper-item.step-done .step-circle {{ background: #10b981; color: #fff; box-shadow: 0 0 8px #10b98166; }}
        .stepper-item.step-done .step-status {{ background: #10b98122; color: #34d399; }}
        
        .stepper-item.step-active {{ border-color: #38bdf8; background: #0284c722; box-shadow: 0 0 10px rgba(56, 189, 248, 0.2); animation: activeGlow 2s infinite alternate; }}
        @keyframes activeGlow {{ 0% {{ border-color: #38bdf8; }} 100% {{ border-color: #f59e0b; }} }}
        .stepper-item.step-active .step-circle {{ background: #38bdf8; color: #0f172a; box-shadow: 0 0 10px #38bdf8; }}
        .stepper-item.step-active .step-status {{ background: #38bdf822; color: #38bdf8; }}
        
        .stepper-item.step-pending {{ border-color: #334155; opacity: 0.55; }}
        .stepper-item.step-pending .step-circle {{ background: #334155; color: #94a3b8; }}
        .stepper-item.step-pending .step-status {{ background: #33415522; color: #94a3b8; }}

        /* Active Work Inspector Styles */
        .work-inspector-card {{ background: linear-gradient(135deg, #16243e 0%, #0d1629 100%); border: 1px solid #38bdf844; border-radius: 12px; padding: 18px 20px; margin-bottom: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }}
        .inspector-header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid #243556; }}
        .inspector-title {{ font-size: 15px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .inspector-badge {{ background: #0284c722; color: #38bdf8; border: 1px solid #38bdf844; padding: 2px 8px; border-radius: 12px; font-size: 11px; }}
        .inspector-narrative {{ font-size: 13px; color: #e2e8f0; line-height: 1.5; margin-bottom: 14px; background: rgba(0,0,0,0.2); padding: 10px 14px; border-radius: 8px; border-left: 3px solid #38bdf8; }}
        .metric-chips-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }}
        .metric-chip {{ background: #1a2846; border: 1px solid #2b4068; padding: 8px 12px; border-radius: 8px; display: flex; flex-direction: column; gap: 2px; }}
        .metric-label {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
        .metric-val {{ font-size: 14px; font-weight: 700; color: #38bdf8; }}
        .inspector-steps-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .inspector-step-item {{ display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-radius: 8px; background: #131f37; border: 1px solid #243556; font-size: 13px; }}
        .inspector-step-item.step-done-row {{ border-left: 3px solid #10b981; }}
        .inspector-step-item.step-active-row {{ border-left: 3px solid #38bdf8; background: #0c203d; }}
        .inspector-step-item.step-pending-row {{ border-left: 3px solid #64748b; opacity: 0.6; }}
        .step-content strong {{ color: #f1f5f9; display: block; margin-bottom: 2px; }}
        .step-content p {{ color: #94a3b8; font-size: 12px; margin: 0; line-height: 1.4; }}

        /* Market Hub & Replay Matrix Sections */
        .market-hub-section, .replay-matrix-section {{ background: var(--bg-secondary); border-radius: 12px; border: 1px solid var(--border-color); padding: 18px 20px; margin-bottom: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
        .section-header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border-color); }}
        .section-title {{ font-size: 15px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .section-meta {{ font-size: 12px; color: var(--text-secondary); display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
        .section-meta strong {{ color: #38bdf8; }}

        .cat-tabs-bar {{ display: flex; gap: 8px; overflow-x: auto; margin-bottom: 14px; padding-bottom: 4px; }}
        .cat-tab-btn {{ background: #1a2846; border: 1px solid #2b4068; color: #cbd5e1; padding: 6px 14px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s; white-space: nowrap; display: flex; align-items: center; gap: 6px; }}
        .cat-tab-btn:hover {{ background: #243556; border-color: #38bdf8; color: #fff; }}
        .cat-tab-btn.active {{ background: #0284c7; border-color: #38bdf8; color: #fff; box-shadow: 0 0 10px rgba(56, 189, 248, 0.4); }}
        
        .cat-tab-panel {{ display: none; overflow-x: auto; }}
        .cat-tab-panel.active {{ display: block; }}
        .tf-badge {{ background: #0f172a; border: 1px solid #334155; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; color: #38bdf8; }}

        .replay-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
        .replay-card {{ background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px; }}
        .card-subtitle {{ font-size: 13px; font-weight: 700; color: #38bdf8; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }}
        .param-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
        .param-item {{ background: #131f37; border: 1px solid #243556; padding: 8px 10px; border-radius: 6px; }}
        .param-label {{ font-size: 10px; color: #94a3b8; display: block; }}
        .param-val {{ font-size: 14px; font-weight: 700; color: #f8fafc; }}

        .guards-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .guard-pill {{ background: #131f37; border: 1px solid #243556; border-radius: 6px; padding: 8px 10px; font-size: 12px; }}
        .guard-pill-header {{ display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }}
        .guard-id {{ background: #8b5cf622; color: #a78bfa; border: 1px solid #8b5cf644; padding: 1px 4px; border-radius: 3px; font-weight: 700; font-size: 10px; }}
        .guard-name {{ color: #f1f5f9; }}
        .guard-detail {{ color: #94a3b8; font-size: 11px; margin-left: 2px; }}

        /* Human Action Bar Styles */
        .human-actions-bar {{ margin-top: 16px; padding-top: 14px; border-top: 1px solid #243556; display: flex; flex-direction: column; gap: 10px; background: rgba(56, 189, 248, 0.04); padding: 14px; border-radius: 8px; border: 1px dashed #38bdf866; }}
        .action-prompt-text {{ font-size: 13px; color: #cbd5e1; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; line-height: 1.5; }}
        .action-buttons-group {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
        .btn {{ padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; border: none; transition: all 0.2s ease; display: inline-flex; align-items: center; gap: 6px; }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
        .btn-approve {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #fff; box-shadow: 0 0 15px rgba(16, 185, 129, 0.4); animation: btnPulse 2s infinite; }}
        @keyframes btnPulse {{ 0%, 100% {{ box-shadow: 0 0 10px rgba(16, 185, 129, 0.4); }} 50% {{ box-shadow: 0 0 20px rgba(16, 185, 129, 0.8); }} }}
        .btn-top-quick {{ padding: 6px 12px; font-size: 12px; border-radius: 6px; box-shadow: 0 0 10px rgba(16, 185, 129, 0.3); }}
        .btn-completed {{ background: linear-gradient(135deg, #059669 0%, #047857 100%) !important; color: #f8fafc !important; cursor: default !important; box-shadow: 0 0 12px rgba(16, 185, 129, 0.4) !important; animation: none !important; }}
        .btn-revise {{ background: #f59e0b22; color: #fbbf24; border: 1px solid #f59e0b66; }}
        .btn-revise:hover {{ background: #f59e0b33; }}
        .btn-pause {{ background: #334155; color: #cbd5e1; border: 1px solid #475569; }}

        /* Floating Toast */
        #daio-toast {{ position: fixed; top: 24px; right: 24px; background: #1e293b; border: 1px solid #38bdf8; color: #fff; padding: 14px 20px; border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); z-index: 9999; display: none; font-size: 13px; font-weight: 600; max-width: calc(100vw - 48px); }}

        /* Decision History Section */
        .history-section {{ background: var(--bg-secondary); border-radius: 12px; border: 1px solid var(--border-color); padding: 18px 20px; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
        .history-title {{ font-size: 16px; font-weight: 600; margin-bottom: 14px; color: #fff; }}
        table {{ width: 100%; min-width: 650px; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border-color); }}
        th {{ color: var(--text-secondary); font-weight: 600; background: #101a2e; white-space: nowrap; }}
        .decision-badge {{ padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; white-space: nowrap; }}
        .decision-badge.approved {{ background: #10b98122; color: #34d399; }}
        .decision-badge.revise {{ background: #f59e0b22; color: #fbbf24; }}
        .decision-badge.review {{ background: #ef444422; color: #f87171; }}
    
        .sync-health-panel{{margin:0 0 18px;padding:16px;border:1px solid #334155;border-radius:14px;background:#0f172a}}
        .sync-health-header{{display:flex;justify-content:space-between;gap:12px;margin-bottom:12px;color:#e2e8f0}}
        .sync-health-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}
        .sync-health-card{{padding:12px;border-radius:10px;border:1px solid #334155;background:#111827}}
        .sync-health-name{{font-weight:700}}.sync-health-state{{font-size:12px;margin:6px 0}}.sync-health-meta,.sync-health-action{{font-size:11px;color:#94a3b8;overflow-wrap:anywhere}}
        .sync-synced .sync-health-name{{color:#34d399}}.sync-lagging .sync-health-name{{color:#fbbf24}}.sync-missing .sync-health-name{{color:#f87171}}
        @media(max-width:800px){{.sync-health-grid{{grid-template-columns:1fr}}.sync-health-header{{flex-direction:column}}}}
</style>
    <script>
        function showToast(msg, duration = 3500) {{
            let toast = document.getElementById('daio-toast');
            if (!toast) {{
                toast = document.createElement('div');
                toast.id = 'daio-toast';
                document.body.appendChild(toast);
            }}
            toast.innerHTML = msg;
            toast.style.display = 'block';
            setTimeout(() => {{ toast.style.display = 'none'; }}, duration);
        }}

        function switchCatTab(evt, tabId) {{
            document.querySelectorAll('.cat-tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.cat-tab-panel').forEach(p => p.classList.remove('active'));
            evt.currentTarget.classList.add('active');
            const panel = document.getElementById(tabId);
            if (panel) panel.classList.add('active');
        }}

        let currentUpdatedAt = "{{self.updated_at}}";
        let timerSeconds = 3;

        async function handleHumanDecision(action) {{
            const allApproveBtns = document.querySelectorAll('.btn-approve');
            
            if (action === 'APPROVE') {{
                allApproveBtns.forEach(btn => {{
                    btn.disabled = true;
                    btn.style.pointerEvents = 'none';
                    btn.classList.add('btn-completed');
                    btn.onclick = null;
                    btn.innerHTML = '<span>✨ 已批准生效 (Approved)</span>';
                }});
                showToast('✅ <strong>已確認批准當前階段！</strong> 正在同步至後端資料庫...', 3000);

                try {{
                    if (window.location.protocol.startsWith('http')) {{
                        await fetch('/api/daio/action', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ action: 'APPROVE', comment: 'Owner 透過看板 UI 快速批准' }})
                        }});
                    }}
                }} catch (e) {{
                    console.log('Direct API sync fallback', e);
                }}
            }} else if (action === 'REVISE') {{
                const comment = prompt('請輸入修改指示：', '請重新檢驗參數');
                if (comment) {{
                    showToast('🔄 已記錄修改指示：' + comment);
                    try {{
                        if (window.location.protocol.startsWith('http')) {{
                            fetch('/api/daio/action', {{
                                method: 'POST',
                                headers: {{ 'Content-Type': 'application/json' }},
                                body: JSON.stringify({{ action: 'REVISE', comment: comment }})
                            }});
                        }}
                    }} catch (e) {{}}
                }}
            }} else {{
                showToast('⏸️ DAIO 自動循環已暫停。');
            }}
        }}

        async function checkLiveUpdate() {{
            try {{
                const res = await fetch('taskboard.json?_t=' + Date.now(), {{ cache: 'no-store' }});
                if (res.ok) {{
                    const data = await res.json();
                    if (data.updated_at && data.updated_at !== currentUpdatedAt) {{
                        currentUpdatedAt = data.updated_at;
                        window.location.reload();
                        return;
                    }}
                }}
            }} catch (e) {{}}
        }}

        setInterval(() => {{
            timerSeconds--;
            const countEl = document.getElementById('daio-countdown');
            if (countEl) countEl.textContent = Math.max(1, timerSeconds);
            if (timerSeconds <= 0) {{
                timerSeconds = 3;
                if (window.location.protocol === 'file:') {{
                    window.location.reload();
                }} else {{
                    checkLiveUpdate();
                }}
            }}
        }}, 1000);
    </script>
</head>
<body>
    <header>
        <div class="header-title">
            <span class="live-pulse"></span>
            DAIO 雙 Agent 即時對話與任務看板
        </div>
        <div style="font-size: 12px; color: var(--text-secondary); display: flex; align-items: center; gap: 8px;">
            <span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); padding: 3px 8px;">⚡ 雙向即時連線 (<span id="daio-countdown">3</span>s 自動同步)</span>
        </div>
    </header>

    {{sync_health_html}}\n        {{progress_html}}

    {{inspector_html}}

    {{dialogue_html}}

    {{adapter_html}}

    

    <div class="board">
        {{cols_html}}
    </div>

    <div class="history-section">
        <div class="history-title">📜 雙 Agent 歷史審計決策串流 (Audit Decision Stream)</div>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Iteration</th>
                    <th>Phase</th>
                    <th>Decision</th>
                    <th>Auditor Agent</th>
                    <th>Instruction / Assessment Summary</th>
                </tr>
            </thead>
            <tbody>
                {{history_rows}}
            </tbody>
        </table>
    </div>
</body>
</html>
        """
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(html)


if __name__ == "__main__":
    import sys
    mgr = TaskboardManager()
    mgr.save()
    print("Saved taskboard state and generated visual files.")
