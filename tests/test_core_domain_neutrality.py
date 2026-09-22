from pathlib import Path

FORBIDDEN=("2330.TW","change045","RTS-A","watchlist_data_fetch_log")

def test_taskboard_core_is_domain_neutral():
    source=Path("scripts/daio_taskboard.py").read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in source, f"domain token leaked into DAIO core: {token}"

def test_awin_domain_logic_lives_in_adapter():
    source=Path("adapters/awin_fintech.py").read_text(encoding="utf-8")
    assert "2330.TW" in source
    assert "change045" in source
