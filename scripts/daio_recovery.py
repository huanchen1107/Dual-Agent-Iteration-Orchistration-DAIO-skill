"""DAIO Robust Recovery utilities.

Repository state is authoritative; chat/session state is a disposable cache.
"""
from __future__ import annotations
import json, subprocess
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR=".daio"
STATE_FILE="recovery_state.json"

def _git(root,*args):
    p=subprocess.run(["git",*args],cwd=root,capture_output=True,text=True)
    return p.returncode,p.stdout.strip()

def discover_project_root(start="."):
    p=Path(start).resolve()
    for c in [p,*p.parents]:
        if (c/".git").exists(): return c
    return p

def git_head(root):
    code,out=_git(root,"rev-parse","HEAD")
    return out if code==0 else None

def load_state(root):
    p=Path(root)/STATE_DIR/STATE_FILE
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}

def diagnose(root="."):
    root=discover_project_root(root); head=git_head(root); state=load_state(root)
    checkpoint=state.get("checkpoint_head")
    if not checkpoint: health="CHECKPOINT_MISSING"
    elif checkpoint!=head: health="STALE"
    else: health="SYNCED"
    recent=[]
    if checkpoint and head and checkpoint!=head:
        code,out=_git(root,"log","--oneline",f"{checkpoint}..{head}","-20")
        if code==0: recent=out.splitlines()
    return {"project_root":str(root),"head":head,"checkpoint_head":checkpoint,
            "health":health,"recent_commits":recent,"state":state}

def checkpoint(root=".", **metadata):
    root=discover_project_root(root); d=Path(root)/STATE_DIR; d.mkdir(exist_ok=True)
    state=load_state(root)
    state.update(metadata)
    state.update({"schema_version":"1.0","checkpoint_head":git_head(root),
                  "updated_at":datetime.now(timezone.utc).isoformat(),
                  "authority":"NON_AUTHORITATIVE_RECOVERY_CACHE"})
    (d/STATE_FILE).write_text(json.dumps(state,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return state


def build_rehydration_packet(root="."):
    """Build a bounded packet for a replacement Architect/Engineer session."""
    d=diagnose(root); root=Path(d["project_root"])
    _,branch=_git(root,"branch","--show-current")
    _,status=_git(root,"status","--short")
    _,last=_git(root,"log","-10","--pretty=format:%h %s")
    candidates=[]
    for name in ("AGENTS.md","TASKBOARD.md","README.md","design.md"):
        if (root/name).exists(): candidates.append(name)
    for dirname in ("openspec","_myplan_"):
        if (root/dirname).exists(): candidates.append(dirname+"/")
    lines=[
      "# DAIO Context Rehydration Packet",
      "- Project root: "+str(root), "- Branch: "+(branch or "UNKNOWN"),
      "- HEAD: "+(d["head"] or "UNKNOWN"), "- Recovery health: "+d["health"],
      "- Previous checkpoint: "+(d["checkpoint_head"] or "NONE"),
      "- Authority: Git/project artifacts; this packet is navigation context only.",
      "", "## Canonical artifact candidates", *["- "+x for x in candidates],
      "", "## Recent commits", last or "(none)",
      "", "## Commits since checkpoint",
      "\n".join(d["recent_commits"]) or "(checkpoint current or missing)",
      "", "## Working tree", status or "(clean)", "",
      "## Recovery directive",
      "Reconcile the artifacts above before acting. STALE or CHECKPOINT_MISSING is recoverable and must not by itself trigger HUMAN_REVIEW."
    ]
    return "\n".join(lines)+"\n"

def write_rehydration_packet(root="."):
    root=discover_project_root(root); d=Path(root)/STATE_DIR; d.mkdir(exist_ok=True)
    p=d/"rehydration_packet.md"; p.write_text(build_rehydration_packet(root),encoding="utf-8")
    return p
