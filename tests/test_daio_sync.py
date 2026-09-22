import subprocess
from scripts.daio_sync import heartbeat, sync_status, mark_git

def git(root,*args):
    subprocess.run(["git",*args],cwd=root,check=True,capture_output=True,text=True)

def repo(tmp_path):
    git(tmp_path,"init"); git(tmp_path,"config","user.email","daio@test.local"); git(tmp_path,"config","user.name","DAIO Test")
    (tmp_path/"a").write_text("1"); git(tmp_path,"add","."); git(tmp_path,"commit","-m","one")
    return tmp_path

def test_registry_missing_participants_is_degraded(tmp_path):
    r=repo(tmp_path); mark_git(r)
    s=sync_status(r)
    assert s["overall"]=="DEGRADED"
    assert s["participants"]["engineer"]["state"]=="MISSING"

def test_all_participants_synced(tmp_path):
    r=repo(tmp_path)
    for p in ("github","engineer","architect"): heartbeat(r,p)
    assert sync_status(r)["overall"]=="SYNCED"

def test_git_advance_marks_agents_lagging(tmp_path):
    r=repo(tmp_path)
    for p in ("github","engineer","architect"): heartbeat(r,p)
    (r/"b").write_text("2"); git(r,"add","."); git(r,"commit","-m","advance")
    s=sync_status(r)
    assert s["overall"]=="STALE"
    assert s["participants"]["engineer"]["state"]=="LAGGING"
    assert s["participants"]["architect"]["state"]=="LAGGING"


def test_healing_plan_uses_delta_for_lagging_agent(tmp_path):
    from scripts.daio_sync import healing_plan
    r=repo(tmp_path)
    for p in ("github","engineer","architect"): heartbeat(r,p)
    (r/"b").write_text("2"); git(r,"add","."); git(r,"commit","-m","delta-change")
    mark_git(r)
    plan=healing_plan(r)
    eng=next(a for a in plan["actions"] if a["participant"]=="engineer")
    assert eng["action"]=="REHYDRATE_DELTA"
    assert any("delta-change" in x for x in eng["commits"])

def test_missing_agent_requires_full_rehydration(tmp_path):
    from scripts.daio_sync import healing_plan
    r=repo(tmp_path); mark_git(r)
    plan=healing_plan(r)
    architect=next(a for a in plan["actions"] if a["participant"]=="architect")
    assert architect["action"]=="REHYDRATE_FULL"

def test_delta_packet_does_not_escalate_context_lag(tmp_path):
    from scripts.daio_sync import build_delta_packet
    r=repo(tmp_path)
    heartbeat(r,"github"); heartbeat(r,"engineer"); heartbeat(r,"architect")
    (r/"b").write_text("2"); git(r,"add","."); git(r,"commit","-m","new-head")
    mark_git(r)
    packet=build_delta_packet(r,"architect")
    assert "new-head" in packet
    assert "Do not treat context lag alone as HUMAN_REVIEW" in packet
