"""Métricas ML audit B8: `GET /api/ml-metricas/board/envios`, the period's sales by shipping type under the board's
filters. Same data, clock and permissions as the board's router tests (`board_data`: in the period, p11 Epson sells
6 units for $600 and p14 TP-Link 1 unit for $150; its orders have no shipment, so they read "desconocido")."""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

from datetime import date

from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _day,
    _frozen_clock,
    _grant,
    _producto,
    _pub,
    bg_sessions,
    board_data,
)
from tests.integration.test_ml_metricas_board_scope_router import _headers, people  # noqa: F401 -- fixtures
from tests.integration.test_ml_metricas_board_tplink_solo_router import tienda, tp_solo  # noqa: F401 -- fixtures

ENVIOS = f"{URL}/envios"


def _get(client, headers, **params):
    resp = client.get(ENVIOS, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["rows"]


def test_the_sales_of_the_period_by_shipping_type(client, admin_auth_headers, board_data) -> None:
    rows = _get(client, admin_auth_headers)

    assert [r["modo"] for r in rows] == ["desconocido"]
    assert (rows[0]["units"], rows[0]["gross"]) == (7, 750)
    # The board's own figures for the same request.
    kpis = client.get(URL, headers=admin_auth_headers).json()["kpis"]
    assert (rows[0]["operations"], rows[0]["gross"]) == (kpis["operations"]["value"], kpis["gross"]["value"])


def test_the_board_filters_apply(client, admin_auth_headers, board_data) -> None:
    rows = _get(client, admin_auth_headers, marcas="Epson")

    assert [(r["units"], r["gross"]) for r in rows] == [(6, 600)]


def test_no_profit_permission_needed(client, admin_auth_headers, db, rol_admin) -> None:
    # Only "ver": the sales by shipping type are sales figures, no profit in them.
    _grant(db, rol_admin, "ml_metricas.ver")
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 30), 2, "200", "30", "100")
    db.commit()

    rows = _get(client, admin_auth_headers)

    assert [(r["modo"], r["units"], r["gross"]) for r in rows] == [("desconocido", 2, 200)]


def test_a_pm_sees_only_the_sales_of_their_pairs(client, people) -> None:
    # `people`: ana is PM of Epson, beto of Lenovo plus TP-Link as sub-PM, nadie holds no pair.
    def shipped(user):
        return [(r["modo"], r["units"], r["gross"]) for r in _get(client, _headers(user))]

    assert shipped(people["ana"]) == [("desconocido", 6, 600)]
    assert shipped(people["beto"]) == [("desconocido", 1, 150)]
    assert shipped(people["nadie"]) == []


def test_a_tp_only_user_sees_only_the_tp_store_sales(client, admin_auth_headers, tp_solo) -> None:
    # `tienda`: one sale per publication; the Gauss one (MLA1, $200) stays out, the two TP-store ones count.
    rows = _get(client, admin_auth_headers)

    assert [(r["modo"], r["operations"], r["units"], r["gross"]) for r in rows] == [("desconocido", 2, 2, 400)]


def test_without_the_view_permission_it_is_forbidden(client, admin_auth_headers) -> None:
    assert client.get(ENVIOS, headers=admin_auth_headers).status_code == 403
