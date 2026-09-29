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


def test_discover_tab_by_endpoint_exact_match():
    from scripts.daio_closed_loop.adapters.bridge import discover_tab_by_endpoint
    mock_tabs = [
        {"type": "page", "id": "tab-1", "title": "Random Page", "url": "https://example.com", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-1"},
        {"type": "page", "id": "tab-2", "title": "ChatGPT Target", "url": "https://chatgpt.com/g/p-123/c/conv-abc-456", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-2"},
    ]
    ws, tab_id, title = discover_tab_by_endpoint(
        endpoint={"conversation_id": "conv-abc-456", "routing_policy": "EXACT_CONVERSATION"},
        raw_tabs=mock_tabs,
    )
    assert tab_id == "tab-2"
    assert ws == "ws://127.0.0.1:9222/devtools/page/tab-2"


def test_discover_tab_by_endpoint_fail_closed_on_missing_conversation():
    from scripts.daio_closed_loop.adapters.bridge import discover_tab_by_endpoint
    mock_tabs = [
        {"type": "page", "id": "tab-1", "title": "Another Project", "url": "https://chatgpt.com/g/p-999/c/conv-xyz-789", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-1"},
    ]
    with pytest.raises(RuntimeError) as exc_info:
        discover_tab_by_endpoint(
            endpoint={"conversation_id": "conv-needed-000", "routing_policy": "EXACT_CONVERSATION"},
            raw_tabs=mock_tabs,
        )
    assert "DAIO-004 Exact Conversation Routing Failed" in str(exc_info.value)
    assert "Fail-closed policy prevented dispatch" in str(exc_info.value)


def test_discover_tab_by_endpoint_fails_closed_for_duplicate_exact_targets():
    """A CDP target is not a conversation identity; duplicate exact targets are ambiguous."""
    from scripts.daio_closed_loop.adapters.bridge import discover_tab_by_endpoint
    endpoint_url = "https://chatgpt.com/g/project-1/c/conversation-1"
    mock_tabs = [
        {"type": "page", "id": "tab-a", "title": "ChatGPT", "url": endpoint_url,
         "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-a"},
        {"type": "page", "id": "tab-b", "title": "ChatGPT", "url": endpoint_url,
         "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-b"},
    ]
    with pytest.raises(RuntimeError, match="Routing Ambiguous"):
        discover_tab_by_endpoint(
            endpoint={"project_id": "project-1", "conversation_id": "conversation-1",
                      "canonical_url": endpoint_url, "routing_policy": "EXACT_CONVERSATION"},
            raw_tabs=mock_tabs,
        )


def test_exact_endpoint_ignores_other_project_or_conversation_tabs():
    from scripts.daio_closed_loop.adapters.bridge import discover_tab_by_endpoint
    mock_tabs = [
        {"type": "page", "id": "wrong-project", "title": "Other", "url": "https://chatgpt.com/g/project-2/c/conversation-1",
         "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/wrong-project"},
        {"type": "page", "id": "wrong-conversation", "title": "Other", "url": "https://chatgpt.com/g/project-1/c/conversation-2",
         "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/wrong-conversation"},
        {"type": "page", "id": "right", "title": "Right", "url": "https://chatgpt.com/g/project-1/c/conversation-1",
         "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/right"},
    ]
    _, tab_id, _ = discover_tab_by_endpoint(
        endpoint={"project_id": "project-1", "conversation_id": "conversation-1", "routing_policy": "EXACT_CONVERSATION"},
        raw_tabs=mock_tabs,
    )
    assert tab_id == "right"


