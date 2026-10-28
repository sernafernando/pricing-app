"""Métricas ML audit B1a -- the KPI strip's "Operaciones", "Ticket promedio" and "Unids/Venta".

An operation is a pack, or a lone order, with a sale on the board in the period: the same sold lines that make up
Facturado and Unidades (a cancellation ML did not cover is no sale), each pack counted once however many of its
products or orders sell. Under a filter it counts the operations with a sold line of a row that survives it, so
"Ticket promedio" (Facturado / Operaciones) and "Unids/Venta" (Unidades / Operaciones) divide figures of the same
lines.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, text

from app.core.config import settings
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import build_board_kpis
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.order_metrics.sale_lines_store import STORED_COLUMNS
from tests.services.ml_daily_metrics.test_board_postgres import MLA, NOW, OTHER, TODAY, _group, _order

pytestmark = pytest.mark.postgres

PERIOD = {"date_from": TODAY - timedelta(days=29), "date_to": TODAY}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture(params=["live", "persisted"])
def sales(request, board_pg, monkeypatch):
    """777 (TP-Link, MLA) and 778 (Logi, OTHER), every unit at $100.
    Period: lone order A (777 x2), lone order C (777 x7, 02:55 UTC on Sep 28 = Sep 27 in Buenos Aires), and pack P
    with order 914 (777 x1 + 778 x2) and order 915 (778 x1): 3 operations, 13 units, $1300. A cancellation ML did
    not cover (777 x5) is no sale. Comparison period: one lone order of 777 x1."""
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (777, 'P777', 'Router', 'TP-Link', 'Redes', 1, 1), (778, 'P778', 'Mouse', 'Logi', 'Perif', 2, 1)"
        )
    )
    _order(db, 2000012345678911, [(777, MLA, 2, 10)])
    _group(db, "o:2000012345678911", [2000012345678911], NOW - timedelta(hours=3))
    _order(db, 2000012345678912, [(777, MLA, 5, 10)], status="cancelled")
    _group(db, "o:2000012345678912", [2000012345678912], NOW - timedelta(hours=1))
    _order(db, 2000012345678913, [(777, MLA, 7, 10)])
    _group(db, "o:2000012345678913", [2000012345678913], datetime(2026, 9, 28, 2, 55, tzinfo=timezone.utc))
    pack = 2000009999999999
    _order(db, 2000012345678914, [(777, MLA, 1, 300), (778, OTHER, 2, 50)], pack_id=pack, tg="80", costo="400")
    _order(db, 2000012345678915, [(778, OTHER, 1, 50)], pack_id=pack, tg="5", costo="50")
    _group(db, f"p:{pack}", [2000012345678914, 2000012345678915], datetime(2026, 9, 20, 15, tzinfo=timezone.utc))
    _order(db, 2000012345678916, [(777, MLA, 1, 10)])
    _group(db, "o:2000012345678916", [2000012345678916], NOW - timedelta(days=40))
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


def _kpis(db, **filters):
    with board.Board(db, board.BoardFilter(**PERIOD, **filters), scope_pairs=None) as b:
        return b.kpis()


def test_each_pack_or_lone_order_with_a_sale_counts_once(sales) -> None:
    k = _kpis(sales)

    assert (k.operations, k.prev_operations) == (3, 1)
    assert (k.units, k.gross) == (13, 1300)


def test_the_daily_series_counts_each_operation_on_its_day(sales) -> None:
    series = _kpis(sales).series_operations

    assert len(series) == 30 and sum(series) == 3
    # Sep 20 (pack P), Sep 27 (order C), Sep 30 (order A).
    assert [i for i, n in enumerate(series) if n] == [19, 26, 29]


def test_a_filter_counts_the_operations_of_the_rows_it_keeps(sales) -> None:
    # Logi keeps 778: only pack P sells it -- 3 units, $300.
    k = _kpis(sales, marcas=("Logi",))

    assert (k.operations, k.prev_operations, k.units, k.gross) == (1, 0, 3, 300)


def test_the_strip_adds_ticket_and_units_per_sale() -> None:
    k = board.Kpis(
        units=13,
        gross=1300,
        tg=0,
        mtg=0,
        costo=0,
        prev_units=1,
        prev_gross=100,
        prev_tg=0,
        prev_mtg=0,
        prev_costo=0,
        rows=2,
        with_sales=2,
        ageing_avg=None,
        up_to_30=0,
        from_31_to_60=0,
        over_60=0,
        series_units=[0, 13],
        series_gross=[0, 1300],
        series_tg=[0, 0],
        series_markup=[None, None],
        operations=3,
        prev_operations=1,
        series_operations=[0, 3],
    )

    strip = build_board_kpis(k, can_see_margin=False)

    assert strip.operations.model_dump() == {"value": 3, "delta_pct": 200.0, "series": [0, 3]}
    # $1300 / 3 = 433.33 vs $100 / 1.
    assert strip.ticket.model_dump() == {"value": 433.33, "delta_pct": 333.3, "series": [None, 433.33]}
    assert strip.units_per_sale.model_dump() == {"value": 4.33, "delta_pct": 333.3}


def test_without_operations_before_the_changes_are_unknown() -> None:
    k = board.Kpis(
        units=4,
        gross=400,
        tg=0,
        mtg=0,
        costo=0,
        prev_units=0,
        prev_gross=0,
        prev_tg=0,
        prev_mtg=0,
        prev_costo=0,
        rows=1,
        with_sales=1,
        ageing_avg=None,
        up_to_30=0,
        from_31_to_60=0,
        over_60=0,
        series_units=[4],
        series_gross=[400],
        series_tg=[0],
        series_markup=[None],
        operations=2,
        prev_operations=0,
        series_operations=[2],
    )

    strip = build_board_kpis(k, can_see_margin=True)

    assert (strip.operations.delta_pct, strip.ticket.delta_pct, strip.units_per_sale.delta_pct) == (None, None, None)
    assert (strip.ticket.value, strip.units_per_sale.value) == (200.0, 2.0)


def test_without_operations_ticket_and_units_per_sale_are_unknown_never_zero() -> None:
    k = board.Kpis(
        units=0,
        gross=0,
        tg=0,
        mtg=0,
        costo=0,
        prev_units=0,
        prev_gross=0,
        prev_tg=0,
        prev_mtg=0,
        prev_costo=0,
        rows=0,
        with_sales=0,
        ageing_avg=None,
        up_to_30=0,
        from_31_to_60=0,
        over_60=0,
        series_units=[0],
        series_gross=[0],
        series_tg=[0],
        series_markup=[None],
        operations=0,
        prev_operations=0,
        series_operations=[0],
    )

    strip = build_board_kpis(k, can_see_margin=True)

    assert strip.operations.value == 0
    assert strip.ticket.model_dump() == {"value": None, "delta_pct": None, "series": [None]}
    assert strip.units_per_sale.model_dump() == {"value": None, "delta_pct": None}
