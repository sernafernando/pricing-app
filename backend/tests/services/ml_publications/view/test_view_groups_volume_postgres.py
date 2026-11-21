"""P7a + P7b: the Agrupado tree, with and without the node markup, on the volume of `test_view_volume_postgres.py`
(its seed, session and helpers), in its own module so CI's volume job (`--dist loadfile`) runs it on another worker.
Timings are printed and recorded in the PR, never asserted."""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.services.ml_publications.view import groups, listing, markup_service
from app.services.ml_publications.view.filters import build_base_select, parse_filter
from tests.services.ml_publications.view.test_view_markup_volume_postgres import (
    markup_page,
    priced,  # noqa: F401 -- fixture
)
from tests.services.ml_publications.view.test_view_volume_postgres import (  # noqa: F401 -- fixtures
    explain,
    page,
    seeded,
    session,
    timed,
)

# ruff: noqa: F811 -- the imported fixtures are the tests' parameters

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


def tree(session: Session, *path: str, familias: bool = False, **params):
    return groups.list_groups(session, parse_filter(**params), list(path), familias=familias, limit=100, offset=0)


class TestGroupsVolume:
    """P7a: one level of the Agrupado tree at 25k publications (budget p95 < 400 ms, proposed; production is
    measured with `scripts/measure_pubml_p7a.py`). Timings are printed and recorded in the PR, never asserted."""

    def deepest(self, session: Session) -> list[str]:
        """The path to the biggest products level: each step opens the biggest node of the level above."""
        path: list[str] = []
        for _ in range(3):
            nodes = tree(session, *path).nodes
            path.append(max((n for n in nodes if n.key != groups.NO_GROUP), key=lambda n: n.count).key)
        return path

    def test_the_levels_add_up_to_the_list_at_volume(self, session) -> None:
        roots = tree(session)
        assert roots.level == "marca" and roots.total == 6  # five brands and the publications with no product
        assert sum(n.count for n in roots.nodes) == page(session).total
        brand = max(roots.nodes, key=lambda n: n.count)
        assert sum(n.count for n in tree(session, brand.key).nodes) == brand.count

    def test_the_statement_count_is_fixed_at_every_level(self, session) -> None:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        path = self.deepest(session)
        counts = {}
        event.listen(session.get_bind(), "before_cursor_execute", record)
        try:
            for depth in range(4):
                recorded.clear()
                tree(session, *path[:depth], familias=True)
                counts[depth] = len(recorded)
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", record)
        print(f"\nstatements per level: {counts}")
        # The level's nodes, then their Tipo/Estado/Precio summaries: two statements, whatever the level.
        assert set(counts.values()) == {2}

    def test_timings(self, session) -> None:
        path = self.deepest(session)
        print(f"\n--- groups timings (service only, no HTTP), 25k publications, deepest path {path}")
        timed("roots (brands)", lambda: tree(session))
        timed("roots, store 2645", lambda: tree(session, tiendas="2645"))
        timed("roots, search 'router'", lambda: tree(session, q="router"))
        timed("categories of the biggest brand", lambda: tree(session, *path[:1]))
        timed("subcategories", lambda: tree(session, *path[:2]))
        timed("products (page of 100)", lambda: tree(session, *path))
        timed("products, families on", lambda: tree(session, *path, familias=True))
        timed("'Sin producto' products", lambda: tree(session, *[groups.NO_GROUP] * 3))
        plan = explain(session, build_base_select(parse_filter(), listing.func.count()))
        print("\n--- unfiltered count (what every level scans)\n" + plan)


def tree_with_markup(session: Session, *path: str, familias: bool = False, **params):
    query = markup_service.MarkupQuery(session)
    return groups.list_groups(
        session, parse_filter(**params), list(path), familias=familias, limit=100, offset=0, markup=query
    )


class TestGroupsMarkupVolume:
    """P7b: one level of the tree WITH the node markup figures at 25k publications (budget p95 < 1 s, proposed; production
    is measured with `scripts/measure_pubml_p7b.py`). Timings are printed and recorded in the PR, never asserted. The
    pricing context is hand-built and the shipping batch stubbed, as in `TestMarkupVolume`."""

    def test_the_figures_of_a_level_add_up_to_the_set_wide_markup(self, session, priced) -> None:
        roots = tree_with_markup(session)
        everything = markup_page(session, orden="markup", negative=True)
        assert sum(n.negative_count for n in roots.nodes) == everything.total
        assert all(n.negative_count is not None for n in roots.nodes)
        lows = [n.markup_min for n in roots.nodes if n.markup_min is not None]
        assert (
            round(min(lows), 2) == markup_page(session, orden="markup").items[0]["markup"]["worst"]
        )  # the list rounds

    def test_the_statement_count_does_not_depend_on_the_level(self, session, priced) -> None:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        path: list[str] = []
        for _ in range(3):
            nodes = tree_with_markup(session, *path).nodes
            path.append(max((n for n in nodes if n.key != groups.NO_GROUP), key=lambda n: n.count).key)
        counts = {}
        event.listen(session.get_bind(), "before_cursor_execute", record)
        try:
            for depth in range(4):
                recorded.clear()
                tree_with_markup(session, *path[:depth], familias=True)
                counts[depth] = len(recorded)
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", record)
        print(f"\nstatements per level with markup: {counts}")
        assert len(set(counts.values())) == 1

    def test_timings(self, session, priced) -> None:
        path: list[str] = []
        for _ in range(3):
            nodes = tree_with_markup(session, *path).nodes
            path.append(max((n for n in nodes if n.key != groups.NO_GROUP), key=lambda n: n.count).key)
        print(f"\n--- groups + markup timings (service only, no HTTP, no shipping batch), 25k, deepest path {path}")
        timed("roots (brands) + markup", lambda: tree_with_markup(session))
        timed("roots, store 2645 + markup", lambda: tree_with_markup(session, tiendas="2645"))
        timed("categories of the biggest brand + markup", lambda: tree_with_markup(session, *path[:1]))
        timed("subcategories + markup", lambda: tree_with_markup(session, *path[:2]))
        timed("products (page of 100) + markup", lambda: tree_with_markup(session, *path))
        timed("products, families on + markup", lambda: tree_with_markup(session, *path, familias=True))
        timed("  baseline: the same roots WITHOUT markup", lambda: tree(session))
