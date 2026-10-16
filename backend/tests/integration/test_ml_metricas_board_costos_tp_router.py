"""metricas-ml-tplink-mode P4: the `costos_tp` toggle of `GET /api/ml-metricas/board`, its sub-rows, its group
nodes and its CSV export.

- OFF (the default): no TP field anywhere (null), the response is what it was.
- ON: needs `ml_metricas.ver_ganancia` (Total TP and Markup TP are profit figures, like Total Gauss); the TP
  store group comes from the `tplink` clave (503 when none is configured: fail closed, never every store); the
  rows, the KPI strip and the CSV carry Total TP next to Total Gauss, and the incomplete TP count.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.ml_ads import MlAdsItemDay
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.services.ml_daily_metrics import board
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    _grant,
    _producto,
    _pub,
    bg_sessions,
)
from tests.services.ml_daily_metrics.seed import Line, seed_sale

_ORDER_IDS = iter(range(2000095000000001, 2000095000100000))
ON = {"costos_tp": "true"}


def _sale(db, product, mla, units, gross, tg, costo, costo_tp=None, total_tp=None) -> None:
    order_id = next(_ORDER_IDS)
    accredited = datetime.combine(date(2026, 9, 20), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
    seed_sale(db, order_id, accredited, [Line(product, mla, units, Decimal(gross) / units)], tg=tg, costo=costo)
    metrics = db.get(MlOrderMetrics, order_id)
    metrics.costo_tp = Decimal(costo_tp) if costo_tp is not None else None
    metrics.total_tp = Decimal(total_tp) if total_tp is not None else None
    metrics.tp_incompleto = costo_tp is None


@pytest.fixture()
def tp_data(db, rol_admin):
    """11 sells in Gauss 57997 (tg 30 / c 100) and in TP 2645 (tg 20 / c 100, TP cost 50, Total TP 70);
    12 sells only in TP 471846 without a TP cost (incomplete)."""
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    db.add_all(
        [
            MlTiendaOficial(store_id=57997, nombre="Gauss", clave=None, orden=1, activa=True),
            MlTiendaOficial(store_id=2645, nombre="TP-Link vieja", clave="tplink", orden=2, activa=False),
            MlTiendaOficial(store_id=471846, nombre="TP-Link", clave="tplink", orden=3, activa=True),
        ]
    )
    _producto(db, 11, "Router AX55", "TP-Link")
    _producto(db, 12, "Switch", "TP-Link")
    db.flush()
    _pub(db, 1, "MLA1", 11, 57997)
    _pub(db, 2, "MLA2", 11, 2645)
    _pub(db, 3, "MLA3", 12, 471846)
    _sale(db, 11, "MLA1", 1, "200", "30", "100")
    _sale(db, 11, "MLA2", 1, "200", "20", "100", costo_tp="50", total_tp="70")
    _sale(db, 12, "MLA3", 1, "200", "40", "100")
    db.commit()


def _get(client, headers, path="", **params):
    resp = client.get(URL + path, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_key(body):
    return {row["key"]: row for row in body["rows"]}


def test_off_carries_no_tp_field(client, admin_auth_headers, tp_data) -> None:
    body = _get(client, admin_auth_headers)

    assert body["kpis"]["total_tp"] is None
    assert all(row["total_tp"] is None and row["tp_incompletos"] is None for row in body["rows"])
    assert _by_key(body)["11"]["markup_pct"] == 25.0  # (30 + 20) / (100 + 100)


def test_on_swaps_the_tp_store_cost_and_adds_total_tp(client, admin_auth_headers, tp_data) -> None:
    body = _get(client, admin_auth_headers, **ON)

    rows = _by_key(body)
    # Total Gauss stays; the TP pair's markup is Markup TP: (30 + 70) / (100 + 50).
    assert (rows["11"]["total_gauss"], rows["11"]["total_tp"], rows["11"]["tp_incompletos"]) == (50.0, 70.0, 0)
    assert rows["11"]["markup_pct"] == 66.7
    # No TP cost: no Total TP, no markup (never the Gauss cost), flagged.
    assert (rows["12"]["total_tp"], rows["12"]["tp_incompletos"], rows["12"]["markup_pct"]) == (None, 1, None)
    assert body["kpis"]["total_gauss"]["value"] == 90.0
    assert body["kpis"]["total_tp"] == {"value": 70.0, "incompletos": 1}


def test_on_reaches_the_sub_rows_and_the_group_nodes(client, admin_auth_headers, tp_data) -> None:
    subs = _by_key(_get(client, admin_auth_headers, "/products/11/publications", **ON))
    assert (subs["MLA1"]["total_tp"], subs["MLA2"]["total_tp"]) == (None, 70.0)

    nodes = _get(client, admin_auth_headers, group_by="group", dimension="tienda", **ON)
    tp = _by_key(nodes)["c:tplink"]
    assert (tp["total_tp"], tp["tp_incompletos"]) == (70.0, 1)


def test_on_needs_ver_ganancia(client, admin_auth_headers, db, rol_admin) -> None:
    _grant(db, rol_admin, "ml_metricas.ver")
    db.commit()

    assert client.get(URL, params=ON, headers=admin_auth_headers).status_code == 403
    assert client.get(URL + "/export", params=ON, headers=admin_auth_headers).status_code == 403


def test_on_without_a_tplink_store_fails_closed(client, admin_auth_headers, db, rol_admin) -> None:
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    db.commit()

    assert client.get(URL, params=ON, headers=admin_auth_headers).status_code == 503


def _csv(client, headers, **params):
    resp = client.get(URL + "/export", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))


def test_the_csv_adds_total_tp_only_when_on(client, admin_auth_headers, tp_data) -> None:
    off = _csv(client, admin_auth_headers)
    assert "Total TP" not in off[0]

    on = _csv(client, admin_auth_headers, **ON)
    header = on[0]
    tp, incompletos = header.index("Total TP"), header.index("TP incompletas")
    assert header[tp - 1] == "Total Gauss"
    by_product = {line[0]: line for line in on[1:]}
    assert (by_product["Router AX55"][tp], by_product["Router AX55"][incompletos]) == ("70,00", "0")
    assert (by_product["Switch"][tp], by_product["Switch"][incompletos]) == ("", "1")


def test_the_filter_classifies_the_new_fields() -> None:
    assert {"costos_tp", "tp_store_ids"} <= board.NAVIGATION_FIELDS


def test_restar_publicidad_takes_the_ads_off_total_tp_too(db, tp_data) -> None:
    # Total TP = Total Gauss + cost - TP cost: with the ads off Total Gauss, they come off Total TP as well.
    db.add(MlAdsItemDay(advertiser_id=1, ad_group_id=1, item_id="MLA2", day=date(2026, 9, 21), raw={}, cost=10))
    db.commit()
    f = board.BoardFilter(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        restar_publicidad=True,
        costos_tp=True,
        tp_store_ids=(2645, 471846),
    )
    with board.Board(db, f, scope_pairs=None) as b:
        row = {r.key: r for r in b.page(None, with_series=False)}["11"]

    ads = row.ads_cost
    assert ads > 0
    assert (row.tg, row.total_tp, row.mtg, row.costo) == (50 - ads, 70 - ads, 100 - ads, Decimal("150.00"))


def test_the_csv_combines_the_publicidad_position_and_costos_tp(client, admin_auth_headers, db, tp_data) -> None:
    # 10 of ads on the TP publication: off Total Gauss AND off Total TP, the board's figures at that position.
    db.add(MlAdsItemDay(advertiser_id=1, ad_group_id=1, item_id="MLA2", day=date(2026, 9, 21), raw={}, cost=10))
    db.commit()
    both = {**ON, "publicidad": "mla"}
    board_row = _by_key(_get(client, admin_auth_headers, **both))["11"]

    lines = _csv(client, admin_auth_headers, **both)

    header = lines[0]
    gauss = header.index("Total Gauss")
    assert header[gauss : gauss + 5] == [
        "Total Gauss",
        "Publicidad (inversión)",
        "Total TP",
        "TP incompletas",
        "Markup %",
    ]
    router = {line[0]: line for line in lines[1:]}["Router AX55"]
    money = [f"{value:.2f}".replace(".", ",") for value in (50 - board_row["ads"]["cost"], board_row["ads"]["cost"])]
    assert board_row["ads"]["cost"] > 0
    assert router[gauss : gauss + 4] == [*money, f"{board_row['total_tp']:.2f}".replace(".", ","), "0"]
    assert board_row["total_tp"] == 70 - board_row["ads"]["cost"]
