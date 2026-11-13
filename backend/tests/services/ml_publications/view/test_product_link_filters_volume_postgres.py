"""The `sin_producto` / `producto` filters on a one-row list page, on the 25k volume seed.

A page of one row (`limit=1`) made the planner walk `ix_ml_items_last_trigger` in the page's order, betting it finds
a row that passes the filters within a few rows. `has_product` was an `EXISTS` over `product_links`, a `SELECT
DISTINCT` subquery the planner cannot probe by `item_id`: it materialized all of it and compared every one of its rows
with every publication walked (a `Join Filter`), 24.5k x 18k. `sin_producto` hit the list's 8 s
`statement_timeout`; a page of 50 rows took a hash join and answered at once.

The filters now read `ml_item_product_links` directly, correlated by its primary key (`item_id` leads it), with the
same rule (`linked` link of the item or of a live variation). An `EXISTS` does not need the `DISTINCT`.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest
from sqlalchemy import ARRAY, Integer, Select, all_, any_, event, exists, literal, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.producto import ProductoERP
from app.services.ml_publications.view import filters, listing
from app.services.ml_publications.view.filters import PublicationFilter, parse_filter
from tests.services.ml_publications.view.test_view_volume_postgres import PRODUCTS, seeded  # noqa: F401

pytestmark = [pytest.mark.postgres, pytest.mark.volume]

SCENARIOS = {
    "sin_producto": dict(sin_producto=True),
    "producto": dict(producto=str(800000 + PRODUCTS // 2)),
}


@pytest.fixture()
def session(seeded) -> Iterator[Session]:  # noqa: F811
    session = sessionmaker(bind=seeded, autocommit=False, autoflush=False)()
    try:
        listing.bound(session)  # as every read of the router: statement_timeout and jit = off
        yield session
    finally:
        session.rollback()
        session.close()


def page(session: Session, f: PublicationFilter, limit: int) -> Any:
    return listing.list_items(session, f, listing.parse_sort(None, None), limit, 0, events=True)


def page_statement(session: Session, f: PublicationFilter, limit: int) -> tuple[str, Any]:
    """The list page's own SELECT (ordered, limited), as the cursor got it."""
    sent: list[tuple[str, Any]] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        if "ORDER BY i.last_trigger_received_at" in statement:
            sent.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        page(session, f, limit)
    finally:
        event.remove(bind, "before_cursor_execute", record)
    return sent[0]


def plan_nodes(session: Session, statement: str, parameters: Any) -> Iterator[dict[str, Any]]:
    cursor = session.connection().connection.cursor()
    try:
        cursor.execute("EXPLAIN (FORMAT JSON) " + statement, parameters)
        document = cursor.fetchone()[0]
    finally:
        cursor.close()
    stack = [(json.loads(document) if isinstance(document, str) else document)[0]["Plan"]]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.get("Plans", []))


@pytest.mark.parametrize("name", SCENARIOS)
def test_a_one_row_page_answers_what_a_full_page_starts_with(session, name) -> None:
    f = parse_filter(**SCENARIOS[name])
    full = page(session, f, 50)
    one = page(session, f, 1)  # cancelled by the 8 s statement_timeout before the fix
    assert full.total > 0
    assert (one.total, [row["item_id"] for row in one.items]) == (full.total, [full.items[0]["item_id"]])


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_link_test_is_probed_by_item_not_compared_per_row(session, name) -> None:
    """No `Join Filter` compares the row's `item_id` with a materialized set: the link test is an index condition."""
    statement, parameters = page_statement(session, parse_filter(**SCENARIOS[name]), 1)
    per_row = [
        node["Join Filter"]
        for node in plan_nodes(session, statement, parameters)
        if "item_id = i.item_id" in node.get("Join Filter", "")
    ]
    assert per_row == []
    # and the links are read by an index: by `item_id` (`sin_producto`, walking the page), or by product (`producto`)
    reads = [
        (node["Node Type"], node.get("Index Cond", ""))
        for node in plan_nodes(session, statement, parameters)
        if node.get("Alias") == "pl_filter_l"
    ]
    assert reads and all(kind == "Index Scan" and "item_id" in cond for kind, cond in reads)


def previous_has_product(products: Any = None, *, outside: Any = None) -> Any:
    """main's `has_product`: an `EXISTS` over the `DISTINCT` `product_links` subquery."""
    pl = filters.product_links("pl_filter_previous")
    found = select(1).select_from(pl).where(pl.c.item_id == filters.T.i.item_id)
    if isinstance(products, Select):
        found = found.where(pl.c.producto_item_id.in_(products))
    elif products is not None:
        found = found.where(pl.c.producto_item_id == any_(literal(products, ARRAY(Integer))))
    if outside is not None:
        found = found.where(pl.c.producto_item_id != all_(literal(outside, ARRAY(Integer))))
    return exists(found)


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_filter_selects_what_the_distinct_subquery_selected(session, name, monkeypatch) -> None:
    f = parse_filter(**SCENARIOS[name])
    now = page(session, f, 50)
    monkeypatch.setattr(filters, "has_product", previous_has_product)
    before = page(session, f, 50)
    assert (now.total, [r["item_id"] for r in now.items]) == (before.total, [r["item_id"] for r in before.items])


SOME = [800000 + n for n in range(1, PRODUCTS, 7)]
FORMS = {  # every form `has_product` takes: any product, a list, an uncorrelated select, a product outside a list
    "any": dict(),
    "list": dict(products=SOME),
    "select": dict(products=select(ProductoERP.item_id).where(ProductoERP.item_id % 5 == 0)),
    "outside": dict(outside=SOME),
    "list outside": dict(products=SOME[:40], outside=SOME[:20]),
}


@pytest.mark.parametrize("form", FORMS)
def test_every_form_selects_what_the_distinct_subquery_selected(session, form) -> None:
    def selected(predicate: Any) -> list[str]:
        query = select(filters.T.i.item_id).select_from(filters.T.i).where(predicate).order_by(filters.T.i.item_id)
        return list(session.execute(query).scalars())

    now = selected(filters.has_product(**FORMS[form]))
    assert now and now == selected(previous_has_product(**FORMS[form]))
