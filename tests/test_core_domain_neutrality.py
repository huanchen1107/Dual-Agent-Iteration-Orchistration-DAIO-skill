from pathlib import Path

FORBIDDEN=("2330.TW","change045","RTS-A","watchlist_data_fetch_log","Market Data Inventory","Blind Replay","market_hub_html","replay_matrix_html")

def test_taskboard_core_is_domain_neutral():
    source=Path("scripts/daio_taskboard.py").read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in source, f"domain token leaked into DAIO core: {token}"

def test_awin_domain_logic_lives_in_adapter():
    source=Path("adapters/awin_fintech.py").read_text(encoding="utf-8")
    assert "2330.TW" in source
    assert "change045" in source


def test_domain_renderer_contract_lives_outside_core():
    core=Path("scripts/daio_taskboard.py").read_text(encoding="utf-8")
    adapter=Path("adapters/awin_fintech.py").read_text(encoding="utf-8")
    assert "render_sections" in core
    assert "def render_sections" in adapter
    assert "Project Adapter - Market Data" in adapter
