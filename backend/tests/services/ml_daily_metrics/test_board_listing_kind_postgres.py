"""Métricas ML lists publications Clásica first, then 3, 6, 9 and 12 cuotas (owner, 2026-11-02): each
publication row carries its listing kind, read from `ml_items` (listing type, campaign tags, sale-term
campaign), and the `listing_kind` sort orders by it in SQL, before LIMIT/OFFSET, with the gross as tiebreak.
A product's publication sub-rows put the kind first, then the board's sort."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.test_board_subrows_postgres import _seed_products

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
FIRST = 900001
# MLA -> (ml_items listing type, tags, sale-term campaign); the ERP mirror says gold_special for all.
ML_ITEMS = {
    "MLA9000011": ("gold_pro", ["12x_campaign"], None),
    "MLA9000012": ("gold_special", [], None),
    "MLA9000013": ("gold_pro", [], None),
    "MLA9000021": ("gold_pro", ["good_quality_thumbnail", "3x_campaign"], None),
    "MLA9000022": ("gold_pro", [], "9x_campaign"),
    "MLA9000023": ("gold_special", ["pcj-co-funded"], None),
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture()
def kinds_catalog(board_pg):
    _seed_products(board_pg, FIRST, 2, sales_per_mla=2)
    for mla, (listing_type_id, tags, campaign) in ML_ITEMS.items():
        board_pg.execute(
            text(
                "INSERT INTO ml_items (item_id, listing_type_id, tags, installments_campaign) "
                "VALUES (:mla, :lt, :tags, :campaign)"
            ),
            {"mla": mla, "lt": listing_type_id, "tags": tags, "campaign": campaign},
        )
    # The co-funded Clásica sells more than the plain one: within one kind the gross decides.
    board_pg.execute(text("UPDATE ml_order_items_ops SET quantity = quantity * 10 WHERE item_id = 'MLA9000023'"))
    return board_pg


def _filter(**overrides):
    values = dict(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="publication")
    values.update(overrides)
    return board.BoardFilter(**values)


def _page(db, limit=None, offset=0, **overrides):
    with board.Board(db, _filter(**overrides), scope_pairs=None) as b:
        return b.page(limit, offset)


@pytest.mark.postgres
def test_publication_rows_carry_the_kind_read_from_ml_items(kinds_catalog) -> None:
    kinds = {row.mla: row.pub.listing_kind for row in _page(kinds_catalog)}
    assert kinds == {
        "MLA9000011": "cuotas_12",
        "MLA9000012": "clasica",
        "MLA9000013": "cuotas_6",
        "MLA9000021": "cuotas_3",
        "MLA9000022": "cuotas_9",
        "MLA9000023": "clasica_cofinanciada",
    }


@pytest.mark.postgres
def test_a_publication_missing_from_ml_items_reads_its_kind_from_the_erp_listing_type(kinds_catalog) -> None:
    kinds_catalog.execute(text("DELETE FROM ml_items WHERE item_id = 'MLA9000013'"))
    kinds_catalog.execute(
        text("UPDATE tb_mercadolibre_items_publicados SET mlp_listing_type_id = 'gold_pro' WHERE mlp_id = 9000013")
    )
    kinds = {row.mla: row.pub.listing_kind for row in _page(kinds_catalog)}
    assert kinds["MLA9000013"] == "cuotas_6"


@pytest.mark.postgres
def test_the_listing_kind_sort_pages_clasica_then_3_6_9_12_cuotas_with_the_gross_as_tiebreak(kinds_catalog) -> None:
    order = ["MLA9000023", "MLA9000012", "MLA9000021", "MLA9000013", "MLA9000022", "MLA9000011"]
    assert [row.mla for row in _page(kinds_catalog, sort="listing_kind", sort_desc=False)] == order
    # Before LIMIT/OFFSET: the second page continues the same order.
    assert [row.mla for row in _page(kinds_catalog, limit=2, offset=2, sort="listing_kind", sort_desc=False)] == (
        order[2:4]
    )


@pytest.mark.postgres
def test_another_sort_still_wins_on_the_publication_rows(kinds_catalog) -> None:
    # The co-funded Clásica sells most; the rest tie on gross and the MLA settles them.
    assert [row.mla for row in _page(kinds_catalog, sort="gross", sort_desc=True)] == [
        "MLA9000023",
        "MLA9000011",
        "MLA9000012",
        "MLA9000013",
        "MLA9000021",
        "MLA9000022",
    ]


@pytest.mark.postgres
def test_a_products_publication_sub_rows_put_the_kind_first_then_the_board_sort(kinds_catalog) -> None:
    f = _filter(sort="gross", sort_desc=True)
    with board.Board(kinds_catalog, f, product_item_id=FIRST, scope_pairs=None, kind_first=True) as b:
        assert [row.mla for row in b.page(limit=None, apply_alerts=False)] == [
            "MLA9000012",
            "MLA9000013",
            "MLA9000011",
        ]


@pytest.mark.postgres
def test_the_listing_kind_sort_descending_puts_the_highest_installments_first(kinds_catalog) -> None:
    rows = _page(kinds_catalog, sort="listing_kind", sort_desc=True)
    assert [row.mla for row in rows] == [
        "MLA9000011",
        "MLA9000022",
        "MLA9000013",
        "MLA9000021",
        "MLA9000023",
        "MLA9000012",
    ]


@pytest.mark.postgres
def test_product_rows_sorted_by_listing_kind_follow_their_best_publication(kinds_catalog) -> None:
    # Product FIRST+1 has a co-funded Clásica (rank 0) and sells more; FIRST has a plain Clásica (rank 0) too: a tie
    # on the rank, settled by the gross. With no Clásica left, FIRST+1's best is a 3 cuotas and FIRST's a 6 cuotas.
    rows = _page(kinds_catalog, group_by="product", sort="listing_kind", sort_desc=False)
    assert [row.key for row in rows] == [str(FIRST + 1), str(FIRST)]
    kinds_catalog.execute(text("UPDATE ml_items SET listing_type_id = 'gold_pro' WHERE item_id = 'MLA9000012'"))
    kinds_catalog.execute(text("UPDATE ml_items SET listing_type_id = 'gold_pro' WHERE item_id = 'MLA9000023'"))
    kinds_catalog.execute(text("UPDATE ml_items SET tags = ARRAY['3x_campaign'] WHERE item_id = 'MLA9000023'"))
    rows = _page(kinds_catalog, group_by="product", sort="listing_kind", sort_desc=False)
    assert [row.key for row in rows] == [str(FIRST + 1), str(FIRST)]
    rows = _page(kinds_catalog, group_by="product", sort="listing_kind", sort_desc=True)
    assert [row.key for row in rows] == [str(FIRST), str(FIRST + 1)]
