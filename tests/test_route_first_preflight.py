from pathlib import Path

from scripts.route_first_preflight import validate_document


GATES = """# change
G0 — Route survey
G1 — External feasibility
G2 — Architecture selection
G3 — Thin real end-to-end
G4 — Deep implementation
PRIMARY_ROUTE: Cockpit
ESCAPE_HATCH: local
LAST_VERIFIED_AT: 2026-09-29
AUTHORITATIVE_SOURCE: https://example.test
"""


def test_route_first_document_passes(tmp_path: Path):
    path = tmp_path / "change.md"
    path.write_text(GATES, encoding="utf-8")
    assert validate_document(path) == []


def test_route_first_document_fails_closed_when_external_evidence_missing(tmp_path: Path):
    path = tmp_path / "change.md"
    path.write_text(GATES.replace("G3 — Thin real end-to-end", ""), encoding="utf-8")
    assert "G3 — Thin real end-to-end" in validate_document(path)
