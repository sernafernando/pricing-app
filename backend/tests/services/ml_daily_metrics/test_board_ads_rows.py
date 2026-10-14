"""ODD `ml-billing-balance` PR 7b-i: which ROWS the board shows with "Restar publicidad" ON (MA-5, Q8, Q9).

With the toggle ON, "Solo con ventas" keeps a row when `units > 0 OR ads_cost > 0`, and the unfiltered view
also gets the ad-only "sin producto" rows (`(0, mla)` pairs for MLAs no product owns). OFF is untouched (the
goldens of `test_board_ads_core.py` pin it). DERIVED fixtures: figures chosen to be checkable by hand.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import literal, select

from app.services.ml_daily_metrics import board
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    _day,
    _frozen_clock,
    _producto,
    _pub,
    bg_sessions,
)
from tests.services.ml_daily_metrics.seed import Line, seed_sale
from tests.services.ml_daily_metrics.test_board_ads_subtract import OFF, ON, _ad, _rows

AD_DAY = date(2026, 9, 4)
SOLO = dataclasses.replace(ON, solo_con_ventas=True)
FILTERED = dataclasses.replace(SOLO, pub_status_exclude=("closed",))  # keeps every pair, but IS a filter
PM_SCOPE = [("EPSON", "CAT")]  # upper-cased by the database, like `pm_scope` hands them over


def _ads_only_product(db) -> None:
    """Product 11 published as MLA1, no sale at all, 500 of ads."""
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _ad(db, "MLA1", AD_DAY, "500")
    db.commit()


def _unowned_ads(db, cost: str = "30") -> None:
    """MLAX has no publication mapping and no sale: its ads belong to nobody ("sin producto")."""
    _ad(db, "MLAX", AD_DAY, cost)
    db.commit()


# ── is_unfiltered (MA-5 a/b) ──

FILTER_SAMPLES = {
    "stores": ("57997",),
    "marcas": ("Epson",),
    "categorias": ("Cat",),
    "subcategorias": (1,),
    "pms": (7,),
    "q": "impresora",
    "pub_status": ("active",),
    "pub_type": ("clasica",),
    "pub_status_exclude": ("closed",),
    "pub_type_exclude": ("full",),
    "alerts": ("sin_ventas_30d",),
    "stock": ("con_stock",),
    "stock_exclude": ("sin_stock",),
    "ageing": ("over_60",),
    "ageing_exclude": ("up_to_30",),
    "mla_source": select(literal("MLA1")),
}


def test_every_filter_field_has_a_sample() -> None:
    assert set(FILTER_SAMPLES) == board.FILTER_FIELDS


def test_the_default_view_and_every_navigation_choice_is_unfiltered() -> None:
    assert board.is_unfiltered(OFF, None)
    navigating = dataclasses.replace(
        OFF, solo_con_ventas=True, group_by="group", dimension="tienda", sort="markup", sort_desc=False
    )
    assert board.is_unfiltered(navigating, None)  # "solo con ventas" is not a filter (owner Q9)


@pytest.mark.parametrize("name", sorted(board.FILTER_FIELDS))
def test_any_filter_makes_the_view_filtered(name: str) -> None:
    assert not board.is_unfiltered(dataclasses.replace(OFF, **{name: FILTER_SAMPLES[name]}), None)


@pytest.mark.parametrize("pairs", [[], PM_SCOPE])
def test_a_scoped_caller_is_never_unfiltered(pairs) -> None:
    assert not board.is_unfiltered(OFF, pairs)


# ── the row predicate: units > 0 OR ads_cost > 0 (MA-5 c/e) ──


def test_a_product_with_ads_and_no_sales_enters_and_counts_as_a_row_not_as_a_sale(db) -> None:
    _ads_only_product(db)
    row = _rows(db, SOLO)["11"]
    assert (row.units, row.ads_cost, row.tg) == (0, Decimal("500.00"), Decimal("-500.00"))
    with board.Board(db, SOLO, scope_pairs=None) as b:
        kpis = b.kpis()
    assert (kpis.rows, kpis.with_sales) == (1, 0)


def test_with_the_toggle_off_the_same_product_stays_out(db) -> None:
    _ads_only_product(db)
    assert _rows(db, dataclasses.replace(OFF, solo_con_ventas=True)) == {}


def test_an_ads_only_mla_enters_the_publication_view(db) -> None:
    _ads_only_product(db)
    rows = _rows(db, dataclasses.replace(SOLO, group_by="publication"))
    assert rows["MLA1"].ads_cost == Decimal("500.00")


def test_an_ads_only_product_enters_the_group_nodes_and_the_csv_leaves(db) -> None:
    _ads_only_product(db)
    grouped = dataclasses.replace(SOLO, group_by="group", dimension="marca")
    with board.Board(db, grouped, scope_pairs=None) as b:
        nodes = b.group_page(10, with_series=False)
    assert [(n.title, n.units, n.ads_cost) for n in nodes] == [("Epson", 0, Decimal("500.00"))]
    with board.Board(db, grouped, through_leaves=True, scope_pairs=None) as b:
        leaves = b.leaves_for_keys(b.leaf_keys(10))
    assert [(leaf.key, leaf.ads_cost) for leaf in leaves] == [("11", Decimal("500.00"))]


# ── ad-only "sin producto" rows: ON AND unfiltered only (MA-5 a/d) ──


def test_unowned_ads_make_a_sin_producto_row_in_the_unfiltered_view(db) -> None:
    _unowned_ads(db)
    row = _rows(db, SOLO)["0"]
    assert (row.units, row.ads_cost, row.tg, row.title) == (0, Decimal("30.00"), Decimal("-30.00"), "Sin producto")


def test_without_solo_con_ventas_the_rows_are_the_off_rows_plus_the_union_rows(db) -> None:
    _ads_only_product(db)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _unowned_ads(db)
    assert sorted(_rows(db, OFF)) == ["11"]
    assert sorted(_rows(db, ON)) == ["0", "11"]


@pytest.mark.parametrize(
    "f, scope_pairs",
    [(FILTERED, None), (SOLO, PM_SCOPE)],
    ids=["a filter", "a PM scope"],
)
def test_no_sin_producto_row_enters_through_ads_under_a_filter_or_a_scope(db, f, scope_pairs) -> None:
    _ads_only_product(db)
    _unowned_ads(db)
    with board.Board(db, f, scope_pairs=scope_pairs) as b:
        rows = {row.key: row for row in b.page(50, with_series=False)}
        kpis = b.kpis()
    assert sorted(rows) == ["11"]  # the filter-passing product with ads enters; nobody owns MLAX
    assert rows["11"].ads_cost == Decimal("500.00")
    assert kpis.rows == 1


def test_a_sin_producto_sale_is_charged_its_ads_only_in_the_unfiltered_view(db) -> None:
    """MLAX sold with no frozen cost (product 0): its ads reduce the row unfiltered, never under a filter."""
    seed_sale(db, 2000091000000001, _utc(date(2026, 9, 3)), [Line(None, "MLAX", 1, Decimal("1000"))], tg="100")
    _unowned_ads(db)
    assert _rows(db, SOLO)["0"].tg == Decimal("70.00")
    filtered = _rows(db, FILTERED)["0"]
    assert (filtered.tg, filtered.ads_cost) == (Decimal("100.00"), Decimal("0.00"))


def _utc(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
