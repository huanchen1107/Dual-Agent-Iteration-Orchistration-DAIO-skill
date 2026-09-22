import json, subprocess
from pathlib import Path
from scripts.daio_adapter import collect_sections
from scripts.daio_taskboard import TaskboardManager

def git(root,*args):
    subprocess.run(["git",*args],cwd=root,check=True,capture_output=True,text=True)

def init_repo(root):
    git(root,"init"); git(root,"config","user.email","daio@test.local"); git(root,"config","user.name","DAIO Test")
    (root/"a").write_text("1"); git(root,"add","."); git(root,"commit","-m","one")

def test_core_has_no_project_adapter_by_default(tmp_path):
    init_repo(tmp_path)
    assert collect_sections(tmp_path)=={}
    tb=TaskboardManager(str(tmp_path)); tb.save()
    data=json.loads((tmp_path/"taskboard.json").read_text())
    assert data["project_sections"]=={}

def test_project_adapter_is_explicit_opt_in(tmp_path):
    init_repo(tmp_path)
    (tmp_path/"custom_adapter.py").write_text(
        "def collect_sections(project_root):\n    return {'demo': {'title':'Demo','items':['ok']}}\n"
    )
    d=tmp_path/".daio"; d.mkdir()
    (d/"project_adapter.json").write_text(json.dumps({"enabled":True,"path":"custom_adapter.py"}))
    sections=collect_sections(tmp_path)
    assert sections["demo"]["items"]==["ok"]
