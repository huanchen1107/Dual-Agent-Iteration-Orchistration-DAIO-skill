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


def _git_delta(root, old_head, new_head):
    import subprocess
    if not old_head or not new_head or old_head == new_head: return []
    p=subprocess.run(["git","log","--oneline",old_head+".."+new_head,"-20"],
                     cwd=root,capture_output=True,text=True)
    return p.stdout.strip().splitlines() if p.returncode==0 else []

def healing_plan(root="."):
    """Return deterministic self-healing actions without mutating semantic project state."""
    root=discover_project_root(root); s=sync_status(root); head=s["head"]; actions=[]
    for name in ("engineer","architect"):
        item=s["participants"][name]; state=item["state"]
        if state=="LAGGING":
            actions.append({"participant":name,"action":"REHYDRATE_DELTA",
                            "from_head":item.get("checkpoint_head"),"to_head":head,
                            "commits":_git_delta(root,item.get("checkpoint_head"),head)})
        elif state=="MISSING":
            actions.append({"participant":name,"action":"REHYDRATE_FULL",
                            "from_head":None,"to_head":head,"commits":[]})
    return {"overall":s["overall"],"head":head,"actions":actions}

def build_delta_packet(root, participant):
    root=discover_project_root(root); plan=healing_plan(root)
    action=next((x for x in plan["actions"] if x["participant"]==participant),None)
    if not action: return ""
    lines=["# DAIO Self-Healing Sync Packet",
           "- Participant: "+participant,
           "- Action: "+action["action"],
           "- Canonical HEAD: "+str(action["to_head"]),
           "- Previous participant HEAD: "+str(action["from_head"] or "NONE"),
           "- Authority: Git repository and project governance artifacts.",
           "", "## Delta commits"]
    lines += action["commits"] or ["(full rehydration required; no reliable prior checkpoint)"]
    lines += ["","## Directive",
              "Rehydrate context to canonical HEAD before making new semantic decisions. Do not treat context lag alone as HUMAN_REVIEW."]
    return "\n".join(lines)+"\n"
