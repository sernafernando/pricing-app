"""Métricas ML audit B8: `GET /api/ml-metricas/board/envios`, the period's sales by shipping type under the board's
filters. Same data, clock and permissions as the board's router tests (`board_data`: in the period, p11 Epson sells
6 units for $600 and p14 TP-Link 1 unit for $150; its orders have no shipment, so they read "desconocido")."""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    _grant,
    bg_sessions,
    board_data,
)

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
    _grant(db, rol_admin, "ml_metricas.ver")
    db.flush()

    assert _get(client, admin_auth_headers) == []


def test_without_the_view_permission_it_is_forbidden(client, admin_auth_headers) -> None:
    assert client.get(ENVIOS, headers=admin_auth_headers).status_code == 403
