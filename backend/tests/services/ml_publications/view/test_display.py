"""The display rounding shared by the view's serializers."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.ml_publications.view.display import round_display


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (1.005, 1.0), (12.346, 12.35), (Decimal("99.994"), 99.99), (7, 7.0), (-19.834710743801654, -19.83)],
)
def test_two_decimals_for_floats_decimals_and_integers(value, expected) -> None:
    assert round_display(value) == expected
