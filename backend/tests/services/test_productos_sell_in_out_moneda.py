"""The Productos sell in / sell out payload without its sell in part (costo SI T5 PR B).

costo SI replaced the FIFO lots and the per-sale cost bonuses (owner L24: no per-sale loyalty ever), so the payload no
longer carries a "c/ sell in" figure, nor that figure in the cost's currency (the retired S10 conversion
`en_moneda_costo`). Only the sell out ("c/ SO") and its markups over the cost stay. A cost currency that is missing,
blank or not upper case is still read as the markup path reads it: no currency is ARS, and `usd` is USD.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas import sell_in_out_producto
from app.schemas.sell_in_out_producto import SellInOutProducto, SellInOutTienda
from app.services import productos_sell_in_out
from app.services.productos_sell_in_out import SellInOutBatch


def test_the_payloads_have_no_sell_in_field() -> None:
    assert "sell_in" not in SellInOutProducto.model_fields
    assert "sell_in" not in SellInOutTienda.model_fields
    assert set(SellInOutProducto.model_fields) == {"sell_out", "markups_sell_in", "markups_sell_in_out"}


def test_the_sell_in_figure_and_its_currency_conversion_are_gone() -> None:
    assert not hasattr(sell_in_out_producto, "SellInProducto")
    assert not hasattr(productos_sell_in_out, "en_moneda_costo")


def _producto(costo: float, moneda) -> SimpleNamespace:
    return SimpleNamespace(item_id=1, costo=costo, moneda_costo=moneda, iva=21.0)


def test_a_product_without_sell_out_has_no_payload() -> None:
    batch = SellInOutBatch(hoy=date(2026, 11, 12), campanas={}, bna=None)

    assert batch.markups(_producto(50000.0, "ARS"), tipo_cambio=1250.0).payload() is None


@pytest.mark.parametrize("moneda, costo, esperado", [(None, 50000.0, 50000.0), ("usd", 40.0, 50000.0)])
def test_the_markup_cost_reads_the_currency_as_the_markup_path_does(moneda, costo, esperado) -> None:
    # A product outside the costo SI read: its own cost, ARS without a currency, USD x the rate for `usd`.
    acc = SellInOutBatch(hoy=date(2026, 11, 12), campanas={}, bna=None).markups(
        _producto(costo, moneda), tipo_cambio=1250.0
    )

    assert acc._costo == esperado
