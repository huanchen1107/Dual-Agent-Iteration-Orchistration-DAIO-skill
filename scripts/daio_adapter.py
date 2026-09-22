"""Optional project adapter loader for DAIO core."""
from __future__ import annotations
import importlib.util, json
from pathlib import Path

CONFIG=".daio/project_adapter.json"

def adapter_config(root="."):
    p=Path(root)/CONFIG
    if not p.exists(): return {"enabled":False}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {"enabled":False,"error":"invalid adapter config"}

def load_adapter(root="."):
    root=Path(root); cfg=adapter_config(root)
    if not cfg.get("enabled"): return None
    path=cfg.get("path")
    if not path: return None
    module_path=(root/path).resolve()
    if not module_path.exists(): return None
    spec=importlib.util.spec_from_file_location("daio_project_adapter",module_path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def collect_sections(root="."):
    adapter=load_adapter(root)
    if not adapter: return {}
    fn=getattr(adapter,"collect_sections",None)
    return fn(Path(root)) if fn else {}


def render_sections(root=".", sections=None):
    """Return adapter-owned markdown/html fragments. Core treats them as opaque UI."""
    adapter=load_adapter(root)
    if not adapter: return {"markdown":"","html":""}
    fn=getattr(adapter,"render_sections",None)
    if not fn: return {"markdown":"","html":""}
    rendered=fn(Path(root), sections if sections is not None else collect_sections(root))
    return {"markdown":rendered.get("markdown",""),"html":rendered.get("html","")}
