"""sell-in-sell-out T11 on real Postgres: the board's sell in / sell out figures.

Owner: "Always show both: cost and cost with sell in; markup and totals without and with sell out." Sell in lowers
the cost; sell out is a credit added to profit. Each sold line takes what the allocators wrote for it
(`sell_in_consumos` / `sell_out_consumos`, canal 'ml', `venta_ref` = the line's `item_row_id`), converted to ARS
like the sell-out screen (`resumen.ARS_FILA`). A line whose USD sell out has no rate yet is counted as pending,
never read as 0; one whose campaign rate is still an estimate is counted as estimated.

With `BoardFilter.sell_in_out` OFF the board reports none of it. Both line sources are covered.

The consumption tables are minimal TEMP tables (the real ones carry foreign keys to the purchases and campaigns,
which the board never reads): the allocators' business is tested in `sell_in/` and `sell_out/`.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetricsDirty
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import sell_in_out_of
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.order_metrics.sale_lines_store import STORED_COLUMNS
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
OFF = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)
ON = dataclasses.replace(OFF, sell_in_out=True)
TP_STORES = (2645,)

CONSUMPTION_DDL = (
    "CREATE TEMP TABLE sell_in_consumos (canal VARCHAR(8), venta_ref BIGINT, descuento_ars NUMERIC(18, 2)) "
    "ON COMMIT DROP;"
    "CREATE TEMP TABLE sell_out_campanas (id BIGINT PRIMARY KEY, moneda VARCHAR(3), tc_modo VARCHAR(12), "
    "tipo_cambio NUMERIC(18, 6)) ON COMMIT DROP;"
    "CREATE TEMP TABLE sell_out_consumos (campana_id BIGINT, canal VARCHAR(8), venta_ref BIGINT, "
    "monto NUMERIC(18, 2), tc_venta NUMERIC(18, 6)) ON COMMIT DROP;"
    "INSERT INTO sell_out_campanas VALUES (1, 'ARS', 'fijo', NULL), (2, 'USD', 'fijo', 1000), "
    "(3, 'USD', 'al_cobro', NULL)"
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _line(db, order_id: int) -> int:
    return db.execute(text("SELECT id FROM ml_order_items_ops WHERE order_id = :o"), {"o": order_id}).scalar_one()


@pytest.fixture(params=["live", "persisted"])
def catalog(request, board_pg, monkeypatch):
    """31: two sales of MLA931 (tg10/c50 each). Sale 1: sell in $5 and an ARS sell out of $3. Sale 2: a USD sell
    out of 0.01 at a known rate of 200 ($2) on campaign 2, and the same sale is also in another channel's
    consumption (never counted).
    32: one sale (tg20/c100) with an al_cobro USD sell out whose rate is an estimate ($4: 0.02 at 200) and one
    (tg20/c100) with a USD sell out without its rate yet: pending, never 0.
    33: one sale (tg10/c50) with no sell in nor sell out.
    34: one sale whose markup is unknown (cost 0) with a sell in of $1: it adds to Total Gauss, not to the markup.
    35: one sale whose Total Gauss is not resolved yet with a sell in of $7: outside Total Gauss, so outside its
    sell in / sell out too."""
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (31, 'S31', 'Router', 'TP-Link', 'Redes', 1, 1), (32, 'S32', 'Switch', 'TP-Link', 'Redes', 1, 1), "
            "(33, 'S33', 'Mouse', 'Logi', 'Perifericos', 2, 1), (34, 'S34', 'Cable', 'Logi', 'Perifericos', 2, 1), "
            "(35, 'S35', 'Hub', 'Otra', 'Perifericos', 2, 1);"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true), (2645, 'TP-Link', 'tplink', 2, true)"
        )
    )
    sales = (
        (1, 31, "MLA931", 57997, "10", "50"),
        (2, 31, "MLA931", 57997, "10", "50"),
        (3, 32, "MLA932", 2645, "20", "100"),
        (4, 32, "MLA932", 2645, "20", "100"),
        (5, 33, "MLA933", 57997, "10", "50"),
        (6, 34, "MLA934", 57997, "10", "0"),
        (7, 35, "MLA935", 57997, "10", "50"),
    )
    published = set()
    refs = {}
    for n, product, mla, store, tg, costo in sales:
        if mla not in published:
            published.add(mla)
            db.execute(
                text(
                    "INSERT INTO tb_mercadolibre_items_publicados "
                    "(mlp_id, mlp_publicationid, item_id, mlp_official_store_id) VALUES (:id, :mla, :item, :store)"
                ),
                {"id": 9100 + n, "mla": mla, "item": product, "store": store},
            )
        order_id = 2000012345679000 + n
        _order(db, order_id, [(product, mla, 1, Decimal(costo))], tg=tg, costo=costo)
        _group(db, f"o:{order_id}", [order_id], NOW - timedelta(hours=3))
        refs[n] = _line(db, order_id)
    db.execute(
        text("UPDATE ml_order_metrics SET gauss_status = 'unresolved', total_gauss = NULL WHERE order_id = :o"),
        {"o": 2000012345679007},
    )
    db.execute(text(CONSUMPTION_DDL))
    db.execute(
        text(
            "INSERT INTO sell_in_consumos VALUES ('ml', :s1, 5), ('ml', :s6, 1), ('ml', :s7, 7), ('fuera', :s2, 99);"
            "INSERT INTO sell_out_consumos VALUES (1, 'ml', :s1, 3, NULL), (2, 'ml', :s2, 0.01, 200), "
            "(1, 'tn', :s2, 50, NULL), (3, 'ml', :s3, 0.02, 200), (2, 'ml', :s4, 1, NULL)"
        ),
        {f"s{n}": ref for n, ref in refs.items()},
    )
    db.flush()
    if request.param == "persisted":
        lines = sale_lines(sqlite=False, queue=False, keyed=True, tp=True)
        db.execute(
            insert(MlSaleLine.__table__).from_select(
                list(STORED_COLUMNS), select(*(lines.c[n] for n in STORED_COLUMNS))
            )
        )
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        db.flush()
    return db


def _rows(db, f):
    with board.Board(db, f, scope_pairs=None) as b:
        return {row.key: row for row in b.page(None)}


def _d(value: str) -> Decimal:
    return Decimal(value)


@pytest.mark.postgres
class TestBoardSellInOut:
    def test_off_reports_no_sell_in_out_figure(self, catalog) -> None:
        row = _rows(catalog, OFF)["31"]

        assert (row.sell_in, row.sell_out, row.sell_out_pendientes, row.sell_out_estimados) == (None, None, None, None)
        assert (row.costo_sell_in, row.total_gauss_sell, row.markup_sell) == (None, None, None)

    def test_cost_total_and_markup_with_sell_in_and_sell_out(self, catalog) -> None:
        row = _rows(catalog, ON)["31"]

        assert (row.sell_in, row.sell_out) == (_d("5.00"), _d("5.00"))
        # The figures without them never change.
        assert (row.tg, row.costo) == (_d("20.00"), _d("100.00"))
        assert row.costo_sell_in == _d("95.00")
        assert row.total_gauss_sell == _d("30.00")
        assert row.markup_sell == _d("30") * 100 / _d("95")
        assert (row.sell_out_pendientes, row.sell_out_estimados) == (0, 0)

    def test_a_sell_out_without_its_rate_is_pending_and_an_estimated_rate_is_flagged(self, catalog) -> None:
        row = _rows(catalog, ON)["32"]

        assert row.sell_out == _d("4.00")
        assert (row.sell_out_pendientes, row.sell_out_estimados) == (1, 1)
        assert row.total_gauss_sell == _d("44.00")

    def test_a_row_without_sell_in_out_leaves_its_sell_figures_empty(self, catalog) -> None:
        # Owner: "en las filas que no aplica estaría bueno que directamente esté vacío así no hace ruido".
        row = _rows(catalog, ON)["33"]

        assert (row.sell_in_lineas, row.sell_out_lineas) == (0, 0)
        assert (row.costo_sell_in, row.total_gauss_sell, row.markup_sell) == (None, None, None)
        figures = sell_in_out_of(row)
        assert (figures.sell_in, figures.sell_out, figures.costo_sell_in) == (None, None, None)
        assert (figures.total_gauss, figures.markup_pct) == (None, None)
        # The cost is the row's own, not a sell in figure.
        assert figures.costo == 50.0

    def test_a_row_with_sell_out_only_leaves_its_sell_in_empty(self, catalog) -> None:
        row = _rows(catalog, ON)["32"]

        assert (row.sell_in_lineas, row.sell_out_lineas) == (0, 2)
        figures = sell_in_out_of(row)
        assert (figures.sell_in, figures.costo_sell_in) == (None, None)
        assert (figures.sell_out, figures.total_gauss) == (4.0, 44.0)

    def test_a_line_outside_the_markup_adds_to_total_gauss_only(self, catalog) -> None:
        row = _rows(catalog, ON)["34"]

        assert row.sell_in == _d("1.00")
        assert row.total_gauss_sell == _d("11.00")
        assert row.markup_sell is None

    def test_a_line_without_total_gauss_takes_no_sell_in_out(self, catalog) -> None:
        row = _rows(catalog, ON)["35"]

        # Its Total Gauss is not known yet (0 in Total Gauss): its sell in would read as profit without the sale's,
        # so the row has no sell in / sell out to show.
        assert (row.tg, row.sell_in, row.sell_in_lineas) == (_d("0"), _d("0"), 0)
        assert row.total_gauss_sell is None

    def test_sorts_by_total_gauss_with_sell_in_out(self, catalog) -> None:
        f = dataclasses.replace(ON, sort="total_gauss_sell", sort_desc=True)
        with board.Board(catalog, f, scope_pairs=None) as b:
            keys = [row.key for row in b.page(None)]

        assert keys == ["32", "31", "34", "33", "35"]

    def test_kpis_sum_the_rows(self, catalog) -> None:
        with board.Board(catalog, ON, scope_pairs=None) as b:
            k = b.kpis()

        assert (k.sell_in, k.sell_out) == (_d("6.00"), _d("9.00"))
        assert (k.sell_out_pendientes, k.sell_out_estimados) == (1, 1)
        assert (k.m_sell_in, k.m_sell_out) == (_d("5.00"), _d("9.00"))

    def test_the_group_view_sums_its_products(self, catalog) -> None:
        f = dataclasses.replace(ON, group_by="group", dimension="marca")
        with board.Board(catalog, f, scope_pairs=None) as b:
            nodes = {row.key: row for row in b.group_page(None)}

        tp = nodes["TP-LINK"]
        assert (tp.sell_in, tp.sell_out, tp.sell_out_pendientes) == (_d("5.00"), _d("9.00"), 1)
        assert tp.total_gauss_sell == _d("74.00")

    def test_costos_tp_leaves_the_markup_with_sell_in_out_unknown(self, catalog) -> None:
        f = dataclasses.replace(ON, costos_tp=True, tp_store_ids=TP_STORES)
        row = _rows(catalog, f)["31"]

        # Total Gauss never changes with "Costos TP"; the markup's cost basis does, so no mixed markup.
        assert row.total_gauss_sell == _d("30.00")
        assert (row.costo_sell_in, row.markup_sell) == (None, None)

    def test_costos_tp_refuses_the_markup_with_sell_in_out_sort(self, catalog) -> None:
        f = dataclasses.replace(ON, costos_tp=True, tp_store_ids=TP_STORES, sort="markup_sell")

        # The router answers 422 first; never a silent fallback to another order.
        with pytest.raises(ValueError, match="markup_sell"):
            _rows(catalog, f)


def test_a_sell_in_above_the_cost_leaves_the_markup_unknown_like_the_sort() -> None:
    row = board.Row(
        key="1",
        product_item_id=1,
        mla=None,
        tg=_d("10"),
        mtg=_d("10"),
        costo=_d("5"),
        sell_in=_d("8"),
        sell_out=_d("0"),
        sell_in_lineas=1,
    )
    row.m_sell_in, row.m_sell_out = _d("8"), _d("0")

    assert row.costo_sell_in == _d("-3")
    assert row.markup_sell is None


@pytest.fixture(params=["live", "persisted"])
def zero_tg(request, board_pg, monkeypatch):
    """36: one sale whose Total Gauss is resolved and exactly 0 (tg0/c50), with a sell in of $4 and an ARS sell out
    of $2. A known 0 is not an unknown Total Gauss: its sell in / sell out count."""
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (36, 'S36', 'Antena', 'TP-Link', 'Redes', 1, 1);"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true);"
            "INSERT INTO tb_mercadolibre_items_publicados "
            "(mlp_id, mlp_publicationid, item_id, mlp_official_store_id) VALUES (9136, 'MLA936', 36, 57997)"
        )
    )
    order_id = 2000012345679036
    _order(db, order_id, [(36, "MLA936", 1, Decimal("50"))], tg="0", costo="50")
    _group(db, f"o:{order_id}", [order_id], NOW - timedelta(hours=3))
    ref = _line(db, order_id)
    db.execute(text(CONSUMPTION_DDL))
    db.execute(
        text(
            "INSERT INTO sell_in_consumos VALUES ('ml', :s, 4); INSERT INTO sell_out_consumos VALUES (1, 'ml', :s, 2, NULL)"
        ),
        {"s": ref},
    )
    db.flush()
    if request.param == "persisted":
        lines = sale_lines(sqlite=False, queue=False, keyed=True, tp=True)
        db.execute(
            insert(MlSaleLine.__table__).from_select(
                list(STORED_COLUMNS), select(*(lines.c[n] for n in STORED_COLUMNS))
            )
        )
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        db.flush()
    return db


def test_a_sale_with_a_total_gauss_of_exactly_zero_adds_its_sell_in_out(zero_tg) -> None:
    # Audit A3: "a sale with Total Gauss exactly 0 must add to sell in/out".
    row = _rows(zero_tg, ON)["36"]

    assert row.tg == _d("0")
    assert (row.sell_in, row.sell_out, row.sell_in_lineas, row.sell_out_lineas) == (_d("4.00"), _d("2.00"), 1, 1)
    assert row.total_gauss_sell == _d("6.00")


def test_a_known_zero_being_recalculated_takes_no_sell_in_out(zero_tg) -> None:
    # Queued for a recompute, its stored Total Gauss is stale: unknown again until the drain rewrites it.
    zero_tg.add(MlOrderMetricsDirty(order_id=2000012345679036, version=1, reason="test", attempts=0))
    zero_tg.flush()

    row = _rows(zero_tg, ON)["36"]

    assert (row.tg, row.sell_in, row.sell_in_lineas) == (_d("0"), _d("0"), 0)
    assert row.total_gauss_sell is None
