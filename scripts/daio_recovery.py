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
