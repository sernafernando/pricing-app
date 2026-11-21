"""P6.T6: the list sorted and filtered by markup on the volume of `test_view_volume_postgres.py` (its seed,
session and helpers), in its own module so CI's volume job (`--dist loadfile`) runs it on another worker. Timings are
printed and recorded in the PR, never asserted."""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.services.envio_real_service import CostosEnvio
from app.services.ml_publications.view import listing, markup_inputs, markup_service, products
from app.services.ml_publications.view.filters import MarkupFilter, parse_filter
from tests.services.ml_publications.view.test_unit_markup import BASE_BY_GRUPO, make_ctx
from tests.services.ml_publications.view.test_view_volume_postgres import (  # noqa: F401 -- fixtures
    ITEMS,
    seeded,
    session,
    timed,
)

# ruff: noqa: F811 -- the imported fixtures are the tests' parameters

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


PRICING_CTX = make_ctx(subcat_to_grupo={n: (1, 4, 6, 10)[n % 4] for n in range(1, 8)}, comision_base=BASE_BY_GRUPO)


@pytest.fixture()
def priced(monkeypatch):
    """The pricing context is hand-built and the shipping batch is stubbed: the database cost of the markup is
    what is measured here (the cross-database shipping lookup can only be measured on production)."""
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: PRICING_CTX)
    monkeypatch.setattr(markup_service, "resolver_costos_envio_mlas", lambda db, ids, mlas, **k: CostosEnvio())


def markup_page(session: Session, limit: int = 50, offset: int = 0, **params):
    f = parse_filter(**{k: v for k, v in params.items() if k not in ("orden", "dir", "negative")})
    sort = listing.parse_sort(params.get("orden"), params.get("dir"))
    query = markup_service.MarkupQuery(session, MarkupFilter(negative=params.get("negative", False)))
    return listing.list_items(session, f, sort, limit, offset, events=True, markup=query)


class TestMarkupVolume:
    def test_the_set_wide_markup_sort_prices_every_linked_publication(self, session, priced) -> None:
        result = markup_page(session, orden="markup")
        assert result.total == ITEMS - ITEMS // 50  # gone items are hidden
        stats = result.markup_stats
        unpriced = dict(stats.null_by_reason)
        print(f"\nmarkup stats at 25k: computed={stats.computed} ms={stats.ms} null_by_reason={unpriced}")
        assert stats.computed > 10_000  # the linked, priceable ones
        assert {"sin_vinculo"} <= set(stats.null_by_reason)
        worst = [row["markup"]["worst"] for row in result.items]
        assert worst == sorted(worst)  # the page is the lowest markups, ascending

    def test_the_statement_count_does_not_depend_on_the_page_size_with_markup(self, session, priced) -> None:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        engine = session.get_bind()
        counts: dict[tuple, int] = {}
        event.listen(engine, "before_cursor_execute", record)
        try:
            for label, params in (("page", {}), ("sort", {"orden": "markup"}), ("neg", {"negative": True})):
                for limit in (10, 100):
                    recorded.clear()
                    assert len(markup_page(session, limit=limit, **params).items) == limit
                    counts[(label, limit)] = len(recorded)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        print(f"\nstatements with markup: {counts}")
        for label in ("page", "sort", "neg"):
            assert counts[(label, 10)] == counts[(label, 100)]

    def test_markup_timings(self, session, priced) -> None:
        print("\n--- markup timings (service only, no HTTP, no shipping batch), 25k publications")
        timed("page of 50 + markup (default sort)", lambda: markup_page(session))
        timed("Todos page (limit 9999) + markup", lambda: markup_page(session, limit=9_999))
        timed("orden=markup, page 1 (set-wide)", lambda: markup_page(session, orden="markup"))
        timed("orden=markup, page 200 (offset 10k)", lambda: markup_page(session, orden="markup", offset=10_000))
        timed("markup_neg=true, sort titulo (set-wide)", lambda: markup_page(session, negative=True, orden="titulo"))
        timed(
            "orden=markup + estado=active + tienda 2645",
            lambda: markup_page(session, orden="markup", estado="active", tiendas="2645"),
        )
        timed(
            "product-ids markup_neg=true (bulk resolver, set-wide)",
            lambda: products.product_ids(
                session, parse_filter(), markup_service.MarkupQuery(session, MarkupFilter(negative=True))
            ),
        )
        timed("product-ids, no markup filter", lambda: products.product_ids(session, parse_filter()))
        f = parse_filter()
        timed("  stage: inputs of the whole set (3 statements)", lambda: markup_inputs.fetch_inputs(session, f=f))
        inputs = markup_inputs.fetch_inputs(session, f=f)
        timed(
            "  stage: pricing loop over the whole set",
            lambda: [markup_service.price_publication(PRICING_CTX, pub, {}) for pub in inputs.values()],
        )
