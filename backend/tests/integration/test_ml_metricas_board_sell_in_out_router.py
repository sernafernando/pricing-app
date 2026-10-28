"""sell-in-sell-out T11: the sell in / sell out figures of `GET /api/ml-metricas/board`, its sub-rows and its CSV.

Owner: "Always show both: cost and cost with sell in; markup and totals without and with sell out." They are profit
figures: present only with `ml_metricas.ver_ganancia` (null without it, and sorting by them is refused like any
margin sort), and never for `tplink.solo` (they are on the Gauss basis). The figures without them never change.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo
from app.models.sell_out import SellOutCampana, SellOutConsumo
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    _grant,
    _producto,
    _pub,
    bg_sessions,
)
from tests.integration.test_ml_metricas_board_tplink_solo_router import _all_keys
from tests.services.ml_daily_metrics.seed import Line, seed_sale

_ORDER_IDS = iter(range(2000096000000001, 2000096000100000))
DIA = date(2026, 9, 20)
# The campaign's and purchase's author: the admin of the request.
_USUARIO = [0]


def _sale(db, product, mla, tg, costo) -> int:
    """One unit sold for 200; the line's `item_row_id` (the sell in / sell out `venta_ref`)."""
    order_id = next(_ORDER_IDS)
    accredited = datetime.combine(DIA, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
    seed_sale(db, order_id, accredited, [Line(product, mla, 1, Decimal("200"))], tg=tg, costo=costo)
    db.flush()
    return db.query(MlOrderItemOps.id).filter(MlOrderItemOps.order_id == order_id).scalar()


def _campana(db, moneda: str, **values) -> int:
    campana = SellOutCampana(
        nombre=f"Campaña {moneda}",
        fecha_desde=DIA,
        fecha_hasta=DIA,
        tipo="por_unidad",
        monto_unit=Decimal("1"),
        moneda=moneda,
        usuario_id=_USUARIO[0],
        **values,
    )
    db.add(campana)
    db.flush()
    return campana.id


def _compra_item(db) -> int:
    compra = SellInCompra(
        fecha_compra=DIA,
        moneda="ARS",
        monto_total=Decimal("10"),
        formula="por_unidad",
        usuario_id=_USUARIO[0],
    )
    db.add(compra)
    db.flush()
    item = SellInCompraItem(
        compra_id=compra.id, item_id=11, cantidad=1, costo_base_unit=Decimal("100"), monto_asignado=Decimal("10")
    )
    db.add(item)
    db.flush()
    return item.id


def _consumos(db, ref: int, sell_in=None, sell_out=()) -> None:
    if sell_in is not None:
        db.add(
            SellInConsumo(
                compra_item_id=_compra_item(db),
                canal="ml",
                venta_ref=ref,
                item_id=11,
                fecha_venta=DIA,
                unidades=1,
                descuento_ars=Decimal(sell_in),
            )
        )
    for campana_id, monto, tc in sell_out:
        db.add(
            SellOutConsumo(
                campana_id=campana_id,
                canal="ml",
                venta_ref=ref,
                item_id=11,
                fecha_venta=DIA,
                unidades=1,
                monto=Decimal(monto),
                tc_venta=None if tc is None else Decimal(tc),
            )
        )


@pytest.fixture()
def sells(db, rol_admin, admin_user):
    """11 (MLA1): tg 30 / c 100, sell in $10 and an ARS sell out of $5.
    12 (MLA2): tg 40 / c 100, a USD sell out without its rate yet (pending)."""
    db.add_all(
        [
            MlTiendaOficial(store_id=57997, nombre="Gauss", clave=None, orden=1, activa=True),
            MlTiendaOficial(store_id=471846, nombre="TP-Link", clave="tplink", orden=2, activa=True),
        ]
    )
    _USUARIO[0] = admin_user.id
    _producto(db, 11, "Router AX55", "TP-Link")
    _producto(db, 12, "Switch", "TP-Link")
    db.flush()
    _pub(db, 1, "MLA1", 11, 471846)
    _pub(db, 2, "MLA2", 12, 471846)
    ars, usd = _campana(db, "ARS"), _campana(db, "USD", tc_modo="fijo", tipo_cambio=Decimal("1000"))
    _consumos(db, _sale(db, 11, "MLA1", "30", "100"), sell_in="10", sell_out=[(ars, "5", None)])
    _consumos(db, _sale(db, 12, "MLA2", "40", "100"), sell_out=[(usd, "1", None)])
    db.commit()


def _get(client, headers, path="", **params):
    resp = client.get(
        URL + path, params={"date_from": "2026-09-01", "date_to": "2026-09-30", **params}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_key(body):
    return {row["key"]: row for row in body["rows"]}


class TestWithTheProfitView:
    @pytest.fixture(autouse=True)
    def _ganancia(self, db, rol_admin, sells):
        _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        db.commit()

    def test_each_row_carries_its_figures_with_sell_in_and_sell_out(self, client, admin_auth_headers) -> None:
        rows = _by_key(_get(client, admin_auth_headers))

        assert rows["11"]["total_gauss"] == 30.0
        assert rows["11"]["sell_in_out"] == {
            "sell_in": 10.0,
            "sell_out": 5.0,
            "sell_out_pendientes": 0,
            "sell_out_estimados": 0,
            "costo": 100.0,
            "costo_sell_in": 90.0,
            "total_gauss": 45.0,
            "markup_pct": 50.0,
        }
        assert rows["12"]["sell_in_out"]["sell_out_pendientes"] == 1
        assert rows["12"]["sell_in_out"]["total_gauss"] == 40.0

    def test_the_kpi_strip_sums_them(self, client, admin_auth_headers) -> None:
        kpis = _get(client, admin_auth_headers)["kpis"]

        assert kpis["sell_in_out"]["sell_in"] == 10.0
        assert kpis["sell_in_out"]["total_gauss"] == 85.0
        assert kpis["sell_in_out"]["sell_out_pendientes"] == 1

    def test_the_publications_carry_them_too(self, client, admin_auth_headers) -> None:
        body = _get(client, admin_auth_headers, "/products/11/publications")

        assert body["rows"][0]["sell_in_out"]["sell_in"] == 10.0

    def test_the_csv_has_the_columns(self, client, admin_auth_headers) -> None:
        resp = client.get(URL + "/export", headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
        header, *lines = list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
        row = dict(zip(header, next(line for line in lines if "Router AX55" in line)))

        assert (row["Sell in"], row["Sell out"], row["Costo c/ sell in"]) == ("10,00", "5,00", "90,00")
        assert (row["Total Gauss c/ sell in/out"], row["Markup c/ sell in/out %"]) == ("45,00", "50,00")

    def test_a_sell_in_that_does_not_apply_is_empty_on_screen_and_in_the_csv(self, client, admin_auth_headers) -> None:
        # Owner: "en las filas que no aplica estaría bueno que directamente esté vacío así no hace ruido".
        figures = _by_key(_get(client, admin_auth_headers))["12"]["sell_in_out"]
        assert (figures["sell_in"], figures["costo_sell_in"], figures["costo"]) == (None, None, 100.0)

        resp = client.get(URL + "/export", headers=admin_auth_headers)
        header, *lines = list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
        row = dict(zip(header, next(line for line in lines if "Switch" in line)))
        assert (row["Sell in"], row["Costo c/ sell in"], row["Total Gauss c/ sell in/out"]) == ("", "", "40,00")

    def test_the_pending_sell_out_count_is_empty_in_the_csv_where_no_sell_out_applies(
        self, client, admin_auth_headers, db
    ) -> None:
        # A sale with neither sell in nor sell out: the screen leaves the sell out (and its pending count) empty.
        _producto(db, 13, "Hub", "TP-Link")
        _sale(db, 13, "MLA3", "20", "100")
        db.commit()

        resp = client.get(URL + "/export", headers=admin_auth_headers)
        header, *lines = list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
        rows = {name: dict(zip(header, next(line for line in lines if name in line))) for name in ("Hub", "Switch")}
        assert (rows["Hub"]["Sell out"], rows["Hub"]["Sell out pendientes"]) == ("", "")
        # Where a sell out applies, its pending count stays a number.
        assert rows["Switch"]["Sell out pendientes"] == "1"


class TestWithoutTheProfitView:
    @pytest.fixture(autouse=True)
    def _ver(self, db, rol_admin, sells):
        _grant(db, rol_admin, "ml_metricas.ver")
        db.commit()

    def test_no_figure_and_no_sort(self, client, admin_auth_headers) -> None:
        body = _get(client, admin_auth_headers)

        assert all(row["sell_in_out"] is None for row in body["rows"])
        assert body["kpis"]["sell_in_out"] is None
        resp = client.get(URL, params={"sort": "markup_sell"}, headers=admin_auth_headers)
        assert resp.status_code == 403


def test_tplink_solo_never_gets_them(client, admin_auth_headers, db, rol_admin, sells) -> None:
    _grant(db, rol_admin, "ml_metricas.ver", "tplink.solo")
    db.commit()

    body = _get(client, admin_auth_headers)

    assert body["rows"] and "sell_in_out" not in _all_keys(body)


@pytest.mark.parametrize(
    ("sort", "expected", "ascending"),
    [
        # 10 vs an empty cell (12 has no sell in: last both ways, never sorted as 0); 5 vs 0 (the pending sell out is
        # left out); 45 vs 40; 50% vs 40% (without them: 30% vs 40%).
        ("sell_in", ["11", "12"], ["11", "12"]),
        ("sell_out", ["11", "12"], ["12", "11"]),
        ("total_gauss_sell", ["11", "12"], ["12", "11"]),
        ("markup_sell", ["11", "12"], ["12", "11"]),
    ],
)
def test_sorts_by_the_sell_in_out_columns(
    client, admin_auth_headers, db, rol_admin, sells, sort, expected, ascending
) -> None:
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    db.commit()

    for direction, order in (("desc", expected), ("asc", ascending)):
        body = _get(client, admin_auth_headers, sort=sort, sort_dir=direction)
        assert [row["key"] for row in body["rows"]] == order


def test_the_markup_with_sell_in_out_is_no_sort_with_costos_tp(
    client, admin_auth_headers, db, rol_admin, sells
) -> None:
    """With "Costos TP" there is no markup with sell in / sell out (the sell in is on the Gauss cost): 422, never a
    table that claims an order it does not have."""
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    db.commit()

    resp = client.get(
        URL,
        params={"date_from": "2026-09-01", "date_to": "2026-09-30", "sort": "markup_sell", "costos_tp": "true"},
        headers=admin_auth_headers,
    )

    assert resp.status_code == 422, resp.text
