"""A board without an explicit visibility must not be constructible: forgetting
`scope_pairs` has to fail closed (TypeError), never silently see everything."""

from __future__ import annotations

from datetime import date

import pytest

from app.routers.ml_metricas import build_board_response
from app.services.ml_daily_metrics import board

F = board.BoardFilter(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))


def test_board_requires_scope_pairs():
    with pytest.raises(TypeError, match="scope_pairs"):
        board.Board(None, F)


def test_build_board_response_requires_scope_pairs():
    with pytest.raises(TypeError, match="scope_pairs"):
        build_board_response(None, F, limit=10, offset=0, can_see_margin=True)
