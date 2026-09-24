"""Unit tests for `app.services.ml_sales_query.search.apply_search`
(spec `ml-sales-search` R25, R25a, R26, R27; PR9.T3).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.services.ml_sales_query.filters import SalesFilter, build_scope
from app.services.ml_sales_query.search import apply_search


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _seed_order(db, order_id: int, *, pack_id=None, buyer_nickname=None, date_created=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            buyer_nickname=buyer_nickname,
            date_created=date_created or datetime(2026, 1, 1, tzinfo=timezone.utc),
            ml_last_updated=date_created or datetime(2026, 1, 1, tzinfo=timezone.utc),
            seller_id=999,
            total_amount=100,
            paid_amount=100,
            currency_id="ARS",
        )
    )
    db.flush()


def _seed_item(db, order_id: int, item_id: str, *, title=None, seller_sku=None) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, title=title, seller_sku=seller_sku, quantity=1))
    db.flush()


def _matched_ids(db, q: str) -> set[int]:
    query = db.query(MlOrdersOps)
    if settings.ML_USER_ID:
        query = query.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    query = apply_search(query, db, q)
    return {o.order_id for o in query.all()}


class TestDigitsMatchOrderOrPackId:
    def test_matches_the_exact_order_id(self, db):
        _seed_order(db, 111)
        _seed_order(db, 222)
        assert _matched_ids(db, "111") == {111}

    def test_matches_a_pack_id_too(self, db):
        _seed_order(db, 300, pack_id=555)
        _seed_order(db, 301, pack_id=555)
        _seed_order(db, 400)
        assert _matched_ids(db, "555") == {300, 301}


class TestMlaMatchesItemId:
    def test_matches_orders_carrying_that_item_id(self, db):
        _seed_order(db, 500)
        _seed_order(db, 501)
        _seed_item(db, 500, "MLA123456")
        assert _matched_ids(db, "MLA123456") == {500}

    def test_is_case_insensitive(self, db):
        _seed_order(db, 502)
        _seed_item(db, 502, "MLA123456")
        assert _matched_ids(db, "mla123456") == {502}


class TestFreeTextMatchesBuyerAndOwnItemFields:
    def test_matches_buyer_nickname(self, db):
        _seed_order(db, 600, buyer_nickname="comprador_test")
        _seed_order(db, 601, buyer_nickname="otro")
        assert _matched_ids(db, "comprador") == {600}

    def test_matches_item_title_r25a(self, db):
        """R25a: matches `ml_order_items_ops.title` directly -- never
        through `producto_item_id` (no frozen-cost row exists here at
        all, and the order is still found)."""
        _seed_order(db, 700)
        _seed_item(db, 700, "MLA1", title="Zapatilla deportiva talle 42")
        assert _matched_ids(db, "deportiva") == {700}

    def test_matches_item_seller_sku_r25a(self, db):
        _seed_order(db, 701)
        _seed_item(db, 701, "MLA2", seller_sku="SKU-ABC-99")
        assert _matched_ids(db, "ABC-99") == {701}

    def test_below_three_chars_matches_nothing(self, db):
        _seed_order(db, 800, buyer_nickname="ab")
        assert _matched_ids(db, "ab") == set()


class TestEmptyAndBlankSearch:
    def test_none_q_leaves_the_query_unchanged(self, db):
        _seed_order(db, 900)
        assert _matched_ids(db, None) == {900}

    def test_blank_q_leaves_the_query_unchanged(self, db):
        _seed_order(db, 901)
        assert _matched_ids(db, "   ") == {901}

    def test_no_match_returns_an_explicit_empty_result_not_an_error(self, db):
        _seed_order(db, 902, buyer_nickname="alguien")
        assert _matched_ids(db, "nadie_coincide") == set()


class TestSearchIntersectsWithActiveFilters:
    def test_search_combined_with_operation_status_is_an_intersection(self, db):
        _seed_order(db, 1000, buyer_nickname="mismo_comprador")
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 1000).update({"status": "cancelled"})
        _seed_order(db, 1001, buyer_nickname="mismo_comprador")
        db.flush()
        scope = build_scope(
            db,
            SalesFilter(
                operation_status="cancelled", q="mismo_comprador", include_unknown=True, include_in_dispute=True
            ),
        )
        ids = {row.order_id for row in scope.listing_query.with_entities(MlOrdersOps.order_id).all()}
        assert ids == {1000}


class TestSearchNeverErrors:
    """SEARCH R27: a search that matches nothing returns an explicit empty
    result. It must never reach the user as a 500."""

    def test_a_number_too_big_for_the_column_matches_nothing(self, db) -> None:
        _seed_order(db, 7001, buyer_nickname="comprador")
        db.commit()

        # 25 digits: `isdigit()` is True, but the value does not fit the
        # BIGINT order_id/pack_id columns.
        assert _matched_ids(db, "9" * 25) == set()

    def test_unicode_digits_match_nothing(self, db) -> None:
        _seed_order(db, 7002, buyer_nickname="comprador")
        db.commit()

        # `"²³".isdigit()` is True but `int("²³")` raises ValueError.
        assert _matched_ids(db, "²³") == set()


class TestSearchEscapesWildcards:
    """The free text is data, not a pattern: `%` and `_` must not turn a
    search into "everything"."""

    def test_percent_signs_do_not_match_every_sale(self, db) -> None:
        _seed_order(db, 7003, buyer_nickname="comprador")
        _seed_order(db, 7004, buyer_nickname="otro")
        db.commit()

        assert _matched_ids(db, "%%%") == set()

    def test_underscore_is_matched_literally(self, db) -> None:
        _seed_order(db, 7005, buyer_nickname="juan_perez")
        _seed_order(db, 7006, buyer_nickname="juanXperez")
        db.commit()

        assert _matched_ids(db, "juan_perez") == {7005}
