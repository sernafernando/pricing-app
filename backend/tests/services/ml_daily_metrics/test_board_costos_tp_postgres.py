"""metricas-ml-tplink-mode P4 on real Postgres: the board's `costos_tp` toggle.

With the toggle ON, the operations of the TP store group (the publication's
CURRENT store, one of `BoardFilter.tp_store_ids`) take the TP cost: their
markup is Markup TP (Total TP / TP cost) and Total TP is reported NEXT TO Total
Gauss, which never changes. Every other store's operations are untouched. A
TP operation without a TP cost is counted as incomplete, never read as 0.

Both line sources are covered: the live derivation and the persisted
`ml_sale_lines` (behind `METRICAS_SALE_LINES_ENABLED`).
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
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.order_metrics.sale_lines_store import STORED_COLUMNS
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
TP_STORES = (2645, 471846)
QUEUED_ORDER = 2000012345678905
UNRESOLVED_ORDER = 2000012345678908
NO_METRICS_ORDER = 2000012345678909
OFF = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)
ON = dataclasses.replace(OFF, costos_tp=True, tp_store_ids=TP_STORES)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture(params=["live", "persisted"])
def catalog(request, board_pg, monkeypatch):
    """21: A21 in Gauss 57997 (tg10/c50) and B21 in TP 2645 (tg20/c100, TP cost 80, Total TP 40).
    22: C22 in TP 471846 (tg90/c100) WITHOUT a TP cost: Total TP incomplete.
    23: D23 in Gauss (tg10/c50); it also has a TP cost, which must be ignored there.
    24: E24 in TP 471846 (tg25/c100, TP cost 70, Total TP 55), its only order QUEUED for a recompute.
    25: F25 in TP 471846, its Total Gauss UNRESOLVED (TP cost known): Total TP needs Total Gauss, so unknown.
    26: G26 in TP 471846, its metrics NEVER computed: Total TP unknown too.
    Comparison period (40 days ago), product 21: A21 (tg10/c50) and B21 (tg40/c100, TP cost 130, Total TP 10)."""
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (21, 'S21', 'Router', 'TP-Link', 'Redes', 1, 1), (22, 'S22', 'Switch', 'TP-Link', 'Redes', 1, 1), "
            "(23, 'S23', 'Impresora', 'Epson', 'Impresoras', 2, 1), (24, 'S24', 'AP', 'TP-Link', 'Redes', 1, 1), "
            "(25, 'S25', 'Mesh', 'TP-Link', 'Redes', 1, 1), (26, 'S26', 'Cam', 'TP-Link', 'Redes', 1, 1);"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true), (2645, 'TP-Link vieja', 'tplink', 2, false), "
            "(471846, 'TP-Link', 'tplink', 3, true)"
        )
    )
    recent, before = timedelta(hours=3), timedelta(days=40)
    sales = (
        (1, 21, "MLA9000000021", 57997, "10", "50", None, None, recent),
        (2, 21, "MLA9000000121", 2645, "20", "100", "80", "40", recent),
        (3, 22, "MLA9000000022", 471846, "90", "100", None, None, recent),
        (4, 23, "MLA9000000023", 57997, "10", "50", "30", "30", recent),
        (5, 24, "MLA9000000024", 471846, "25", "100", "70", "55", recent),
        (6, 21, "MLA9000000021", 57997, "10", "50", None, None, before),
        (7, 21, "MLA9000000121", 2645, "40", "100", "130", "10", before),
        (8, 25, "MLA9000000025", 471846, "15", "100", "20", None, recent),
        (9, 26, "MLA9000000026", 471846, "15", "100", "20", "35", recent),
    )
    published = set()
    for n, product, mla, store, tg, costo, costo_tp, total_tp, ago in sales:
        if mla not in published:
            published.add(mla)
            db.execute(
                text(
                    "INSERT INTO tb_mercadolibre_items_publicados "
                    "(mlp_id, mlp_publicationid, item_id, mlp_official_store_id) VALUES (:id, :mla, :item, :store)"
                ),
                {"id": 9000 + n, "mla": mla, "item": product, "store": store},
            )
        order_id = 2000012345678900 + n
        _order(db, order_id, [(product, mla, 1, Decimal(costo))], tg=tg, costo=costo)
        db.execute(
            text("UPDATE ml_order_metrics SET costo_tp = :c, total_tp = :t, tp_incompleto = :i WHERE order_id = :o"),
            {"c": costo_tp, "t": total_tp, "i": costo_tp is None, "o": order_id},
        )
        _group(db, f"o:{order_id}", [order_id], NOW - ago)
    db.execute(
        text("UPDATE ml_order_metrics SET gauss_status = 'unresolved', total_gauss = NULL WHERE order_id = :o"),
        {"o": UNRESOLVED_ORDER},
    )
    db.execute(text("DELETE FROM ml_order_metrics WHERE order_id = :o"), {"o": NO_METRICS_ORDER})
    db.flush()
    if request.param == "persisted":
        lines = sale_lines(sqlite=False, queue=False, keyed=True, tp=True)
        db.execute(
            insert(MlSaleLine.__table__).from_select(
                list(STORED_COLUMNS), select(*(lines.c[n] for n in STORED_COLUMNS))
            )
        )
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
    db.add(MlOrderMetricsDirty(order_id=QUEUED_ORDER, version=1, reason="test", attempts=0))
    db.flush()
    return db


def _rows(db, f):
    with board.Board(db, f, scope_pairs=None) as b:
        return {row.key: row for row in b.page(None)}


def _d(value: str) -> Decimal:
    return Decimal(value)


@pytest.mark.postgres
class TestCostosTp:
    def test_off_reports_no_tp_figure_and_keeps_the_gauss_markup(self, catalog) -> None:
        rows = _rows(catalog, OFF)

        assert rows["21"].total_tp is None and rows["21"].tp_incompletos is None
        assert rows["21"].markup == _d("30") * 100 / _d("150")

    def test_on_tp_operations_take_the_tp_cost_and_others_keep_theirs(self, catalog) -> None:
        rows = _rows(catalog, ON)

        r21, r22, r23 = rows["21"], rows["22"], rows["23"]
        # Total Gauss never changes.
        assert (r21.tg, r22.tg, r23.tg) == (_d("30.00"), _d("90.00"), _d("10.00"))
        # Product 21: Gauss pair (10 / 50) + TP pair with Markup TP (40 / 80).
        assert (r21.mtg, r21.costo) == (_d("50.00"), _d("130.00"))
        assert r21.total_tp == _d("40.00") and r21.tp_incompletos == 0
        # Product 22: TP pair without a TP cost: no markup, no Total TP, flagged -- never 0, never the Gauss cost.
        assert (r22.mtg, r22.costo, r22.markup) == (_d("0.00"), _d("0.00"), None)
        assert r22.total_tp is None and r22.tp_incompletos == 1
        # Product 23 sells only in Gauss: its own TP cost is ignored.
        assert (r23.mtg, r23.costo) == (_d("10.00"), _d("50.00"))
        assert r23.total_tp is None and r23.tp_incompletos == 0

    def test_a_queued_tp_order_is_incomplete_never_zero(self, catalog) -> None:
        # Being recalculated, its Total TP is unknown: NULL and counted, like a missing TP cost.
        r24 = _rows(catalog, ON)["24"]

        assert (r24.tg, r24.mtg, r24.costo) == (_d("0.00"), _d("0.00"), _d("0.00"))
        assert (r24.total_tp, r24.tp_incompletos) == (None, 1)

    @pytest.mark.parametrize("product", ["25", "26"])
    def test_without_total_gauss_total_tp_is_incomplete_never_zero(self, catalog, product) -> None:
        # 25: Total Gauss unresolved; 26: metrics never computed. Total TP needs Total Gauss: unknown.
        row = _rows(catalog, ON)[product]

        assert (row.tg, row.mtg, row.costo) == (_d("0.00"), _d("0.00"), _d("0.00"))
        assert (row.total_tp, row.tp_incompletos) == (None, 1)

    def test_the_comparison_period_switches_to_markup_tp_too(self, catalog) -> None:
        off, on = _rows(catalog, OFF)["21"], _rows(catalog, ON)["21"]

        # OFF: 30/150 now vs 50/150 before -- falling.
        assert (off.prev_mtg, off.prev_costo) == (_d("50.00"), _d("150.00"))
        assert off.markup_delta == _d("20") - _d("50") * 100 / _d("150")
        assert "margen_cayendo" in off.flags
        # ON: (10 + 40)/(50 + 80) now vs (10 + 10)/(50 + 130) before, both with the TP cost -- rising.
        assert (on.prev_mtg, on.prev_costo) == (_d("20.00"), _d("180.00"))
        assert on.markup_prev == _d("20") * 100 / _d("180")
        assert on.markup_delta == _d("50") * 100 / _d("130") - _d("20") * 100 / _d("180")
        assert "margen_cayendo" not in on.flags

    def test_kpis_add_total_tp_and_the_incomplete_count(self, catalog) -> None:
        with board.Board(catalog, ON, scope_pairs=None) as b:
            on = b.kpis()
        with board.Board(catalog, OFF, scope_pairs=None) as b:
            off = b.kpis()

        assert on.tg == off.tg == _d("130.00")
        # 24 (queued), 25 (Gauss unresolved) and 26 (no metrics) are incomplete too.
        assert (on.total_tp, on.tp_incompletos) == (_d("40.00"), 4)
        assert (on.mtg, on.costo) == (_d("60.00"), _d("180.00"))
        assert (off.total_tp, off.tp_incompletos) == (None, None)

    def test_the_tienda_group_carries_total_tp_per_group(self, catalog) -> None:
        f = dataclasses.replace(ON, group_by="group", dimension="tienda")
        with board.Board(catalog, f, scope_pairs=None) as b:
            groups = {row.key: row for row in b.group_page(None)}

        tp, gauss = groups["c:tplink"], groups["s:57997"]
        assert (tp.total_tp, tp.tp_incompletos, tp.markup) == (_d("40.00"), 4, _d("50"))
        assert (gauss.total_tp, gauss.tp_incompletos) == (None, 0)

    def test_the_csv_leaves_carry_total_tp(self, catalog) -> None:
        f = dataclasses.replace(ON, group_by="group", dimension="tienda")
        with board.Board(catalog, f, through_leaves=True, scope_pairs=None) as b:
            leaves = b.leaves_for_keys(b.leaf_keys(50))

        # The tienda tree's first level is the store; the leaf is the product under it.
        with_tp = {(leaf.path[0], leaf.key): (leaf.total_tp, leaf.tp_incompletos) for leaf in leaves}
        assert with_tp[("TP-Link", "21")] == (_d("40.00"), 0)
        assert with_tp[("TP-Link", "22")] == (None, 1)
        assert with_tp[("Gauss", "21")] == (None, 0)

    def test_on_needs_the_tp_store_ids(self) -> None:
        with pytest.raises(ValueError):
            dataclasses.replace(OFF, costos_tp=True)
