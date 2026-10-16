"""The Métricas ML store ("Tienda") chips count OPERATIONS of the period, not board rows, on real Postgres.

An operation is what Ventas ML counts in its own store chips: a pack or a lone order, accredited in the period
(the money's day), cancelled ones included. Its store is the publication's CURRENT store. Every other board
filter still narrows the count, through the board pairs the operation's items belong to; the store filter never
narrows its own chips."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.sales import day_bounds
from app.services.ml_sales_query.filters import SalesFilter, build_scope, store_facet_counts
from tests.services.ml_daily_metrics.test_board_nested_groups_postgres import _publish
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
FIRST = date(2026, 9, 1)
GAUSS, TP = 57997, 471846
MLA_A, MLA_B, MLA_C, MLA_D = "MLA7100000001", "MLA7100000002", "MLA7100000003", "MLA7100000004"
# Ventas ML's own defaults: every doubtful-case switch ON, cancelled sales included.
VENTAS_DEFAULTS = dict(
    include_unknown=True, include_in_dispute=True, include_mixed=True, include_provisional=True, include_cancelled=True
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _sale(db, order_id: int, lines, accredited: datetime, *, pack_id=None, status="paid", payment="approved"):
    """One order, its stored metrics and its payment (Ventas ML's day); the group row (the board's day) is
    written by the caller once per group."""
    _order(db, order_id, lines, status=status, pack_id=pack_id)
    db.execute(
        text("INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) VALUES (:o, :o, :s, :d)"),
        {"o": order_id, "s": payment, "d": accredited},
    )


@pytest.fixture()
def shop(board_pg):
    """Three products over two stores and no store:

    - o1, o2: Epson 21 on MLA_A (Gauss), two lone sales -> two operations, ONE board row;
    - pack P1: o3 Epson 21 on MLA_A (Gauss) + o4 Logitech 24 on MLA_D (TP): one operation in each store;
    - o5: Epson 21 on MLA_B (TP): the same product in a second store;
    - o8: Logitech 24 on MLA_D (TP): a second operation of the same TP publication;
    - o6: Tinta 22 on MLA_C (no store), cancelled without coverage, refunded: Ventas ML counts it;
    - o7: Logitech 24 on MLA_D, accredited in August: out of the period.
    """
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) VALUES "
            "(21, 'S21', 'Epson L3250', 'Epson', 'Impresoras', 10, 5), "
            "(22, 'S22', 'Tinta', 'Epson', 'Insumos', 20, 0), "
            "(24, 'S24', 'Mouse', 'Logitech', 'Perifericos', 30, 2)"
        )
    )
    for mlp_id, (product, mla, store) in enumerate(
        ((21, MLA_A, GAUSS), (21, MLA_B, TP), (22, MLA_C, None), (24, MLA_D, TP)), start=7100
    ):
        _publish(db, product, mla, store, mlp_id)
    day = NOW - timedelta(days=2)
    base = 2000071000000000
    for n, (product, mla) in ((1, (21, MLA_A)), (2, (21, MLA_A)), (5, (21, MLA_B)), (8, (24, MLA_D))):
        _sale(db, base + n, [(product, mla, 1, 10)], day)
        _group(db, f"o:{base + n}", [base + n], day)
    pack = 2000079000000001
    _sale(db, base + 3, [(21, MLA_A, 1, 10)], day, pack_id=pack)
    _sale(db, base + 4, [(24, MLA_D, 1, 10)], day, pack_id=pack)
    _group(db, f"p:{pack}", [base + 3, base + 4], day)
    _sale(db, base + 6, [(22, MLA_C, 1, 10)], day, status="cancelled", payment="refunded")
    _group(db, f"o:{base + 6}", [base + 6], day)
    august = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    _sale(db, base + 7, [(24, MLA_D, 1, 10)], august)
    _group(db, f"o:{base + 7}", [base + 7], august)
    db.flush()
    return db


def _filter(**kw: Any) -> board.BoardFilter:
    kw.setdefault("date_from", FIRST)
    kw.setdefault("date_to", TODAY)
    return board.BoardFilter(**kw)


def _board_stores(db, f: board.BoardFilter) -> Tuple[Dict[str, int], int]:
    with board.Board(db, f, scope_pairs=None) as b:
        facets = b.facets()
    return facets.stores, facets.stores_total


def _ventas_stores(db, first: date = FIRST, last: date = TODAY) -> Tuple[Dict[str, int], int]:
    scope = build_scope(db, SalesFilter(date_range=day_bounds(first, last), **VENTAS_DEFAULTS))
    return store_facet_counts(scope)


@pytest.mark.postgres
def test_store_chips_count_the_operations_of_the_period(shop) -> None:
    stores, total = _board_stores(shop, _filter())
    # Gauss: o1, o2 and the pack (one board row). TP: the pack, o5 and o8. No store: the cancelled o6. o7 is
    # August's.
    assert stores == {str(GAUSS): 3, str(TP): 3, board.NO_STORE: 1}
    # "Todas" is the operations of the period: the pack counts once although it spans two stores.
    assert total == 6


@pytest.mark.postgres
def test_store_chips_agree_with_ventas_ml_for_the_same_period(shop) -> None:
    assert _board_stores(shop, _filter()) == _ventas_stores(shop)
    august = (date(2026, 8, 1), date(2026, 8, 31))
    assert _board_stores(shop, _filter(date_from=august[0], date_to=august[1])) == _ventas_stores(shop, *august)
    assert _ventas_stores(shop, *august) == ({str(TP): 1}, 1)


@pytest.mark.postgres
def test_every_other_filter_narrows_the_store_chips_but_never_the_store_filter(shop) -> None:
    # The store filter never narrows its own chips.
    assert _board_stores(shop, _filter(stores=(str(GAUSS),))) == _board_stores(shop, _filter())
    # A brand keeps only the operations of its products' publications: the pack counts under TP only (its
    # Logitech item), never under Gauss through its Epson sibling.
    assert _board_stores(shop, _filter(marcas=("Logitech",))) == ({str(TP): 2}, 2)
    # "Solo con ventas" drops the rows with no units in the period: the cancelled Tinta row, and its operation.
    assert _board_stores(shop, _filter(solo_con_ventas=True)) == ({str(GAUSS): 3, str(TP): 3}, 5)
    # A search narrows the rows the same way.
    assert _board_stores(shop, _filter(q="mouse")) == ({str(TP): 2}, 2)


@pytest.mark.postgres
def test_publication_view_counts_the_same_operations(shop) -> None:
    assert _board_stores(shop, _filter(group_by="publication")) == _board_stores(shop, _filter())


@pytest.mark.postgres
def test_tp_only_lock_counts_only_the_tp_stores_operations(shop) -> None:
    """The `tplink.solo` lock (`ml_metricas._tp_solo_filter`): stores intersected with the TP group, the universe
    bounded to the MLAs published there, "Costos TP" on."""
    f = replace(
        _filter(),
        stores=(str(TP),),
        costos_tp=True,
        tp_store_ids=(TP,),
        mla_source=board.mlas_in_stores((TP,)),
    )
    # Two TP board rows (Epson, Logitech), three TP operations (o5, o8, the pack).
    assert _board_stores(shop, f) == ({str(TP): 3}, 3)


@pytest.mark.postgres
def test_an_item_without_a_frozen_cost_still_counts_like_ventas_ml(shop) -> None:
    """An order item with no frozen cost row (the board places its sale on the "sin producto" pair of its MLA)
    still counts in its publication's store, as Ventas ML counts it -- under every product filter that keeps
    that MLA."""
    order_id = 2000071000000009
    _sale(shop, order_id, [(21, MLA_A, 1, 10)], NOW - timedelta(days=1))
    _group(shop, f"o:{order_id}", [order_id], NOW - timedelta(days=1))
    shop.execute(text("DELETE FROM ml_order_item_costos WHERE order_id = :o"), {"o": order_id})
    shop.flush()

    assert _board_stores(shop, _filter()) == _ventas_stores(shop)
    assert _board_stores(shop, _filter()) == ({str(GAUSS): 4, str(TP): 3, board.NO_STORE: 1}, 7)
    # Epson: o1, o2, the pack's Epson item and this one in Gauss; o5 in TP; the cancelled Tinta with no store.
    assert _board_stores(shop, _filter(marcas=("Epson",))) == ({str(GAUSS): 4, str(TP): 1, board.NO_STORE: 1}, 6)
