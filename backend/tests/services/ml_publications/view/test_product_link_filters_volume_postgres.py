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
from sqlalchemy import ARRAY, Integer, Select, all_, and_, any_, event, exists, literal, or_, select, text
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.models.ml_publications import MlItemProductLink, MlItemVariation
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


def previous_product_links(name: str) -> Any:
    """main's `product_links`, verbatim (not through `_live_links`, so the oracle does not test the rule by itself)."""
    link, var = aliased(MlItemProductLink, name=f"{name}_l"), aliased(MlItemVariation, name=f"{name}_v")
    live = or_(link.variation_id == filters.LINK_ITEM_LEVEL, and_(var.variation_id.isnot(None), var.gone_at.is_(None)))
    return (
        select(link.item_id, link.producto_item_id)
        .select_from(link)
        .outerjoin(var, and_(var.item_id == link.item_id, var.variation_id == link.variation_id))
        .where(link.producto_item_id.isnot(None), live)
        .distinct()
        .subquery(name)
    )


def previous_has_product(products: Any = None, *, outside: Any = None) -> Any:
    """main's `has_product`: an `EXISTS` over the `DISTINCT` `product_links` subquery."""
    pl = previous_product_links("pl_filter_previous")
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


# The 25k seed links each item once, at item level. These shapes, on items the seed leaves unlinked (20001+, no
# variations), reach the other branches of the live-link rule: (item, variation, product, variation gone).
A, B = SOME[0], SOME[1]  # in `SOME` (a list, and `outside`)
C = 800000 + PRODUCTS - 1  # not in `SOME`
D = SOME[22]  # in `SOME[:40]`, not in `SOME[:20]`, a multiple of 5 (the `select` form)
SHAPES = {
    "MLA1020001": [(1, A, False), (2, D, False)],  # two live variations, two products
    "MLA1020002": [(1, A, True)],  # its only variation gone: unlinked
    "MLA1020003": [(1, A, True), (2, C, False)],  # one gone, one live: linked to the live one's only
    "MLA1020004": [(0, None, None)],  # an item-level link with no product (unmatched): unlinked
    "MLA1020005": [(7, A, None)],  # a variation link with no variation row: unlinked
    "MLA1020006": [(0, B, None), (1, B, False), (2, C, False)],  # item level and variations, a product twice
    "MLA1020007": [(1, A, False), (2, A, False)],  # two variations, the same product
    "MLA1020008": [(0, A, None), (1, C, True)],  # item level, plus a gone variation's link
}
LINKED_SHAPES = {"MLA1020001", "MLA1020003", "MLA1020006", "MLA1020007", "MLA1020008"}


def add_shapes(session: Session) -> None:
    for item_id, units in SHAPES.items():
        for variation_id, product, gone in units:
            if gone is not None:
                session.execute(
                    text(
                        "INSERT INTO ml_item_variations (item_id, variation_id, raw, raw_hash, fetched_at, gone_at) "
                        "VALUES (:item, :variation, '{}'::jsonb, '\\x00', now(), "
                        "CASE WHEN CAST(:gone AS boolean) THEN now() END)"
                    ),
                    dict(item=item_id, variation=variation_id, gone=gone),
                )
            session.execute(
                text(
                    "INSERT INTO ml_item_product_links (item_id, variation_id, source, match_status, "
                    "producto_item_id, linked_at) VALUES (:item, :variation, 'manual', "
                    "CASE WHEN CAST(:product AS integer) IS NULL THEN 'unmatched' ELSE 'linked' END, :product, now())"
                ),
                dict(item=item_id, variation=variation_id, product=product),
            )


@pytest.mark.parametrize("form", FORMS)
def test_every_form_selects_what_the_distinct_subquery_selected(session, form) -> None:
    add_shapes(session)  # rolled back with the session

    def selected(predicate: Any) -> list[str]:
        query = select(filters.T.i.item_id).select_from(filters.T.i).where(predicate).order_by(filters.T.i.item_id)
        return list(session.execute(query).scalars())

    now = selected(filters.has_product(**FORMS[form]))
    assert now and now == selected(previous_has_product(**FORMS[form]))
    assert any(item_id in SHAPES for item_id in now)  # the shapes reach every form


def test_the_shapes_are_linked_by_the_live_link_rule(session) -> None:
    add_shapes(session)
    query = select(filters.T.i.item_id).where(filters.T.i.item_id.in_(SHAPES), filters.has_product())
    assert set(session.execute(query).scalars()) == LINKED_SHAPES
