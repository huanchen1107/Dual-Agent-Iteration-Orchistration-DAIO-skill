#!/usr/bin/env python3
"""Fail-closed G0-G4 checklist validator for external-dependent changes."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REQUIRED_MARKERS = (
    "G0 — Route survey",
    "G1 — External feasibility",
    "G2 — Architecture selection",
    "G3 — Thin real end-to-end",
    "G4 — Deep implementation",
    "PRIMARY_ROUTE",
    "ESCAPE_HATCH",
    "AUTHORITATIVE_SOURCE",
    "LAST_VERIFIED_AT",
)


def validate_document(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [marker for marker in REQUIRED_MARKERS if marker not in text]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="change plan/checklist to validate")
    args = parser.parse_args(argv)
    if not args.document.is_file():
        print(f"ROUTE_FIRST_PREFLIGHT: BLOCKED (missing document: {args.document})")
        return 2
    missing = validate_document(args.document)
    if missing:
        print("ROUTE_FIRST_PREFLIGHT: BLOCKED")
        print("MISSING: " + ", ".join(missing))
        return 1
    print("ROUTE_FIRST_PREFLIGHT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
