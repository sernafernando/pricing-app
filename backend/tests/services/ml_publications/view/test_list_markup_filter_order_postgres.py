"""The list filtered by markup and ordered by a database column: the page and the total it returns.

The markup of the whole set is computed in Python; the order of a database column (title, price, activity...) is
applied by the database. The page used to come from the ORDERED ids of the whole filtered set (25k ids sorted and
shipped to Python to keep fifty); now the database orders only the ids the markup filter accepted and cuts the
page. The answer must be the same.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.services.ml_publications.view import listing, markup_service
from app.services.ml_publications.view.filters import MarkupFilter, parse_filter
from app.services.ml_publications.view.markup_service import MarkupQuery
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL
from tests.services.ml_publications.view.test_markup_characterization_postgres import seed_catalog
from tests.services.ml_publications.view.test_unit_markup import make_ctx

pytestmark = pytest.mark.postgres


@pytest.fixture()
def conn(env):  # noqa: F811
    SubcategoriaGrupo.__table__.create(bind=env)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(STORES_DDL))
        connection.execute(text(seed.PRICING_DDL))
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda session: make_ctx())
    monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", lambda session, ids, **kw: {70: 1500.0})


def titled(connection) -> None:
    """Titles in the REVERSE order of the item ids, so an order by title cannot be mistaken for the id order."""
    seed_catalog(connection)
    connection.execute(
        text(
            "UPDATE ml_items SET title = 'Titulo ' || lpad(CAST(100 - CAST(substr(item_id, 4) AS int) AS text), 3, '0')"
        )
    )


def page(session, markup_filter, sort, descending=None, limit=50, offset=0):
    result = listing.list_items(
        session,
        parse_filter(),
        listing.parse_sort(sort, descending),
        limit,
        offset,
        events=False,
        markup=MarkupQuery(session, markup_filter),
    )
    return result.total, [row["item_id"] for row in result.items]


NEGATIVE_BY_TITLE = ["MLA15", "MLA14", "MLA13", "MLA12", "MLA7", "MLA6", "MLA2", "MLA1"]  # titles run backwards


class TestFilteredByMarkupOrderedByAColumn:
    def test_negative_ones_by_title(self, conn, db) -> None:
        titled(conn)
        assert page(db, MarkupFilter(negative=True), "titulo") == (8, NEGATIVE_BY_TITLE)
        assert page(db, MarkupFilter(negative=True), "titulo", "desc") == (8, NEGATIVE_BY_TITLE[::-1])

    def test_a_page_of_the_filtered_set(self, conn, db) -> None:
        titled(conn)
        assert page(db, MarkupFilter(negative=True), "titulo", limit=3, offset=2) == (8, NEGATIVE_BY_TITLE[2:5])

    def test_a_page_past_the_end_still_reports_the_total(self, conn, db) -> None:
        titled(conn)
        assert page(db, MarkupFilter(negative=True), "titulo", offset=40) == (8, [])

    def test_a_range_ordered_by_price_then_item_id(self, conn, db) -> None:
        titled(conn)
        total, ids = page(db, MarkupFilter(minimum=-10, maximum=80), "precio")
        assert total == 7 and sorted(ids) == sorted(["MLA13", "MLA14", "MLA15", "MLA2", "MLA1", "MLA3", "MLA4"])
        # the same publications, in the order of the unfiltered list restricted to them
        _, everyone = page(db, MarkupFilter(), "precio")
        assert ids == [item_id for item_id in everyone if item_id in set(ids)]

    def test_a_filter_nobody_passes_is_an_empty_page(self, conn, db) -> None:
        titled(conn)
        assert page(db, MarkupFilter(minimum=1000), "titulo") == (0, [])


class TestTheDatabaseOrdersOnlyWhatPassed:
    def test_the_page_comes_from_one_limited_statement_over_the_accepted_ids(self, conn, db) -> None:
        titled(conn)
        recorded: list[str] = []

        def record(connection, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", record)
        try:
            page(db, MarkupFilter(negative=True), "titulo", limit=3)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)
        ordering = [s for s in recorded if "ORDER BY" in s and "lower(" in s]
        assert len(ordering) == 1 and "LIMIT" in ordering[0] and "ANY" in ordering[0].upper()


class TestMarkupFirstThenAColumn:
    def test_the_worst_markup_leads_and_the_title_breaks_its_ties(self, conn, db) -> None:
        titled(conn)
        _, got = page(db, MarkupFilter(), "markup,titulo", "asc,asc")
        result, _ = listing.markup_accepted(db, parse_filter(), MarkupQuery(db, MarkupFilter()))
        worst = {item_id: item.markup.worst for item_id, item in result.items.items()}
        titles = dict(db.execute(text("SELECT item_id, lower(title) FROM ml_items")).all())
        expected = sorted(worst, key=lambda i: (worst[i] is None, worst[i] or 0, titles[i], i))
        assert got == expected
        pages = [page(db, MarkupFilter(), "markup,titulo", "asc,asc", limit=4, offset=o)[1] for o in range(0, 40, 4)]
        assert [item_id for chunk in pages for item_id in chunk] == expected  # the database cuts stable pages
        tied = len(worst) - len(set(worst.values()))
        assert tied > 0  # real ties (the unpriced ones at least), broken by the title, which runs against the ids


class TestMarkupAsALaterKey:
    def test_the_worst_markup_breaks_the_ties_of_a_column(self, conn, db) -> None:
        titled(conn)
        conn.execute(text("UPDATE ml_items SET title = 'Grupo ' || (CAST(substr(item_id, 4) AS int) % 3)"))
        _, got = page(db, MarkupFilter(), "titulo,markup", "desc,asc")
        result, _ = listing.markup_accepted(db, parse_filter(), MarkupQuery(db, MarkupFilter()))
        worst = {item_id: item.markup.worst for item_id, item in result.items.items()}
        titles = dict(db.execute(text("SELECT item_id, lower(title) FROM ml_items")).all())
        by_title = sorted(worst, key=lambda i: (worst[i] is None, worst[i] or 0, i))
        expected = sorted(by_title, key=lambda i: titles[i], reverse=True)  # stable: each title keeps the markup order
        assert got == expected
        pages = [page(db, MarkupFilter(), "titulo,markup", "desc,asc", limit=4, offset=o)[1] for o in range(0, 40, 4)]
        assert [item_id for chunk in pages for item_id in chunk] == expected
        by_id = sorted(sorted(worst), key=lambda i: titles[i], reverse=True)
        assert got != by_id  # the markup, not the item id, breaks the ties

    def test_a_markup_filter_with_a_later_markup_key_keeps_only_what_passed(self, conn, db) -> None:
        titled(conn)
        total, got = page(db, MarkupFilter(negative=True), "titulo,markup")
        assert total == 8 and got == NEGATIVE_BY_TITLE  # distinct titles: the title alone decides
