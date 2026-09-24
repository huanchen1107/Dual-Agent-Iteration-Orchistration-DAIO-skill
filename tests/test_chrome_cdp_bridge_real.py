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


def test_parse_decision_with_renderer_metadata_on_fence():
    sample = """Architect notes and assessment:
```json:response file=decision.json
{
  "decision": "REVISE",
  "current_phase": "PHASE_S5_3_SCAFFOLD",
  "next_phase": "PHASE_S5_3_ENGINEERING",
  "action": "RUN",
  "human_approval_required": false,
  "instruction": "Implement rank_values function in src/pipeline.py"
}
```
Prose trailing notes.
"""
    dec = parse_decision_from_text(sample)
    assert dec.decision == "REVISE"
    assert dec.current_phase == "PHASE_S5_3_SCAFFOLD"
    assert "rank_values" in dec.instruction


def test_parse_decision_bare_json_embedded_in_prose():
    sample = """Here is the decision directly:
{"decision": "APPROVE", "current_phase": "PHASE_2", "next_phase": "PHASE_3", "action": "PROCEED", "human_approval_required": false, "instruction": "Proceed to next stage"}
Have a good day!"""
    dec = parse_decision_from_text(sample)
    assert dec.decision == "APPROVE"
    assert dec.action == "PROCEED"


def test_parse_decision_multiple_blocks_final_block_wins():
    sample = """Example template provided earlier:
```json
{
  "decision": "REJECT",
  "current_phase": "TEMPLATE_PHASE",
  "instruction": "Ignore this old template"
}
```
Real final decision at the end of assessment:
```json
{
  "decision": "APPROVE",
  "current_phase": "PHASE_FINAL",
  "next_phase": "PHASE_COMPLETE",
  "action": "PROCEED",
  "human_approval_required": false,
  "instruction": "Final stage approved."
}
```
"""
    dec = parse_decision_from_text(sample)
    assert dec.decision == "APPROVE"
    assert dec.current_phase == "PHASE_FINAL"
    assert dec.instruction == "Final stage approved."


def test_parse_decision_unrelated_json_before_decision():
    sample = """Metadata:
```json
{"session_id": "sess-12345", "token_count": 42}
```
Real decision:
```json
{
  "decision": "HUMAN_REVIEW",
  "current_phase": "SECURITY_AUDIT",
  "action": "HALT",
  "human_approval_required": true,
  "instruction": "Manual review of crypto changes required."
}
```
"""
    dec = parse_decision_from_text(sample)
    assert dec.decision == "HUMAN_REVIEW"
    assert dec.human_approval_required is True


def test_parse_decision_invalid_enum_fails_closed():
    sample = """```json
{
  "decision": "MAYBE",
  "current_phase": "PHASE_1",
  "instruction": "Not sure"
}
```"""
    with pytest.raises(ValueError) as exc_info:
        parse_decision_from_text(sample)
    assert "Invalid or missing decision: 'MAYBE'" in str(exc_info.value)
    assert "Diagnostics:" in str(exc_info.value)


def test_parse_decision_missing_required_fields_fails_closed():
    sample = """```json
{
  "decision": "APPROVE",
  "instruction": "Missing current_phase"
}
```"""
    with pytest.raises(ValueError) as exc_info:
        parse_decision_from_text(sample)
    assert "Missing or empty 'current_phase'" in str(exc_info.value)


def test_parse_decision_empty_or_malformed_fails_closed():
    with pytest.raises(ValueError) as exc_info1:
        parse_decision_from_text("")
    assert "empty response text" in str(exc_info1.value)

    with pytest.raises(ValueError) as exc_info2:
        parse_decision_from_text("This response contains no JSON structures whatsoever.")
    assert "No JSON candidate structures found" in str(exc_info2.value)


def test_cdp_bridge_client_resolution_with_clean_sys_path(monkeypatch):
    """Ensure _get_cdp_client_class works even if scripts directory was removed from sys.path."""
    import sys
    from pathlib import Path
    repo_root = str(Path(__file__).resolve().parent.parent)

    adapter = ChromeCDPBridgeAdapter()
    cls = adapter._get_cdp_client_class()
    assert cls is not None
    assert hasattr(cls, "connect")
    assert hasattr(cls, "send_message")
    assert hasattr(cls, "close")


