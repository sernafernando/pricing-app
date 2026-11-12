"""Publicaciones ML with a PM, brand or category filter plus a promo filter (the MLA set of a promo type, e.g. DEAL),
on the 25k volume seed.

The incident (2026-11-12): PM + promo DEAL answered 503 `consulta_lenta`. The production log had two statements
cancelled by the list's 8 s `statement_timeout`: the brand facet (`SELECT nullif(upper(trim(coalesce(pl_p.marca,
...` with `count(distinct(i.item_id))`) and the Producto view's ids (`SELECT ids.product, count(*) OVER () AS
total`). Both carried a PM's (brand, category) pairs and `i.item_id = ANY(ARRAY[...])`, the promo's MLAs.

Two causes, both measured on this seed:

- `item_id = ANY(<thousands>)` is an index condition of `ml_items_pkey`, priced as one descent per MLA for every
  probe. When the PM / brand / category filter underestimates its rows (Postgres keeps no statistics for
  `upper(trim(...))`), the planner probes `ml_items` once per linked publication through `ix_ml_items_last_trigger`
  by its NON-leading `item_id`: a whole-index walk per row. A PM with many pairs + the promo went over the 8 s
  timeout here, as in production. `filters._item_in` compares `item_id || ''`, a hashed filter, never an index
  condition.
- JIT compiled those statements (priced near a million by their correlated subqueries) for about 1.1 s each:
  `listing.bound` turns it off for the view's transaction.

Pinned: every read answers exactly what the previous shape answered, no statement of the list, its facets, the
tree or the Producto view's ids walks `ix_ml_items_last_trigger` by `item_id`, and JIT is off. Timings are not
asserted (a shared CI box), the plan shape is.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable, Iterator

import pytest
from sqlalchemy import String, any_, event, false, literal, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, sessionmaker

from app.services.ml_publications.view import filters, groups, listing, products
from app.services.ml_publications.view.filters import PublicationFilter, parse_filter
from tests.services.ml_publications.view.test_view_volume_postgres import seeded  # noqa: F401

pytestmark = [pytest.mark.postgres, pytest.mark.volume]

# A promo type's MLAs: every third publication of the seed (8333), the size of a large DEAL set.
PROMO_SCOPE = frozenset(f"MLA{1000000 + i}" for i in range(1, 25_000) if i % 3 == 0)
PM_PAIRS_DDL = (
    "CREATE TABLE marcas_pm (id serial PRIMARY KEY, marca varchar(100) NOT NULL, categoria varchar(100) NOT NULL, "
    "usuario_id integer, fecha_asignacion timestamptz, fecha_modificacion timestamptz)"
)
PM_PAIRS = (
    "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES "
    "('TP-Link', 'Cat0', 1), ('TP-Link', 'Cat1', 1), (' tenda ', 'cat2', 1), ('Sony', 'Cat0', 1), ('Epson', 'Cat1', 2), "
    # a production PM owns dozens of pairs (the cancelled statements carried about 60): one with most of the seed's
    "('TP-Link', 'Cat0', 3), ('TP-Link', 'Cat1', 3), ('TP-Link', 'Cat2', 3), ('Hikvision', 'Cat0', 3), "
    "('Hikvision', 'Cat2', 3), ('Tenda', 'Cat1', 3), ('Tenda', 'Cat2', 3), ('Epson', 'Cat0', 3), ('Epson', 'Cat1', 3), "
    "('Sony', 'Cat1', 3), ('Sony', 'Cat2', 3), ('Nope', 'Cat0', 3)"
)
SCENARIOS = {
    "pm+promo": dict(pms="1"),
    "big pm+promo": dict(pms="3"),
    "big pm+promo+search": dict(pms="3", q="Producto de volumen 12"),
    "pm": dict(pms="1"),
    "marca+promo": dict(marcas="TP-Link"),
    "categoria+promo": dict(categorias="Cat0"),
    "catalog+promo": dict(marcas="TP-Link,Sony", categorias="Cat0", pms="1", subcategorias="1,3,4"),
    "promo": {},
}


@pytest.fixture(scope="module")
def with_pms(seeded):  # noqa: F811
    with seeded.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(PM_PAIRS_DDL))
        conn.execute(text(PM_PAIRS))
    return seeded


@pytest.fixture()
def session(with_pms) -> Iterator[Session]:
    session = sessionmaker(bind=with_pms, autocommit=False, autoflush=False)()
    try:
        listing.bound(session)  # as every read of the router: statement_timeout and jit = off
        yield session
    finally:
        session.rollback()
        session.close()


def scenario(session: Session, name: str) -> PublicationFilter:
    f = parse_filter(**SCENARIOS[name])
    if name != "pm":
        f = replace(f, mla_scope=PROMO_SCOPE)
    return listing.resolve_pm_pairs(session, f)


def view_reads(session: Session, f: PublicationFilter) -> list[tuple[str, Callable[[], Any]]]:
    """The reads a filter change triggers: the list page, its facets, the tree's roots and its biggest root, and
    the Producto view's ids."""
    roots = groups.list_groups(session, f, [], limit=100, offset=0).nodes
    biggest = [max(roots, key=lambda n: n.count).key] if roots else []
    return [
        ("items page", lambda: listing.list_items(session, f, listing.parse_sort(None, None), 50, 0, events=True)),
        ("facets", lambda: listing.facets(session, f, None)),
        ("tree roots", lambda: groups.list_groups(session, f, [], limit=100, offset=0)),
        ("tree level 2", lambda: groups.list_groups(session, f, biggest, limit=100, offset=0)),
        ("product ids", lambda: products.product_ids(session, f)),
    ]


