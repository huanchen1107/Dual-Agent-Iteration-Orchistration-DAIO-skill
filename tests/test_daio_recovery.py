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
