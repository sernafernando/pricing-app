"""`componentes_de` returns exact Decimal quantities whatever numeric type the
driver hands back (combos-propios C2): a float 0.1 must become Decimal("0.1"),
never its binary expansion."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.models.combo_componente import ComboComponente
from app.services.combos.componentes import componentes_de


def test_a_float_quantity_from_the_driver_is_an_exact_decimal() -> None:
    db = MagicMock()
    db.execute.return_value = [(100, 500, 0.1)]

    assert componentes_de(db, [100]) == {100: {500: Decimal("0.1")}}


def test_a_fractional_quantity_round_trips_exactly(db) -> None:
    db.add(ComboComponente(combo_item_id=100, componente_item_id=500, cantidad=Decimal("0.1")))
    db.flush()

    assert componentes_de(db, [100]) == {100: {500: Decimal("0.1")}}