def statements(session: Session, call: Callable[[], Any]) -> list[tuple[str, Any]]:
    """The SELECTs `call` sends, with their parameters, as the cursor got them."""
    sent: list[tuple[str, Any]] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            sent.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        call()
    finally:
        event.remove(bind, "before_cursor_execute", record)
    return sent


def plan(session: Session, statement: str, parameters: Any) -> dict[str, Any]:
    cursor = session.connection().connection.cursor()
    try:
        cursor.execute("EXPLAIN (FORMAT JSON) " + statement, parameters)
        document = cursor.fetchone()[0]
    finally:
        cursor.close()
    return (json.loads(document) if isinstance(document, str) else document)[0]


def nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", ()):
        yield from nodes(child)


def per_row_walks(document: dict[str, Any]) -> list[str]:
    """Index scans of `ix_ml_items_last_trigger` that look an `item_id` up: that index leads with
    `last_trigger_received_at`, so such a probe walks the whole index, once per outer row."""
    return [
        node["Index Cond"]
        for node in nodes(document["Plan"])
        if node.get("Index Name") == "ix_ml_items_last_trigger"
        and "item_id" in node.get("Index Cond", "")
        and "last_trigger_received_at" not in node.get("Index Cond", "")
    ]


def answers(session: Session, f: PublicationFilter) -> dict[str, Any]:
    """What a viewer sees for `f`: every read's result, comparable."""
    page = listing.list_items(session, f, listing.parse_sort(None, None), 50, 0, events=True)
    roots = groups.list_groups(session, f, [], limit=100, offset=0)
    ids = products.product_ids(session, f)
    return {
        "total": page.total,
        "page": [row["item_id"] for row in page.items],
        "roots": sorted((n.key, n.count) for n in roots.nodes),
        "levels": {
            n.key: sorted((m.key, m.count) for m in groups.list_groups(session, f, [n.key], limit=100, offset=0).nodes)
            for n in roots.nodes
        },
        "facets": listing.facets(session, f, None),
        "product ids": ids,
    }


def bare_item_in(mlas: frozenset[str]) -> Any:
    """The previous `_item_in`: the oracle of what the view answered before the fix."""
    return filters.T.i.item_id == any_(literal(sorted(mlas), ARRAY(String))) if mlas else false()


class TestTheResultsAreUnchanged:
    @pytest.mark.parametrize("name", list(SCENARIOS))
    def test_every_read_answers_what_the_previous_shape_answered(self, session, name, monkeypatch) -> None:
        session.execute(text("SET LOCAL statement_timeout = '120s'"))  # the old shape is the slow one
        f = scenario(session, name)
        now = answers(session, f)
        monkeypatch.setattr(filters, "_item_in", bare_item_in)
        before = answers(session, f)
        assert now == before
        assert now["total"] > 0

    def test_pm_plus_promo_counts_what_main_counted(self, session) -> None:
        """Measured on main before the fix, same seed."""
        roots = groups.list_groups(session, scenario(session, "pm+promo"), [], limit=100, offset=0)
        assert sorted((n.key, n.count) for n in roots.nodes) == [("SONY", 513), ("TENDA", 342), ("TP-LINK", 858)]

    def test_the_listed_publications_are_the_promos(self, session) -> None:
        page = listing.list_items(
            session, scenario(session, "pm+promo"), listing.parse_sort(None, None), 50, 0, events=True
        )
        assert page.items and {row["item_id"] for row in page.items} <= PROMO_SCOPE


class TestThePlanShape:
    def test_jit_is_off_in_the_view_transaction(self, session) -> None:
        assert session.execute(text("SHOW jit")).scalar() == "off"

    def test_the_promo_set_is_a_filter_not_an_index_condition(self, session) -> None:
        compiled = filters._item_in(PROMO_SCOPE).compile(dialect=session.get_bind().dialect)
        assert str(compiled).startswith("(i.item_id || ")

    @pytest.mark.parametrize("name", list(SCENARIOS))
    def test_no_read_walks_the_activity_index_once_per_row(self, session, name) -> None:
        f = scenario(session, name)
        found = {}
        for label, read in view_reads(session, f):
            for statement, parameters in statements(session, read):
                document = plan(session, statement, parameters)
                assert "JIT" not in document
                walks = per_row_walks(document)
                if walks:
                    found[label] = walks
        assert found == {}
