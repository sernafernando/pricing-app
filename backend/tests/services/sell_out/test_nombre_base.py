"""`nombre_base`: the name a campaign shares with its renewals, once its period or sequence markers are stripped.

Pure function, no database: it only proposes groups (`GET /api/sell-out/programas/sugerencias`); the operator
assigns by hand."""

from __future__ import annotations

import pytest

from app.services.sell_out.programas import nombre_base


@pytest.mark.parametrize(
    ("nombre", "base"),
    [
        ("EPSON PROG 24", "EPSON PROG"),
        ("EPSON PROG 25", "EPSON PROG"),
        ("EPSON PROG 2024", "EPSON PROG"),
        ("Rebate Q4 2024", "Rebate"),
        ("Rebate q1", "Rebate"),
        ("Rebate Q4-2024", "Rebate"),
        ("EPSON PROG - 24", "EPSON PROG"),
        ("EPSON PROG #3", "EPSON PROG"),
        ("EPSON PROG (2)", "EPSON PROG"),
        ("EPSON PROG N°3", "EPSON PROG"),
        ("EPSON PROG Nº 3", "EPSON PROG"),
        ("  EPSON   PROG   24  ", "EPSON PROG"),  # spaces collapsed
        ("TP-Link 2% noviembre", "TP-Link 2% noviembre"),  # nothing to strip
        ("RB 8180", "RB 8180"),  # a model number, not a year or a sequence
        ("EPSON PROG24", "EPSON PROG24"),  # a glued number is part of the name
        ("Q4 2024", "Q4 2024"),  # everything would go: the name stays
        ("2024", "2024"),
    ],
)
def test_nombre_base_strips_trailing_period_and_sequence_markers(nombre: str, base: str) -> None:
    assert nombre_base(nombre) == base


def test_nombre_base_never_returns_an_empty_base() -> None:
    assert nombre_base("#3") == "#3"
    assert nombre_base(" - 24 ") == "- 24"
