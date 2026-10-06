"""Group-scope plumbing that needs no database: which filters count as row
filters, and how the store key is encoded."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services.ml_daily_metrics import board, groups

VALUES = {"alerts": ("sin_ventas_30d",), "stock": ("con_stock",), "ageing": ("over_60",)}


def _has(**filters) -> bool:
    f = board.BoardFilter(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), **filters)
    return board.Board._has_row_filters(SimpleNamespace(f=f))


def test_no_filter_is_no_row_filter() -> None:
    assert _has() is False


@pytest.mark.parametrize("axis", board.ROW_AXES)
def test_every_row_axis_counts_as_a_row_filter(axis) -> None:
    assert _has(**{axis: VALUES[axis]}) is True


@pytest.mark.parametrize("axis", [a for a in board.ROW_AXES if hasattr(board.BoardFilter, f"{a}_exclude")])
def test_every_row_axis_exclusion_counts_too(axis) -> None:
    assert _has(**{f"{axis}_exclude": VALUES[axis]}) is True


def test_solo_con_ventas_counts_as_a_row_filter() -> None:
    assert _has(solo_con_ventas=True) is True


def test_the_store_key_prefixes_are_shared_constants() -> None:
    assert groups.STORE_KEY_PREFIX == "s:" and groups.CLAVE_KEY_PREFIX == "c:"
