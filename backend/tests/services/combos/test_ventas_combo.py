"""A combo's sale seen as sales of its components (owner, 2026-11-05: "El combo consume los lotes de sell in de cada
componente y cuenta para sus campañas de sell out. En una campaña por % de precio, a la notebook le toca la parte del
precio del combo proporcional a su costo dentro del combo.")."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.combo_componente import ComboComponente
from app.models.producto import ProductoERP, TipoMoneda
from app.models.tipo_cambio import TipoCambio
from app.services.combos.componentes import CombosNoSincronizados
from app.services.combos.ventas import Parte, partes_de_combos, unidades_de

NOTEBOOK, WH, MOUSE, COMBO, COMBO_MOUSE, SUELTO = 10, 11, 12, 20, 21, 30


def _producto(db, item_id: int, costo: float, moneda: TipoMoneda = TipoMoneda.ARS) -> None:
    db.add(ProductoERP(item_id=item_id, codigo=f"P{item_id}", descripcion="x", costo=costo, moneda_costo=moneda))


@pytest.fixture()
def bom(db):
    _producto(db, NOTEBOOK, 900.0)
    _producto(db, WH, 0.1, TipoMoneda.USD)  # 100 ARS at the rate below
    _producto(db, MOUSE, 0.0)  # no cost of its own
    _producto(db, SUELTO, 50.0)
    db.add(TipoCambio(moneda="USD", fecha=date(2026, 11, 5), compra=990, venta=1000))
    db.add_all(
        [
            ComboComponente(combo_item_id=COMBO, componente_item_id=NOTEBOOK, cantidad=Decimal("1")),
            ComboComponente(combo_item_id=COMBO, componente_item_id=WH, cantidad=Decimal("1")),
            ComboComponente(combo_item_id=COMBO_MOUSE, componente_item_id=NOTEBOOK, cantidad=Decimal("1")),
            ComboComponente(combo_item_id=COMBO_MOUSE, componente_item_id=MOUSE, cantidad=Decimal("3")),
        ]
    )
    db.commit()


def test_each_component_weighs_its_cost_times_quantity_within_the_combo(db, bom) -> None:
    partes = partes_de_combos(db, {NOTEBOOK})

    assert partes[COMBO] == [Parte(NOTEBOOK, Decimal("1"), Decimal("0.9")), Parte(WH, Decimal("1"), Decimal("0.1"))]


def test_a_component_without_cost_falls_back_to_an_equal_split_per_unit(db, bom) -> None:
    partes = partes_de_combos(db, {MOUSE})

    assert partes[COMBO_MOUSE] == [
        Parte(NOTEBOOK, Decimal("1"), Decimal("0.25")),
        Parte(MOUSE, Decimal("3"), Decimal("0.75")),
    ]


def test_every_combo_holding_a_product_comes_and_a_combo_asked_for_itself_too(db, bom) -> None:
    assert set(partes_de_combos(db, {NOTEBOOK})) == {COMBO, COMBO_MOUSE}
    assert set(partes_de_combos(db, {COMBO})) == {COMBO}
    assert partes_de_combos(db, {SUELTO}) == {}


def test_the_bill_of_materials_must_be_synced(db) -> None:
    with pytest.raises(CombosNoSincronizados):
        partes_de_combos(db, {NOTEBOOK})


def test_units_are_the_sold_quantity_times_the_component_quantity() -> None:
    assert unidades_de(2, Parte(MOUSE, Decimal("3"), Decimal("0.75"))) == 6
    assert unidades_de(-1, Parte(MOUSE, Decimal("3"), Decimal("0.75"))) == -3
    with pytest.raises(ValueError):
        unidades_de(1, Parte(MOUSE, Decimal("0.5"), Decimal("1")))
