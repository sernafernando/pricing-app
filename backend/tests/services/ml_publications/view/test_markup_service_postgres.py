"""P6.T2: the markup of a page or a filtered set, from the stored publications to `PublicationMarkup`.

The page path (explicit ids) and the set-wide path (a filter) must give identical values; the real shipping
costs are resolved in ONE batch per request; whatever cannot be priced says why and is never 0. The maths itself
is `unit_markup`'s (P2) and the pricing context is built by hand, as in `test_unit_markup.py`.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.ml_publications.view import markup_service
from app.services.ml_publications.view.filters import parse_filter
from app.services.ml_publications.view.markup import aggregate_publication, unit_markup
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs

pytestmark = pytest.mark.postgres

ENVIO = {70: 1500.0}


@pytest.fixture()
def conn(env):  # noqa: F811
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
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


@pytest.fixture()
def envio_calls(monkeypatch):
    """The real-shipping batch, counted: (db, product ids) per call."""
    calls: list[tuple] = []

    def fake(session, product_ids, **kwargs):
        calls.append((session, list(product_ids)))
        return {k: v for k, v in ENVIO.items() if k in product_ids}

    monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", fake)
    return calls


def terms(campaign: str) -> str:
    return json.dumps({"sale_terms": [{"id": "INSTALLMENTS_CAMPAIGN", "value_name": campaign}]})


def seed_catalog(conn) -> None:
    for item_id, costo in ((70, 50000.0), (72, 80000.0)):
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", subcategoria_id=3845)
        seed.add_cost(conn, item_id, costo)
    seed.add_product(conn, 71, "C71", "Sin costo", subcategoria_id=3845)  # cost never loaded
    # MLA1: priced on the 9x list with a sale price.
    seed.add_item(conn, "MLA1", listing_type_id="gold_pro", tags=["9x_campaign"], price=90000)
    seed.add_sale_price(conn, "MLA1", 100000)
    seed.add_link(conn, "MLA1", 70)
    # MLA2: no link at all.
    seed.add_item(conn, "MLA2", listing_type_id="gold_pro", price=90000)
    # MLA3: linked to a product without cost.
    seed.add_item(conn, "MLA3", listing_type_id="gold_pro", price=90000)
    seed.add_link(conn, "MLA3", 71)
    # MLA4: a listing type without a list of ours.
    seed.add_item(conn, "MLA4", listing_type_id="free", price=90000)
    seed.add_link(conn, "MLA4", 70)
    # MLA5: ML co-funds the installments.
    seed.add_item(conn, "MLA5", listing_type_id="gold_special", tags=["pcj-co-funded"], price=90000)
    seed.add_link(conn, "MLA5", 70)
    # MLA6: nothing to price with.
    seed.add_item(conn, "MLA6", listing_type_id="gold_pro")
    seed.add_link(conn, "MLA6", 70)
    # MLA7: two variations on two products, campaign only in the sale term.
    seed.add_item(conn, "MLA7", listing_type_id="gold_pro", price=120000, raw=terms("12x_campaign"))
    seed.add_variation(conn, "MLA7", 11)
    seed.add_variation(conn, "MLA7", 12)
    seed.add_link(conn, "MLA7", 70, variation_id=11)
    seed.add_link(conn, "MLA7", 72, variation_id=12)


class TestValues:
    def test_a_linked_publication_is_the_unit_markup_of_its_stored_inputs(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        ctx = make_ctx()
        got = markup_service.compute_markups(db, db, ctx=ctx, item_ids=["MLA1"]).items["MLA1"].markup
        expected = unit_markup(ctx, make_inputs(producto_item_id=70), ENVIO)
        assert expected.value is not None and expected.reason == "ok"
        assert got.worst == got.value_min == got.value_max == expected.value
        assert got.reason == "ok" and got.any_negative is (expected.value < 0) and got.partial == 0

    def test_variations_on_two_products_give_a_range_and_the_worst_drives_the_summary(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        ctx = make_ctx()
        got = markup_service.compute_markups(db, db, ctx=ctx, item_ids=["MLA7"]).items["MLA7"].markup
        common = dict(item_id="MLA7", sale_price=None, item_price=120000.0, tags=(), sale_terms_campaign="12x_campaign")
        low = unit_markup(ctx, make_inputs(producto_item_id=72, costo=80000.0, **common), ENVIO)
        high = unit_markup(ctx, make_inputs(producto_item_id=70, costo=50000.0, **common), ENVIO)
        assert got.is_range and got.value_min == low.value and got.value_max == high.value
        assert got.worst == low.value

    @pytest.mark.parametrize(
        "item_id, reason",
        [
            ("MLA2", "sin_vinculo"),
            ("MLA3", "sin_costo"),
            ("MLA4", "sin_lista"),
            ("MLA5", "cofinanciada"),
            ("MLA6", "sin_precio"),
        ],
    )
    def test_what_cannot_be_priced_says_why_and_is_never_zero(self, conn, db, envio_calls, item_id, reason) -> None:
        seed_catalog(conn)
        got = markup_service.compute_markups(db, db, ctx=make_ctx(), item_ids=[item_id]).items[item_id].markup
        assert got.reason == reason
        assert (got.worst, got.value_min, got.value_max) == (None, None, None)
        assert got.any_negative is False

    def test_a_context_without_an_active_commission_version_is_sin_comision(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        ctx = make_ctx(active_version_id=None)
        got = markup_service.compute_markups(db, db, ctx=ctx, item_ids=["MLA1"]).items["MLA1"].markup
        assert got.reason == "sin_comision" and got.worst is None

    def test_the_result_names_the_variation_of_each_unit(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        got = markup_service.compute_markups(db, db, ctx=make_ctx(), item_ids=["MLA7", "MLA1"]).items
        assert got["MLA7"].variation_ids == (11, 12) and len(got["MLA7"].markup.variations) == 2
        assert got["MLA1"].variation_ids == ()  # no variations: the item-level unit is the whole publication

    def test_a_missing_item_is_absent(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        assert markup_service.compute_markups(db, db, ctx=make_ctx(), item_ids=["MLA404"]).items == {}


class TestPageAndSetWideAgree:
    def test_the_page_path_and_the_set_wide_path_give_identical_values(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        ctx = make_ctx()
        everything = [f"MLA{n}" for n in range(1, 8)]
        by_page = markup_service.compute_markups(db, db, ctx=ctx, item_ids=everything)
        by_set = markup_service.compute_markups(db, db, ctx=ctx, f=parse_filter())
        assert set(by_page.items) == set(by_set.items) == set(everything)
        for item_id in everything:
            assert by_page.items[item_id].markup == by_set.items[item_id].markup, item_id

    def test_a_subset_gets_the_same_values_as_inside_the_whole_set(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        ctx = make_ctx()
        whole = markup_service.compute_markups(db, db, ctx=ctx, f=parse_filter())
        part = markup_service.compute_markups(db, db, ctx=ctx, item_ids=["MLA1", "MLA7"])
        assert part.items["MLA1"].markup == whole.items["MLA1"].markup
        assert part.items["MLA7"].markup == whole.items["MLA7"].markup


class TestEnvioBatch:
    def test_the_real_shipping_cost_is_resolved_once_per_request_for_the_distinct_products(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        markup_service.compute_markups(db, db, ctx=make_ctx(), f=parse_filter())
        assert len(envio_calls) == 1
        session, product_ids = envio_calls[0]
        assert session is db
        assert product_ids == [70, 72]  # distinct, sorted; the product without cost is never priced

    def test_the_pricing_session_is_the_one_the_batch_and_the_context_use(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        other = object()
        markup_service.compute_markups(db, other, ctx=make_ctx(), item_ids=["MLA1"])  # type: ignore[arg-type]
        assert envio_calls[0][0] is other

    def test_a_missing_envio_falls_back_exactly_like_productos(self, conn, db, monkeypatch) -> None:
        seed_catalog(conn)
        ctx = make_ctx()
        monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", lambda *a, **k: {})
        got = markup_service.compute_markups(db, db, ctx=ctx, item_ids=["MLA1"]).items["MLA1"].markup
        assert got.worst == unit_markup(ctx, make_inputs(producto_item_id=70), {}).value

    def test_no_priceable_product_makes_no_batch_call_with_ids(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        markup_service.compute_markups(db, db, ctx=make_ctx(), item_ids=["MLA2"])
        assert all(ids == [] for _, ids in envio_calls)
        assert len(envio_calls) <= 1


class TestStats:
    def test_stats_count_what_was_priced_and_why_the_rest_was_not(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        stats = markup_service.compute_markups(db, db, ctx=make_ctx(), f=parse_filter()).stats
        assert stats.computed == 2  # MLA1 and MLA7
        assert stats.null_by_reason == {
            "sin_vinculo": 1,
            "sin_costo": 1,
            "sin_lista": 1,
            "cofinanciada": 1,
            "sin_precio": 1,
        }
        assert stats.ms >= 0

    def test_the_variations_without_a_value_of_a_priced_publication_are_partial(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        seed.add_item(conn, "MLA8", listing_type_id="gold_pro", price=90000)
        seed.add_variation(conn, "MLA8", 31)
        seed.add_variation(conn, "MLA8", 32)
        seed.add_link(conn, "MLA8", 70, variation_id=31)
        got = markup_service.compute_markups(db, db, ctx=make_ctx(), item_ids=["MLA8"]).items["MLA8"].markup
        own = make_inputs(item_id="MLA8", producto_item_id=70, sale_price=None, tags=(), sale_terms_campaign=None)
        expected = aggregate_publication(None, [unit_markup(make_ctx(), own, ENVIO), None])
        assert got.partial == 1 and got.reason == "ok"
        assert got.worst == expected.worst
