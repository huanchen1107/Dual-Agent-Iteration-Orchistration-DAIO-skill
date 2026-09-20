"""DAIO Visual Taskboard Generator & State Manager.

Generates:
1. taskboard.json (Machine-readable state)
2. TASKBOARD.md (Markdown Kanban table)
3. taskboard.html (Rich interactive Dark-Mode Kanban Dashboard)
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
        self.load()

    def load(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.tasks = data.get("tasks", [])
                    self.history = data.get("history", [])
            except Exception:
                pass

    def save(self):
        data = {
            "updated_at": datetime.now().isoformat(),
            "tasks": self.tasks,
            "history": self.history,
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.generate_markdown()
        self.generate_html()

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
            "# 📋 DAIO Dual-Agent Interactive Taskboard",
            f"*Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
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

        lines.append("\n## 📜 Recent Decision Stream\n")
        lines.append("| Time | Iter # | Phase | Decision | Auditor Agent | Summary |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
        for h in reversed(self.history[-10:]):
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

        history_rows = ""
        for h in reversed(self.history[-15:]):
            badge_cls = "approved" if h["decision"] == "APPROVE" else ("review" if "HUMAN" in h["decision"] else "revise")
            history_rows += f"""
            <tr>
                <td>{h['timestamp']}</td>
                <td>#{h['iteration']}</td>
                <td><strong>{h['phase']}</strong></td>
                <td><span class="decision-badge {badge_cls}">{h['decision']}</span></td>
                <td>{h['agent']}</td>
                <td>{h['summary']}</td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DAIO Dual-Agent Visual Taskboard</title>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #182234;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border-color: #334155;
            --accent: #38bdf8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: var(--bg-primary); color: var(--text-primary); padding: 24px; min-height: 100vh; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border-color); }}
        .header-title {{ font-size: 24px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }}
        .live-pulse {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #10b981; box-shadow: 0 0 10px #10b981; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
        
        .board {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 32px; overflow-x: auto; }}
        .column {{ background: var(--bg-secondary); border-radius: 12px; border: 1px solid var(--border-color); display: flex; flex-direction: column; min-height: 480px; }}
        .col-header {{ padding: 14px 16px; font-weight: 600; font-size: 14px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid; background: #131d2e; border-top-left-radius: 12px; border-top-right-radius: 12px; }}
        .count-badge {{ padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 700; }}
        .col-body {{ padding: 12px; display: flex; flex-direction: column; gap: 10px; flex: 1; overflow-y: auto; }}
        
        .card {{ background: var(--bg-card); border-radius: 8px; padding: 12px; border: 1px solid var(--border-color); border-left-width: 4px; transition: transform 0.15s ease; }}
        .card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
        .card-header {{ display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 11px; }}
        .phase-tag {{ background: #0284c722; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-weight: 600; }}
        .agent-tag {{ background: #64748b22; color: #cbd5e1; padding: 2px 6px; border-radius: 4px; }}
        .card-title {{ font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #f1f5f9; }}
        .card-desc {{ font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; line-height: 1.4; }}
        .card-footer {{ display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: #64748b; border-top: 1px solid #1e293b; padding-top: 6px; }}
        .badge {{ background: #334155; color: #94a3b8; padding: 1px 5px; border-radius: 4px; margin-left: 4px; }}
        .empty-col {{ color: #475569; font-size: 12px; text-align: center; margin-top: 40px; font-style: italic; }}

        .history-section {{ background: var(--bg-secondary); border-radius: 12px; border: 1px solid var(--border-color); padding: 20px; }}
        .history-title {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #fff; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border-color); }}
        th {{ color: var(--text-secondary); font-weight: 600; background: #131d2e; }}
        .decision-badge {{ padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; }}
        .decision-badge.approved {{ background: #10b98122; color: #34d399; }}
        .decision-badge.revise {{ background: #f59e0b22; color: #fbbf24; }}
        .decision-badge.review {{ background: #ef444422; color: #f87171; }}
    </style>
    <script>
        // Auto-refresh every 10 seconds
        setTimeout(() => {{ window.location.reload(); }}, 10000);
    </script>
</head>
<body>
    <header>
        <div class="header-title">
            <span class="live-pulse"></span>
            DAIO Dual-Agent Live Taskboard
        </div>
        <div style="font-size: 12px; color: var(--text-secondary);">
            Auto-refreshing live state | CDP Active
        </div>
    </header>

    <div class="board">
        {cols_html}
    </div>

    <div class="history-section">
        <div class="history-title">📜 Autonomous Dual-Agent Decision Audit Stream</div>
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
                {history_rows}
            </tbody>
        </table>
    </div>
</body>
</html>
        """
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(html)
