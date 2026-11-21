"""PATCH /markups-tienda/productos/{item_id}/markup-sugerido prices Sugerido over costo SI (sell-in-costo-si T3 PR 6,
owner L20: "los precios de gremio y sugerido toman costo si"), and an unknown cost gives no price (interfaz §7:
"unknown = None + log, never 0, never wrong currency").

Before: the response built the suggested price from the list cost, `producto.costo or 0.0`, and a USD cost with no
USD rate was taken as pesos (USD 100 -> 100 ARS -> a price a thousand times too low). Now the base is costo SI in
pesos (`costo_ars_actual`, the list cost without a costo SI step, Q1); an unknown one gives no price and no total
markup, with a log line naming the product. SQLite: the reader is its stand-in (`tests/costo_si_lista.py`), and the
costo SI case swaps in a step. Invented data."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from app.api.endpoints.productos_shared import computar_precio_sugerido
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tipo_cambio import TipoCambio
from app.services.costo_si import lote
from app.services.pricing_calculator import obtener_constantes_pricing
from tests.costo_si_lista import actuales_lista, costo_si_lista  # noqa: F401 (the costo SI reader's SQLite stand-in)
from tests.integration.test_markup_sugerido_endpoint import ENDPOINT, con_permiso_markups  # noqa: F401

pytestmark = pytest.mark.usefixtures("costo_si_lista")

ITEM = 4242


def _producto(db, costo, moneda: str) -> None:
    db.add(
        ProductoERP(
            item_id=ITEM, codigo="TSU-1", descripcion="P", marca=None, costo=costo, moneda_costo=moneda, iva=21.0
        )
    )
    db.add(ProductoPricing(item_id=ITEM, markup_calculado=30.0))
    db.flush()


def _tasa(db) -> None:
    db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=1000.0, venta=1000.0))
    db.flush()


def _patch(client, auth_headers) -> dict:
    response = client.patch(ENDPOINT.format(item_id=ITEM), json={"markup_sugerido": 5.0}, headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def _sin_precio(data: dict) -> None:
    assert data["precio_sugerido_sin_iva"] is None
    assert data["precio_sugerido_con_iva"] is None
    assert data["markup_sugerido_total"] is None
    assert data["markup_sugerido_valor"] == 5.0  # the saved value is still reported


def _con_precio(db, data: dict, costo_ars: float) -> None:
    varios = obtener_constantes_pricing(db).get("varios", 6.5)
    sin_iva, con_iva, total = computar_precio_sugerido(costo_ars, 21.0, 30.0, 5.0, varios)
    assert data["precio_sugerido_sin_iva"] == pytest.approx(sin_iva)
    assert data["precio_sugerido_con_iva"] == pytest.approx(con_iva)
    assert data["markup_sugerido_total"] == pytest.approx(total) == 35.0


def test_a_usd_cost_without_a_rate_is_unknown_never_pesos(client, auth_headers, db, con_permiso_markups, caplog):  # noqa: F811
    _producto(db, 100.0, "USD")  # no tipo_cambio row at all

    with caplog.at_level(logging.WARNING):
        data = _patch(client, auth_headers)

    _sin_precio(data)
    assert f"no cost in pesos for item {ITEM}" in caplog.text


def test_no_cost_is_unknown_never_0(client, auth_headers, db, con_permiso_markups, caplog):  # noqa: F811
    _producto(db, None, "ARS")

    with caplog.at_level(logging.WARNING):
        data = _patch(client, auth_headers)

    _sin_precio(data)
    assert f"no cost in pesos for item {ITEM}" in caplog.text


def test_without_a_costo_si_step_the_list_cost_prices_it(client, auth_headers, db, con_permiso_markups):  # noqa: F811
    _producto(db, 100.0, "USD")
    _tasa(db)

    _con_precio(db, _patch(client, auth_headers), 100_000.0)  # Q1: the list cost, USD 100 x 1000


def test_the_price_is_over_costo_si(client, auth_headers, db, con_permiso_markups, monkeypatch):  # noqa: F811
    _producto(db, 100.0, "USD")
    _tasa(db)

    def actuales(db, item_ids, *, tipo_cambio=None):
        out = actuales_lista(db, item_ids, tipo_cambio=tipo_cambio)
        tc = Decimal(str(tipo_cambio))
        si = lote.Costo(ITEM, Decimal("80"), "USD", lote.FUENTE_COSTO_SI, date(2026, 11, 1), tc, Decimal("80") * tc)
        return {**out, ITEM: si}

    monkeypatch.setattr(lote, "actuales", actuales)

    _con_precio(db, _patch(client, auth_headers), 80_000.0)  # L20: costo SI USD 80 x 1000, not the list USD 100
