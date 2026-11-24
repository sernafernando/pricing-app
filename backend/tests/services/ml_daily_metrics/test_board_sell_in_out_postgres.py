"""sell-in-sell-out T11 on real Postgres: the board's sell out figures.

Sell out is a credit added to profit. Each sold line takes what the allocator wrote for it (`sell_out_consumos`,
canal 'ml', `venta_ref` = the line's `item_row_id`), converted to ARS like the sell-out screen (`resumen.ARS_FILA`).
A line whose USD sell out has no rate yet is counted as pending, never read as 0; one whose campaign rate is still an
estimate is counted as estimated.

With `BoardFilter.sell_in_out` OFF the board reports none of it. Both line sources are covered.

Costo SI T3 D1 (owner L12): "el costo siso no existe, es costo SI y SO va en la venta, como ganancia adicional, si de
ganancia tenés 1000 y le agregás 10% tenés 1100 de ganancia". Every sell figure is `board.ConSo`: total c/ SO = Total
Gauss + sell out, markup c/ SO = `so.markup_con_so(limpio, sell out, costo)`; the keys `total_gauss_sell` /
`markup_sell` are those figures and their SQL sorts order by them. Costo SI T5 PR B (owner L24: "no podemos
descontarselo dos veces"): the costo SI already holds the sell in through its invoices, so the board has no sell in
at all -- the stored `sell_in_consumos` / `sell_in_bono_consumos` rows below are there to prove it never reads them.

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
from app.services.costo_si import so
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import SellInOutFigures, sell_in_out_of
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
    # The % of cost bonuses' per-sale sell in (T25): stored rows the board never reads (PR B, L24).
    "CREATE TEMP TABLE sell_in_bono_consumos (canal VARCHAR(8), venta_ref BIGINT, descuento_ars NUMERIC(18, 2), "
    "bono_id BIGINT) ON COMMIT DROP;"
    "CREATE TEMP TABLE sell_out_campanas (id BIGINT PRIMARY KEY, moneda VARCHAR(3), tc_modo VARCHAR(12), "
    "tipo_cambio NUMERIC(18, 6), tipo VARCHAR(16) DEFAULT 'por_unidad', estado VARCHAR(16) DEFAULT 'activa', "
    "fecha_hasta DATE DEFAULT '2026-09-30') ON COMMIT DROP;"
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
    """31: two sales of MLA931 (tg10/c50 each). Sale 1: a stored sell in of $5 (never read) and an ARS sell out of $3. Sale 2: a USD sell
    out of 0.01 at a known rate of 200 ($2) on campaign 2, and the same sale is also in another channel's
    consumption (never counted).
    32: one sale (tg20/c100) with an al_cobro USD sell out whose rate is an estimate ($4: 0.02 at 200) and one
    (tg20/c100) with a USD sell out without its rate yet: pending, never 0.
    33: one sale (tg10/c50) with no sell in nor sell out.
    34: one sale whose markup is unknown (cost 0) with only a stored sell in of $1: no sell figure.
    35: one sale whose Total Gauss is not resolved yet with only a stored sell in of $7: no sell figure."""
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
    def test_off_reports_no_sell_out_figure(self, catalog) -> None:
        row = _rows(catalog, OFF)["31"]

        assert (row.sell_out, row.sell_out_pendientes, row.sell_out_estimados) == (None, None, None)
        assert (row.total_gauss_sell, row.markup_sell) == (None, None)

    def test_total_and_markup_sell_are_the_figures_c_so(self, catalog) -> None:
        row = _rows(catalog, ON)["31"]

        # The stored $5 sell in of sale 1 is never read: the frozen cost is costo SI, which already holds it.
        assert row.sell_out == _d("5.00")
        # The figures without sell out never change.
        assert (row.tg, row.costo) == (_d("20.00"), _d("100.00"))
        assert row.total_gauss_sell == _d("25.00") == row.total_gauss_so
        assert row.markup_sell == _d("25") == row.markup_so
        assert (row.sell_out_pendientes, row.sell_out_estimados) == (0, 0)

    def test_a_sell_out_without_its_rate_is_pending_and_an_estimated_rate_is_flagged(self, catalog) -> None:
        row = _rows(catalog, ON)["32"]

        assert row.sell_out == _d("4.00")
        assert (row.sell_out_pendientes, row.sell_out_estimados) == (1, 1)
        assert row.total_gauss_sell == _d("44.00")

    def test_a_row_without_sell_out_leaves_its_sell_figures_empty(self, catalog) -> None:
        # Owner: "en las filas que no aplica estaría bueno que directamente esté vacío así no hace ruido".
        row = _rows(catalog, ON)["33"]

        assert row.sell_out_lineas == 0
        assert (row.total_gauss_sell, row.markup_sell) == (None, None)
        figures = sell_in_out_of(row)
        assert figures.sell_out is None
        assert (figures.total_gauss, figures.markup_pct) == (None, None)
        # The cost is the row's own.
        assert figures.costo == 50.0

    def test_a_row_with_sell_out_counts_its_lines(self, catalog) -> None:
        row = _rows(catalog, ON)["32"]

        assert row.sell_out_lineas == 2
        figures = sell_in_out_of(row)
        assert (figures.sell_out, figures.total_gauss) == (4.0, 44.0)

    @pytest.mark.parametrize("key", ["34", "35"])
    def test_a_sale_with_only_a_stored_sell_in_has_no_sell_figure(self, catalog, key) -> None:
        row = _rows(catalog, ON)[key]

        assert (row.sell_out, row.sell_out_lineas) == (_d("0"), 0)
        assert (row.total_gauss_sell, row.markup_sell) == (None, None)

    def test_sorts_by_total_gauss_with_sell_out(self, catalog) -> None:
        # D1: Total Gauss + sell out (32: 44, 31: 25); 34 and 35 only have a stored sell in, so no figure: last.
        f = dataclasses.replace(ON, sort="total_gauss_sell", sort_desc=True)
        with board.Board(catalog, f, scope_pairs=None) as b:
            keys = [row.key for row in b.page(None)]

        assert keys[:2] == ["32", "31"]
        assert set(keys[2:]) == {"33", "34", "35"}

    @pytest.mark.parametrize(
        "sort,filled",
        [
            # 33 has no sell line and 34/35 only a stored sell in (never read): each shows an empty cell in that
            # column, so it sorts last, like any blank column (Stock, Total TP).
            ("total_gauss_sell", ["31", "32"]),
            ("markup_sell", ["32", "31"]),
            ("sell_out", ["32", "31"]),
        ],
    )
    def test_a_row_with_an_empty_sell_cell_sorts_last_ascending(self, catalog, sort, filled) -> None:
        f = dataclasses.replace(ON, sort=sort, sort_desc=False)
        with board.Board(catalog, f, scope_pairs=None) as b:
            keys = [row.key for row in b.page(None)]

        assert keys[: len(filled)] == filled
        assert set(keys[len(filled) :]) == {"31", "32", "33", "34", "35"} - set(filled)

    @pytest.mark.parametrize("sort", ["total_gauss_sell", "markup_sell"])
    @pytest.mark.parametrize("descending", [True, False])
    def test_the_sql_sort_orders_like_the_row_property(self, catalog, sort, descending) -> None:
        # The SQL sort key and the Python property of the same name are one figure (`_sell_sort_columns`).
        f = dataclasses.replace(ON, sort=sort, sort_desc=descending)
        with board.Board(catalog, f, scope_pairs=None) as b:
            rows = b.page(None)

        values = [getattr(row, sort) for row in rows]
        filled = [v for v in values if v is not None]
        assert len(filled) == 2 and values[:2] == filled
        assert filled == sorted(filled, reverse=descending)

    def test_kpis_sum_the_rows(self, catalog) -> None:
        with board.Board(catalog, ON, scope_pairs=None) as b:
            k = b.kpis()

        assert k.sell_out == _d("9.00")
        assert (k.sell_out_pendientes, k.sell_out_estimados) == (1, 1)
        assert k.m_sell_out == _d("9.00")
        assert k.total_gauss_sell == k.tg + _d("9.00") == k.total_gauss_so
        assert k.markup_sell == k.markup_so

    def test_the_group_view_sums_its_products(self, catalog) -> None:
        f = dataclasses.replace(ON, group_by="group", dimension="marca")
        with board.Board(catalog, f, scope_pairs=None) as b:
            nodes = {row.key: row for row in b.group_page(None)}

        tp = nodes["TP-LINK"]
        assert (tp.sell_out, tp.sell_out_pendientes) == (_d("9.00"), 1)
        # 60 of Total Gauss plus 9 of sell out; the stored $5 sell in of 31 is not read.
        assert tp.total_gauss_sell == _d("69.00")

    def test_costos_tp_leaves_the_markup_sell_unknown(self, catalog) -> None:
        f = dataclasses.replace(ON, costos_tp=True, tp_store_ids=TP_STORES)
        row = _rows(catalog, f)["31"]

        # Total Gauss never changes with "Costos TP"; the markup's cost basis does, so no mixed markup.
        assert row.total_gauss_sell == _d("25.00")
        assert row.markup_sell is None

    def test_costos_tp_refuses_the_markup_sell_sort(self, catalog) -> None:
        f = dataclasses.replace(ON, costos_tp=True, tp_store_ids=TP_STORES, sort="markup_sell")

        # The router answers 422 first; never a silent fallback to another order.
        with pytest.raises(ValueError, match="markup_sell"):
            _rows(catalog, f)

    def test_sums_by_carries_no_sell_in(self, catalog) -> None:
        with board.Board(catalog, dataclasses.replace(ON, group_by="publication"), scope_pairs=None) as b:
            sums = b.sums_by([("g", "MLA931", Decimal(1))])

        assert (sums["g"]["sell_out"], sums["g"]["sell_out_lineas"]) == (_d("5.00"), 2)
        assert not {name for name in sums["g"] if "sell_in" in name}


SELL_IN_FIELDS = {"sell_in", "m_sell_in", "sell_in_estimados", "sell_in_lineas", "costo_sell_in"}


def test_the_board_has_no_sell_in_figure() -> None:
    # PR B (L24): no per-sale sell in on top of costo SI, so neither the rows nor the KPIs carry one.
    for cls in (board.Row, board.Kpis):
        names = {f.name for f in dataclasses.fields(cls)} | {n for n in vars(cls) if not n.startswith("_")}
        assert not names & SELL_IN_FIELDS, cls
    assert not hasattr(board, "SellInOut")
    assert not hasattr(board, "bonos_costo")


@pytest.fixture(params=["live", "persisted"])
def zero_tg(request, board_pg, monkeypatch):
    """36: one sale whose Total Gauss is resolved and exactly 0 (tg0/c50), with a stored sell in of $4 (never read)
    and an ARS sell out of $2. A known 0 is not an unknown Total Gauss: its sell out counts."""
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


def test_a_sale_with_a_total_gauss_of_exactly_zero_adds_its_sell_out(zero_tg) -> None:
    # Audit A3: "a sale with Total Gauss exactly 0 must add to sell in/out"; the sell in is gone (PR B).
    row = _rows(zero_tg, ON)["36"]

    assert row.tg == _d("0")
    assert (row.sell_out, row.sell_out_lineas) == (_d("2.00"), 1)
    assert row.total_gauss_sell == _d("2.00")


def test_a_known_zero_being_recalculated_takes_no_sell_out(zero_tg) -> None:
    # Queued for a recompute, its stored Total Gauss is stale: unknown again until the drain rewrites it.
    zero_tg.add(MlOrderMetricsDirty(order_id=2000012345679036, version=1, reason="test", attempts=0))
    zero_tg.flush()

    row = _rows(zero_tg, ON)["36"]

    assert (row.tg, row.sell_out, row.sell_out_lineas) == (_d("0"), _d("0"), 0)
    assert row.total_gauss_sell is None


@pytest.fixture(params=["live", "persisted"])
def cost_bonus(request, board_pg, monkeypatch):
    """T25 (S31): a % of cost bonus's per-sale sell in (`sell_in_bono_consumos`), stored but never read (PR B, L24).
    37: one sale (tg10/c50) whose only sell in is a cost bonus of $6 (and a fuera row of the same ref, never counted).
    38: one sale (tg10/c50) with an invoice sell in of $5 and a cost bonus sell in of $2 on its other units."""
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (37, 'S37', 'Antena', 'TP-Link', 'Redes', 1, 1), (38, 'S38', 'Repetidor', 'TP-Link', 'Redes', 1, 1);"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true);"
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, mlp_official_store_id) "
            "VALUES (9137, 'MLA937', 37, 57997), (9138, 'MLA938', 38, 57997)"
        )
    )
    refs = {}
    for product in (37, 38):
        order_id = 2000012345679000 + product
        _order(db, order_id, [(product, f"MLA9{product}", 1, Decimal("50"))], tg="10", costo="50")
        _group(db, f"o:{order_id}", [order_id], NOW - timedelta(hours=3))
        refs[product] = _line(db, order_id)
    db.execute(text(CONSUMPTION_DDL))
    db.execute(
        text(
            "INSERT INTO sell_in_bono_consumos VALUES ('ml', :s37, 6), ('fuera', :s37, 99), ('ml', :s38, 2);"
            "INSERT INTO sell_in_consumos VALUES ('ml', :s38, 5)"
        ),
        {"s37": refs[37], "s38": refs[38]},
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


@pytest.fixture(params=["live", "persisted"])
def negative_cost(request, board_pg, monkeypatch):
    """41: tg20/c100 with an ARS sell out of $5. 42: tg10 on a NEGATIVE cost (-50) with a sell out of $3. 43: tg4/c40
    with a sell out of $2. The SQL sort `markup_sell` guards only `costo != 0`, like `so.markup_con_so`."""
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (41, 'S41', 'Router', 'TP-Link', 'Redes', 1, 1), (42, 'S42', 'Switch', 'TP-Link', 'Redes', 1, 1), "
            "(43, 'S43', 'Hub', 'TP-Link', 'Redes', 1, 1);"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true);"
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, mlp_official_store_id) "
            "VALUES (9141, 'MLA941', 41, 57997), (9142, 'MLA942', 42, 57997), (9143, 'MLA943', 43, 57997)"
        )
    )
    refs = {}
    for product, tg, costo in ((41, "20", "100"), (42, "10", "-50"), (43, "4", "40")):
        order_id = 2000012345679000 + product
        _order(db, order_id, [(product, f"MLA9{product}", 1, Decimal(costo))], tg=tg, costo=costo)
        _group(db, f"o:{order_id}", [order_id], NOW - timedelta(hours=3))
        refs[product] = _line(db, order_id)
    db.execute(text(CONSUMPTION_DDL))
    db.execute(
        text(
            "INSERT INTO sell_out_consumos VALUES (1, 'ml', :s41, 5, NULL), (1, 'ml', :s42, 3, NULL), (1, 'ml', :s43, 2, NULL)"
        ),
        {"s41": refs[41], "s42": refs[42], "s43": refs[43]},
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


@pytest.mark.postgres
@pytest.mark.parametrize("descending", [True, False])
def test_the_markup_sort_follows_the_row_value_on_a_negative_cost(negative_cost, descending) -> None:
    f = dataclasses.replace(ON, sort="markup_sell", sort_desc=descending)
    with board.Board(negative_cost, f, scope_pairs=None) as b:
        rows = b.page(None)

    assert {row.key for row in rows} == {"41", "42", "43"}
    assert all(row.markup_so is not None and row.markup_so == _markup_con_so(row) for row in rows)
    values = [row.markup_so for row in rows]
    assert values == sorted(values, reverse=descending)


@pytest.mark.postgres
class TestCostBonusesAreIgnored:
    @pytest.mark.parametrize("key", ["37", "38"])
    def test_a_sale_with_only_a_stored_sell_in_has_no_sell_figure(self, cost_bonus, key) -> None:
        row = _rows(cost_bonus, ON)[key]

        assert (row.tg, row.costo) == (_d("10.00"), _d("50.00"))
        assert (row.total_gauss_sell, row.markup_sell) == (None, None)
        figures = sell_in_out_of(row)
        assert (figures.sell_out, figures.total_gauss, figures.markup_pct) == (None, None, None)

    def test_the_kpis_have_no_sell_figure(self, cost_bonus) -> None:
        with board.Board(cost_bonus, ON, scope_pairs=None) as b:
            k = b.kpis()

        assert (k.total_gauss_sell, k.markup_sell) == (None, None)
        assert sell_in_out_of(k).total_gauss is None


# Costo SI T3 D1: what Métricas ML shows. No sell in figure reaches its payload, and the figures c/ SO add the sell out
# to the profit, never take it off the cost.
SELL_IN_KEYS = ("sell_in", "sell_in_estimados", "costo_sell_in")


def _markup_con_so(row) -> Decimal:
    """The row's markup c/ SO by the one shared rule: `limpio` = its markup profit plus its cost."""
    return so.markup_con_so(row.mtg + row.costo, row.m_sell_out, row.costo) * 100


