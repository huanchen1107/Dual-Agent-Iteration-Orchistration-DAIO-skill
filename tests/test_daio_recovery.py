import subprocess
from pathlib import Path
from scripts.daio_recovery import diagnose, checkpoint

def git(root,*args):
    subprocess.run(["git",*args],cwd=root,check=True,capture_output=True,text=True)

def repo(tmp_path):
    git(tmp_path,"init"); git(tmp_path,"config","user.email","daio@test.local"); git(tmp_path,"config","user.name","DAIO Test")
    (tmp_path/"a").write_text("1"); git(tmp_path,"add","."); git(tmp_path,"commit","-m","one")
    return tmp_path

def test_missing_checkpoint(tmp_path):
    r=repo(tmp_path); assert diagnose(r)["health"]=="CHECKPOINT_MISSING"

def test_synced_checkpoint(tmp_path):
    r=repo(tmp_path); checkpoint(r,agent="test"); assert diagnose(r)["health"]=="SYNCED"

def test_stale_checkpoint_auto_detect(tmp_path):
    r=repo(tmp_path); checkpoint(r,agent="test")
    (r/"b").write_text("2"); git(r,"add","."); git(r,"commit","-m","two")
    d=diagnose(r); assert d["health"]=="STALE"; assert d["recent_commits"]


def test_rehydration_packet_contains_recovery_evidence(tmp_path):
    from scripts.daio_recovery import build_rehydration_packet
    r=repo(tmp_path); checkpoint(r,agent="test")
    (r/"b").write_text("2"); git(r,"add","."); git(r,"commit","-m","two")
    packet=build_rehydration_packet(r)
    assert "Recovery health: STALE" in packet
    assert "Recent commits" in packet
    assert "two" in packet
    assert "must not by itself trigger HUMAN_REVIEW" in packet

def test_checkpoint_missing_packet_is_recoverable(tmp_path):
    from scripts.daio_recovery import build_rehydration_packet
    r=repo(tmp_path)
    packet=build_rehydration_packet(r)
    assert "Recovery health: CHECKPOINT_MISSING" in packet
    assert "Previous checkpoint: NONE" in packet
