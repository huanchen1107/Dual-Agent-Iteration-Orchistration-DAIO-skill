import json, subprocess
from scripts.daio_sync import heartbeat
from scripts.daio_taskboard import TaskboardManager

def git(root,*args):
    subprocess.run(["git",*args],cwd=root,check=True,capture_output=True,text=True)

def test_taskboard_exports_sync_health(tmp_path):
    git(tmp_path,"init"); git(tmp_path,"config","user.email","daio@test.local"); git(tmp_path,"config","user.name","DAIO Test")
    (tmp_path/"a").write_text("1"); git(tmp_path,"add","."); git(tmp_path,"commit","-m","one")
    for p in ("github","engineer","architect"): heartbeat(tmp_path,p)
    tb=TaskboardManager(str(tmp_path)); tb.save()
    data=json.loads((tmp_path/"taskboard.json").read_text())
    assert data["sync_health"]["overall"]=="SYNCED"
    md=(tmp_path/"TASKBOARD.md").read_text()
    assert "DAIO Sync Health" in md
    assert "architect" in md
    html=(tmp_path/"taskboard.html").read_text()
    assert "DAIO Three-Party Sync Health" in html