@pytest.mark.postgres
class TestConSo:
    def test_the_payload_carries_no_sell_in_figure(self, catalog) -> None:
        for name in SELL_IN_KEYS:
            assert name not in SellInOutFigures.model_fields, name
        assert "sell_in" not in board.SORTS

    def test_cost_is_the_frozen_cost_and_sell_out_adds_to_profit(self, catalog) -> None:
        row = _rows(catalog, ON)["31"]

        # The $5 sell in of sale 1 is not read: the frozen cost is costo SI already.
        assert (row.tg, row.costo, row.sell_out) == (_d("20.00"), _d("100.00"), _d("5.00"))
        assert row.total_gauss_so == _d("25.00")
        assert row.markup_so == _d("25") == _markup_con_so(row)
        figures = sell_in_out_of(row)
        assert (figures.costo, figures.sell_out, figures.total_gauss, figures.markup_pct) == (100.0, 5.0, 25.0, 25.0)
        assert (figures.sell_out_pendientes, figures.sell_out_estimados) == (0, 0)

    def test_a_pending_sell_out_still_shows_the_total_c_so(self, catalog) -> None:
        row = _rows(catalog, ON)["32"]

        assert row.total_gauss_so == _d("44.00")
        assert row.markup_so == _d("44") * 100 / _d("200") == _markup_con_so(row)

    def test_a_sale_with_a_sell_in_only_has_no_figure_c_so(self, catalog) -> None:
        rows = _rows(catalog, ON)

        for key in ("33", "34", "35"):
            assert (rows[key].total_gauss_so, rows[key].markup_so) == (None, None), key
            figures = sell_in_out_of(rows[key])
            assert (figures.sell_out, figures.total_gauss, figures.markup_pct) == (None, None, None), key

    @pytest.mark.parametrize("descending", [True, False])
    def test_the_markup_sort_follows_the_row_value(self, catalog, descending) -> None:
        # One formula: the SQL sort key `markup_sell` and the row's `markup_so` (`so.markup_con_so`) order alike.
        f = dataclasses.replace(ON, sort="markup_sell", sort_desc=descending)
        with board.Board(catalog, f, scope_pairs=None) as b:
            rows = b.page(None)

        values = [row.markup_so for row in rows if row.markup_so is not None]
        assert [row.key for row in rows][: len(values)] == (["31", "32"] if descending else ["32", "31"])
        assert values == sorted(values, reverse=descending)
        assert all(row.markup_so == _markup_con_so(row) for row in rows if row.markup_so is not None)

    @pytest.mark.parametrize("descending", [True, False])
    def test_the_total_sort_follows_the_row_value(self, catalog, descending) -> None:
        f = dataclasses.replace(ON, sort="total_gauss_sell", sort_desc=descending)
        with board.Board(catalog, f, scope_pairs=None) as b:
            rows = b.page(None)

        values = [row.total_gauss_so for row in rows if row.total_gauss_so is not None]
        assert len(values) == 2 and values == sorted(values, reverse=descending)

    def test_kpis_sum_the_rows(self, catalog) -> None:
        with board.Board(catalog, ON, scope_pairs=None) as b:
            k = b.kpis()

        assert k.total_gauss_so == k.tg + _d("9.00")
        assert k.markup_so == _markup_con_so(k)

    def test_the_group_view_sums_its_products(self, catalog) -> None:
        f = dataclasses.replace(ON, group_by="group", dimension="marca")
        with board.Board(catalog, f, scope_pairs=None) as b:
            nodes = {row.key: row for row in b.group_page(None)}

        # 60 of Total Gauss plus 9 of sell out; the $5 sell in of 31 is not read.
        assert nodes["TP-LINK"].total_gauss_so == _d("69.00")

    def test_costos_tp_leaves_the_markup_c_so_unknown(self, catalog) -> None:
        f = dataclasses.replace(ON, costos_tp=True, tp_store_ids=TP_STORES)
        row = _rows(catalog, f)["31"]

        assert row.total_gauss_so == _d("25.00")
        assert row.markup_so is None
        assert sell_in_out_of(row).markup_pct is None


def test_the_sell_out_is_never_taken_off_the_cost() -> None:
    # D1's own example: a profit of 1000 on a cost of 1000 plus a sell out of 100 is 1100 of profit, 110%.
    row = board.Row(key="1", product_item_id=1, mla=None, tg=_d("1000"), mtg=_d("1000"), costo=_d("1000"))
    row.sell_out, row.m_sell_out, row.sell_out_lineas = _d("100"), _d("100"), 1

    assert row.total_gauss_so == row.total_gauss_sell == _d("1100")
    assert row.markup_so == row.markup_sell == _d("110")


def test_a_zero_cost_leaves_the_markup_c_so_unknown() -> None:
    row = board.Row(key="1", product_item_id=1, mla=None, tg=_d("10"), mtg=_d("0"), costo=_d("0"))
    row.sell_out, row.m_sell_out, row.sell_out_lineas = _d("3"), _d("0"), 1

    assert row.total_gauss_so == _d("13")
    assert row.markup_so is None


def test_a_sale_with_a_total_gauss_of_exactly_zero_adds_its_sell_out_c_so(zero_tg) -> None:
    row = _rows(zero_tg, ON)["36"]

    assert row.total_gauss_so == _d("2.00")
