"""The sell in in the product's cost currency (S10, display only): `en_moneda_costo` and the batch's `markups`.

Owner (S10): "si son 17,04 USD, mostrame 17,04 USD ... y con sell in también me lo estás poniendo en pesos". The cost
with sell in and its discount are also given in the cost's currency, converted back at the rate the cost was turned
into ARS with. A cost currency that is missing, blank or not upper case (review advisory R3-moneda-unnormalized) is
read as the markup path reads it: no currency is ARS, and `usd` is USD.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.sell_in_out_producto import SellInProducto
from app.services.productos_sell_in_out import SellInOutBatch, en_moneda_costo
from app.services.sell_in.costing import LoteVigente

LOTE = SellInProducto(compra_item_id=7, descuento_unit=5000.0, costo=45000.0, unidades_restantes=2)


@pytest.mark.parametrize("moneda", [None, "", "  ", "ars", " ARS "])
def test_a_missing_blank_or_lower_case_peso_currency_keeps_the_ars_figures(moneda) -> None:
    sell_in = en_moneda_costo(LOTE, moneda, 1250.0)

    assert (sell_in.moneda_costo, sell_in.costo_moneda, sell_in.descuento_unit_moneda) == ("ARS", 45000.0, 5000.0)


@pytest.mark.parametrize("moneda", ["usd", " USD ", "USD"])
def test_a_usd_currency_in_any_case_converts_at_the_rate(moneda) -> None:
    sell_in = en_moneda_costo(LOTE, moneda, 1250.0)

    assert sell_in.moneda_costo == "USD"
    assert (sell_in.costo_moneda, sell_in.descuento_unit_moneda) == (pytest.approx(36.0), pytest.approx(4.0))


def test_a_usd_cost_without_a_rate_has_no_figure_in_usd() -> None:
    sell_in = en_moneda_costo(LOTE, "USD", None)

    assert (sell_in.moneda_costo, sell_in.costo_moneda, sell_in.descuento_unit_moneda) == ("USD", None, None)
    assert (sell_in.costo, sell_in.descuento_unit) == (45000.0, 5000.0)  # the ARS figures stay as they are


def _batch() -> SellInOutBatch:
    lote = LoteVigente(compra_item_id=7, descuento_unit_ars=Decimal("5000"), unidades_restantes=2)
    return SellInOutBatch(hoy=date(2026, 11, 12), sell_in={1: lote}, campanas={}, bna=None)


def _producto(costo: float, moneda) -> SimpleNamespace:
    return SimpleNamespace(item_id=1, costo=costo, moneda_costo=moneda, iva=21.0)


def test_markups_of_a_product_without_a_cost_currency_read_it_as_ars_and_never_divide_by_the_rate() -> None:
    sell_in = _batch().markups(_producto(50000.0, None), tipo_cambio=1250.0).payload().sell_in

    assert (sell_in.costo, sell_in.moneda_costo, sell_in.costo_moneda) == (45000.0, "ARS", 45000.0)


def test_markups_of_a_lower_case_usd_cost_convert_it_and_name_it_usd() -> None:
    sell_in = _batch().markups(_producto(40.0, "usd"), tipo_cambio=1250.0).payload().sell_in

    assert sell_in.costo == 45000.0  # 40 USD x 1250 - 5000
    assert (sell_in.moneda_costo, sell_in.costo_moneda) == ("USD", pytest.approx(36.0))
