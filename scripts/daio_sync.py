"""DAIO three-party sync registry: Git, Engineer, Architect."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .daio_recovery import discover_project_root, git_head

REGISTRY=".daio/sync_registry.json"
PARTICIPANTS=("github","engineer","architect")

def _now(): return datetime.now(timezone.utc).isoformat()

def load_registry(root="."):
    root=discover_project_root(root); p=Path(root)/REGISTRY
    if not p.exists():
        return {"schema_version":"1.0","authority":"NON_AUTHORITATIVE_SYNC_INDEX","participants":{}}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {"schema_version":"1.0","authority":"NON_AUTHORITATIVE_SYNC_INDEX","participants":{}}

def heartbeat(root, participant, checkpoint_head=None, session_ref=None, **metadata):
    if participant not in PARTICIPANTS: raise ValueError("unknown participant")
    root=discover_project_root(root); reg=load_registry(root); head=git_head(root)
    item=reg.setdefault("participants",{}).setdefault(participant,{})
    item.update(metadata); item["heartbeat_at"]=_now()
    item["checkpoint_head"]=checkpoint_head or head
    if session_ref is not None: item["session_ref"]=session_ref
    p=Path(root)/REGISTRY; p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(reg,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return item

def sync_status(root="."):
    root=discover_project_root(root); head=git_head(root); reg=load_registry(root)
    result={"head":head,"overall":"SYNCED","participants":{}}
    for name in PARTICIPANTS:
        item=reg.get("participants",{}).get(name)
        if not item:
            state="MISSING"
        elif item.get("checkpoint_head") != head:
            state="LAGGING"
        else:
            state="SYNCED"
        result["participants"][name]={"state":state,**(item or {})}
    states=[x["state"] for x in result["participants"].values()]
    if "LAGGING" in states: result["overall"]="STALE"
    elif "MISSING" in states: result["overall"]="DEGRADED"
    return result

def mark_git(root="."):
    return heartbeat(root,"github")
