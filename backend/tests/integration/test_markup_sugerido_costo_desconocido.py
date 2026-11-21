"""PATCH /markups-tienda/productos/{item_id}/markup-sugerido with an unknown cost (sell-in-costo-si T3 PR 6, interfaz §7:
"unknown = None + log, never 0, never wrong currency").

Before: the response built the suggested price from `producto.costo or 0.0`, and a USD cost with no USD rate was taken
as pesos (USD 100 -> 100 ARS -> a price a thousand times too low). Now an unknown cost gives no price and no total
markup, with a log line naming the product. The cost base itself (list cost) is unchanged here: it waits for the owner
(plan handoffs/sell-in-costo-si-t3-pr6-plan.md). Invented data."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from app.api.endpoints.productos_shared import computar_precio_sugerido
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tipo_cambio import TipoCambio
from app.services.pricing_calculator import obtener_constantes_pricing
from tests.integration.test_markup_sugerido_endpoint import ENDPOINT, con_permiso_markups  # noqa: F401

ITEM = 4242


def _producto(db, costo, moneda: str) -> None:
    db.add(
        ProductoERP(
            item_id=ITEM, codigo="TSU-1", descripcion="P", marca=None, costo=costo, moneda_costo=moneda, iva=21.0
        )
    )
    db.add(ProductoPricing(item_id=ITEM, markup_calculado=30.0))
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


def test_a_usd_cost_without_a_rate_is_unknown_never_pesos(client, auth_headers, db, con_permiso_markups, caplog):  # noqa: F811
    _producto(db, 100.0, "USD")  # no tipo_cambio row at all

    with caplog.at_level(logging.WARNING):
        data = _patch(client, auth_headers)

    _sin_precio(data)
    assert f"no USD rate for item {ITEM}" in caplog.text


def test_no_cost_is_unknown_never_0(client, auth_headers, db, con_permiso_markups, caplog):  # noqa: F811
    _producto(db, None, "ARS")

    with caplog.at_level(logging.WARNING):
        data = _patch(client, auth_headers)

    _sin_precio(data)
    assert f"no cost for item {ITEM}" in caplog.text


def test_a_usd_cost_with_a_rate_keeps_todays_price(client, auth_headers, db, con_permiso_markups):  # noqa: F811
    _producto(db, 100.0, "USD")
    db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=1000.0, venta=1000.0))
    db.flush()

    data = _patch(client, auth_headers)

    varios = obtener_constantes_pricing(db).get("varios", 6.5)
    sin_iva, con_iva, total = computar_precio_sugerido(100_000.0, 21.0, 30.0, 5.0, varios)
    assert data["precio_sugerido_sin_iva"] == pytest.approx(sin_iva)
    assert data["precio_sugerido_con_iva"] == pytest.approx(con_iva)
    assert data["markup_sugerido_total"] == pytest.approx(total) == 35.0
