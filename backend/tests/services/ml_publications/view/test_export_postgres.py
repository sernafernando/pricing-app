"""The keys-then-pages reads behind the CSV export (`listing.ordered_keys` / `items_for_keys`,
`products.ordered_product_keys` / `products_for_keys`) on Postgres, and the Ads cost an export reads once
(`export.PrefetchedAds`).

What matters: the keys are the list's own order over the WHOLE filtered set (the markup sort and filter included,
computed in Python), capped; a page read by keys keeps the keys' order, uses the list's row builder, and skips a key
whose row stopped matching the filters meanwhile.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.services.ml_publications.view import listing, markup_service, products
from app.services.ml_publications.view.filters import parse_filter, parse_markup_filter
from app.services.ml_publications.view.export import PrefetchedAds
from app.services.ml_publications.view.markup_service import MarkupQuery
from app.utils.csv_cells import csv_money
from tests.routers.test_ml_publications_view_markup import fill as markup_fill
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL
from tests.services.ml_publications.view.test_unit_markup import make_ctx

pytestmark = pytest.mark.postgres


@pytest.fixture()
def conn(env):
    """An autocommit connection for seeding, plus the application tables the list and the markup read."""
    SubcategoriaGrupo.__table__.create(bind=env)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(STORES_DDL))
        connection.execute(text(seed.PRICING_DDL))
        yield connection


@pytest.fixture()
def db(env, conn):
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def page_of(db, f, sort, *, markup=None) -> list[str]:
    page = listing.list_items(db, f, sort, 100, 0, events=False, markup=markup, can_see_margin=markup is not None)
    return [row["item_id"] for row in page.items]


@pytest.fixture()
def titled(conn):
    for number, title in ((1, "Delta"), (2, "Alfa"), (3, "Charlie"), (4, "Bravo")):
        seed.add_item(conn, f"MLA{number}", title=title, status="paused" if number == 3 else "active")
    return conn


class TestItemKeys:
    def test_the_keys_are_the_list_order_and_the_cap_bounds_them(self, titled, db) -> None:
        f, sort = parse_filter(), listing.parse_sort("titulo", None)
        assert listing.ordered_keys(db, f, sort, 100, events=False) == page_of(db, f, sort)
        assert listing.ordered_keys(db, f, sort, 2, events=False) == ["MLA2", "MLA4"]

    def test_the_keys_honor_the_filters(self, titled, db) -> None:
        f = parse_filter(estado="active")
        assert listing.ordered_keys(db, f, listing.parse_sort("titulo", "desc"), 100, events=False) == [
            "MLA1",
            "MLA4",
            "MLA2",
        ]

    def test_a_page_by_keys_keeps_their_order_and_skips_a_row_that_stopped_matching(self, titled, db) -> None:
        f = parse_filter(estado="active")
        page = listing.items_for_keys(db, f, ["MLA4", "MLA3", "MLA1"], events=False)
        assert [row["item_id"] for row in page.items] == ["MLA4", "MLA1"]  # MLA3 is paused now
        listed = {
            row["item_id"]: row
            for row in listing.list_items(db, f, listing.parse_sort(None, None), 50, 0, events=False).items
        }
        assert page.items[0] == listed["MLA4"]  # the list's own row builder

    def test_an_empty_page_reads_nothing(self, titled, db) -> None:
        assert listing.items_for_keys(db, parse_filter(), [], events=False).items == []


class TestItemKeysByMarkup:
    @pytest.fixture()
    def priced(self, conn, db, monkeypatch):
        monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: make_ctx())
        monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", lambda db, ids, **kwargs: {})
        markup_fill(conn)
        return db

    @pytest.mark.parametrize(
        ("orden", "direction", "params"),
        [
            ("markup", None, {}),
            ("markup", "desc", {}),
            ("titulo", None, {"markup_neg": True}),
            ("precio", None, {"markup_min": "0"}),
        ],
    )
    def test_the_markup_sort_and_filter_are_honored(self, priced, orden, direction, params) -> None:
        markup = MarkupQuery(priced, parse_markup_filter(**params))
        f, sort = parse_filter(), listing.parse_sort(orden, direction)
        expected = page_of(priced, f, sort, markup=markup)
        keys = listing.ordered_keys(priced, f, sort, 100, events=False, markup=markup, can_see_margin=True)
        assert expected and keys == expected
        assert (
            listing.ordered_keys(priced, f, sort, 1, events=False, markup=markup, can_see_margin=True) == expected[:1]
        )

    def test_a_page_by_keys_carries_the_markup(self, priced) -> None:
        markup = MarkupQuery(priced, parse_markup_filter())
        page = listing.items_for_keys(priced, parse_filter(), ["MLA2", "MLA1"], events=False, markup=markup)
        assert [row["item_id"] for row in page.items] == ["MLA2", "MLA1"]
        assert all("markup" in row for row in page.items)


class TestProductKeys:
    @pytest.fixture()
    def linked(self, env, conn):
        seed.create_board_tables(env)
        seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link")
        seed.add_product(conn, 78, "R78", "Antena")
        seed.add_item(conn, "MLA1", status="active")
        seed.add_item(conn, "MLA2", status="active")
        seed.add_item(conn, "MLA3", status="paused")
        seed.add_link(conn, "MLA1", 77)
        seed.add_link(conn, "MLA3", 77)
        seed.add_link(conn, "MLA2", 78)
        seed.add_item(conn, "MLA4", status="active")  # no link: "Sin producto"
        return conn

    @pytest.mark.parametrize("descending", [False, True])
    def test_the_keys_are_the_list_order(self, linked, db, descending) -> None:
        f = parse_filter()
        listed = products.list_products(db, f, "titulo", descending, 100, 0)
        keys = products.ordered_product_keys(db, f, "titulo", descending, 100)
        assert keys == [row.product_item_id for row in listed.rows]
        assert products.ordered_product_keys(db, f, "titulo", descending, 1) == keys[:1]

    def test_a_page_by_keys_keeps_their_order_and_the_whole_count_of_each_product(self, linked, db) -> None:
        page = products.products_for_keys(db, parse_filter(), [0, 77])
        assert [(row.product_item_id, row.title, row.publications_count) for row in page.rows] == [
            (0, "Sin producto", 1),
            (77, "Router AX", 2),
        ]

    def test_a_product_that_stopped_matching_is_skipped(self, linked, db) -> None:
        page = products.products_for_keys(db, parse_filter(estado="paused"), [78, 77])
        assert [(row.product_item_id, row.publications_count) for row in page.rows] == [(77, 1)]


class TestPrefetchedAds:
    """The Ads cost of an export is read once (the request's provider rides on the request session) and served per
    page from memory; a provider that failed fails every page, so the markup degrades as the list's does."""

    class Provider:
        def __init__(self, fail: bool = False) -> None:
            self.calls: list = []
            self.fail = fail

        def amounts(self, mla_ids, date_from, date_to):
            self.calls.append(mla_ids)
            if self.fail:
                raise RuntimeError("down")
            return {"MLA1": 10.0, "MLA2": 20.0}

    def test_one_read_then_each_page_gets_its_own_amounts(self) -> None:

        provider = self.Provider()
        ads = PrefetchedAds(provider, date(2026, 9, 1), date(2026, 9, 30))
        assert ads.amounts(["MLA2", "MLA3"], date(2026, 9, 1), date(2026, 9, 30)) == {"MLA2": 20.0}
        assert ads.amounts(None, date(2026, 9, 1), date(2026, 9, 30)) == {"MLA1": 10.0, "MLA2": 20.0}
        assert provider.calls == [None]  # one read, of the whole period: the keys are not fixed yet

    def test_a_failed_read_fails_every_page(self) -> None:

        ads = PrefetchedAds(self.Provider(fail=True), date(2026, 9, 1), date(2026, 9, 30))
        with pytest.raises(RuntimeError):
            ads.amounts(["MLA1"], date(2026, 9, 1), date(2026, 9, 30))


class TestCsvMoney:
    @pytest.mark.parametrize(
        ("value", "cell"),
        [
            (float("nan"), ""),
            (float("inf"), ""),
            (float("-inf"), ""),
            (-0.001, "0,00"),
            (-0.0, "0,00"),
            (None, ""),
            (-12.345, "-12,35"),
            (1000, "1000,00"),
        ],
    )
    def test_cells(self, value, cell) -> None:

        assert csv_money(value) == cell
