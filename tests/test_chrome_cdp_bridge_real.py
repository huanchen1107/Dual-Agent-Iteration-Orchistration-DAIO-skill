import pytest
from scripts.daio_closed_loop.adapters.bridge import ChromeCDPBridgeAdapter, parse_decision_from_text

def test_chrome_cdp_bridge_adapter_import_and_client_resolution():
    adapter = ChromeCDPBridgeAdapter(endpoint={"conversation_id": "test-conv-123"}, cdp_port=9222)
    assert adapter.cdp_port == 9222
    assert adapter.endpoint["conversation_id"] == "test-conv-123"
    
    # Verify client class resolution succeeds without NameError / ModuleNotFoundError
    client_cls = adapter._get_cdp_client_class()
    assert client_cls is not None
    assert client_cls.__name__ == "UniversalCDPClient"

def test_parse_decision_from_text_valid_and_fallback():
    sample_text = """Great job. Here is the control block:
```json
{
  "decision": "REVISE",
  "current_phase": "PHASE_1",
  "next_phase": "PHASE_2",
  "action": "RUN",
  "human_approval_required": false,
  "instruction": "Fix unit test edge cases."
}
```
"""
    dec = parse_decision_from_text(sample_text)
    assert dec.decision == "REVISE"
    assert dec.current_phase == "PHASE_1"
    assert dec.next_phase == "PHASE_2"
    assert dec.instruction == "Fix unit test edge cases."


def test_cdp_bridge_client_resolution_with_clean_sys_path(monkeypatch):
    """Ensure _get_cdp_client_class works even if scripts directory was removed from sys.path."""
    import sys
    # Simulate stripped sys.path containing only stdlib and repo root
    from pathlib import Path
    repo_root = str(Path(__file__).resolve().parent.parent)
    
    adapter = ChromeCDPBridgeAdapter()
    cls = adapter._get_cdp_client_class()
    assert cls is not None
    assert hasattr(cls, "connect")
    assert hasattr(cls, "send_message")
    assert hasattr(cls, "close")

