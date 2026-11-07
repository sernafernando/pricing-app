"""Productos `markup_contextos` query → resolver contextos."""

from __future__ import annotations

import pytest

from app.services.productos_sell_in_out import parse_contextos_query


@pytest.mark.parametrize("raw", [None, "", "  ", "todas", "TODAS"])
def test_todas_is_global(raw) -> None:
    assert parse_contextos_query(raw) is None


def test_parses_stores_and_channels() -> None:
    assert parse_contextos_query("ml:57997,fuera,tn,ml:2645") == [
        ("ml", 57997),
        ("fuera", None),
        ("tn", None),
        ("ml", 2645),
    ]


def test_rejects_unknown_token() -> None:
    with pytest.raises(ValueError, match="inválido"):
        parse_contextos_query("ml:x")
