"""P6.T1: the markup INPUTS of a set of publications, read in a constant number of statements.

Runs over the real store migrations in a throwaway schema (`env`) plus `productos_erp` (from the model) and a
minimal `productos_pricing` (only the price columns the fallback reads). The service only EXTRACTS: pricing is
`unit_markup`'s job (P2), so these tests pin what is read and how it is shaped, not any markup figure.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.services.ml_publications.view import markup_inputs
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres


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


def terms(campaign: str) -> str:
    return json.dumps({"sale_terms": [{"id": "INSTALLMENTS_CAMPAIGN", "value_name": campaign}]})


class TestItemLevelInputs:
    def test_a_linked_item_carries_the_price_listing_and_product_cost_inputs(self, conn, db) -> None:
        seed.add_product(conn, 70, "A1", "Router", subcategoria_id=3845)
        seed.add_cost(conn, 70, 50000.0, moneda_costo="USD", iva=10.5, envio=1200.0)
        seed.add_pricing(conn, 70, precio_lista_ml=111.5, precio_6_cuotas=222.25)
        seed.add_item(conn, "MLA1", listing_type_id="gold_pro", price=90000, tags=["9x_campaign", "other"])
        seed.add_sale_price(conn, "MLA1", 100000)
        seed.add_link(conn, "MLA1", 70)
        inputs = markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"]
        unit = inputs.item_unit
        assert (unit.item_id, unit.listing_type_id, tuple(unit.tags)) == ("MLA1", "gold_pro", ("9x_campaign", "other"))
        assert (unit.sale_price, unit.item_price) == (100000.0, 90000.0)
        assert (unit.producto_item_id, unit.costo, unit.moneda_costo) == (70, 50000.0, "USD")
        assert (unit.iva, unit.envio, unit.subcategoria_id) == (10.5, 1200.0, 3845)
        assert unit.fallback_prices["precio_lista_ml"] == 111.5
        assert unit.fallback_prices["precio_6_cuotas"] == 222.25
        assert unit.fallback_prices["precio_3_cuotas"] is None
        assert inputs.variation_units == ()

    def test_a_failed_or_gone_sale_price_is_not_an_input(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=10)
        seed.add_sale_price(conn, "MLA1", 99, http_status=404)
        seed.add_item(conn, "MLA2", price=20)
        seed.add_sale_price(conn, "MLA2", 88, gone_at=seed.NOW)
        got = markup_inputs.fetch_inputs(db, item_ids=["MLA1", "MLA2"])
        assert got["MLA1"].item_unit.sale_price is None and got["MLA1"].item_unit.item_price == 10.0
        assert got["MLA2"].item_unit.sale_price is None

    def test_an_item_without_a_link_is_a_unit_with_no_product(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=10)
        unit = markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].item_unit
        assert unit.producto_item_id is None and unit.costo is None

    def test_the_table_never_pairs_a_product_with_a_status_other_than_linked(self, conn) -> None:
        """The invariant the item-level read relies on (it does not filter `match_status`, like the list)."""
        seed.add_product(conn, 70, "A1", "Router")
        seed.add_item(conn, "MLA1")
        with pytest.raises(IntegrityError):
            seed.add_link(conn, "MLA1", 70, match_status="conflict")

    def test_a_conflicting_link_gives_no_product(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=10)
        seed.add_link(conn, "MLA1", None, match_status="conflict")
        assert markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].item_unit.producto_item_id is None

    def test_a_product_without_a_cost_keeps_the_missing_cost(self, conn, db) -> None:
        seed.add_product(conn, 70, "A1", "Router")
        seed.add_cost(conn, 70, None)
        seed.add_item(conn, "MLA1", price=10)
        seed.add_link(conn, "MLA1", 70)
        unit = markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].item_unit
        assert unit.producto_item_id == 70 and unit.costo is None

    def test_unknown_ids_are_absent_and_no_ids_is_empty(self, conn, db) -> None:
        seed.add_item(conn, "MLA1")
        assert set(markup_inputs.fetch_inputs(db, item_ids=["MLA1", "MLA404"])) == {"MLA1"}
        assert markup_inputs.fetch_inputs(db, item_ids=[]) == {}


class TestCampaign:
    def test_without_a_campaign_tag_the_installments_sale_term_is_the_campaign(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", tags=["good_quality_picture"], raw=terms("12x_campaign"))
        assert markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].item_unit.sale_terms_campaign == "12x_campaign"

    def test_a_campaign_tag_wins_and_the_sale_term_is_not_extracted(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", tags=["3x_campaign"], raw=terms("12x_campaign"))
        assert markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].item_unit.sale_terms_campaign is None

    def test_no_tags_no_sale_terms_is_no_campaign(self, conn, db) -> None:
        seed.add_item(conn, "MLA1")
        unit = markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].item_unit
        assert unit.sale_terms_campaign is None and tuple(unit.tags) == ()


class TestVariations:
    def test_each_live_variation_has_its_own_link_or_none(self, conn, db) -> None:
        for item_id, codigo in ((70, "A"), (71, "B")):
            seed.add_product(conn, item_id, codigo, f"Producto {codigo}")
            seed.add_cost(conn, item_id, 100.0 * item_id)
        seed.add_item(conn, "MLA1", price=10)
        seed.add_variation(conn, "MLA1", 11)
        seed.add_variation(conn, "MLA1", 12)
        seed.add_variation(conn, "MLA1", 13)
        seed.add_variation(conn, "MLA1", 14, gone_at=seed.NOW)  # dropped by ML: not a unit
        seed.add_link(conn, "MLA1", 70)  # item level
        seed.add_link(conn, "MLA1", 71, variation_id=12)
        inputs = markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"]
        assert inputs.item_unit.producto_item_id == 70
        assert [u.producto_item_id if u else None for u in inputs.variation_units] == [None, 71, None]
        assert inputs.variation_units[1].costo == 7100.0
        assert inputs.variation_ids == (11, 12, 13)  # the id of each entry of `variation_units`, same order

    def test_variation_units_share_the_publication_price_and_listing_inputs(self, conn, db) -> None:
        seed.add_product(conn, 71, "B", "Producto B")
        seed.add_item(conn, "MLA1", listing_type_id="gold_special", price=55)
        seed.add_variation(conn, "MLA1", 12)
        seed.add_link(conn, "MLA1", 71, variation_id=12)
        unit = markup_inputs.fetch_inputs(db, item_ids=["MLA1"])["MLA1"].variation_units[0]
        assert (unit.item_id, unit.listing_type_id, unit.item_price) == ("MLA1", "gold_special", 55.0)


class TestScope:
    def test_a_filter_scopes_the_set_like_the_list_does(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", status="active")
        seed.add_item(conn, "MLA2", status="paused")
        seed.add_item(conn, "MLA3", status="active", gone_at=seed.NOW)  # gone items are hidden by default
        got = markup_inputs.fetch_inputs(db, f=parse_filter(estado="active"))
        assert set(got) == {"MLA1"}
        assert set(markup_inputs.fetch_inputs(db, f=parse_filter())) == {"MLA1", "MLA2"}

    def test_exactly_one_scope_is_required(self, db) -> None:
        with pytest.raises(ValueError):
            markup_inputs.fetch_inputs(db)
        with pytest.raises(ValueError):
            markup_inputs.fetch_inputs(db, item_ids=["MLA1"], f=parse_filter())


class TestStatementCount:
    def seed_items(self, conn, count: int) -> list[str]:
        seed.add_product(conn, 70, "A1", "Router")
        seed.add_cost(conn, 70, 100.0)
        ids = []
        for number in range(count):
            item_id = f"MLA{number + 1}"
            ids.append(item_id)
            seed.add_item(conn, item_id, price=10 + number, tags=["9x_campaign"])
            seed.add_link(conn, item_id, 70)
            seed.add_variation(conn, item_id, 1)
            seed.add_link(conn, item_id, 70, variation_id=1)
        return ids

    def count_statements(self, db, **scope) -> int:
        recorded: list[str] = []

        def record(connection, cursor, statement, *rest) -> None:
            recorded.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            markup_inputs.fetch_inputs(db, **scope)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(recorded)

    def test_ten_rows_and_a_hundred_rows_cost_the_same_number_of_statements(self, conn, db) -> None:
        ids = self.seed_items(conn, 100)
        by_ids = {n: self.count_statements(db, item_ids=ids[:n]) for n in (10, 100)}
        by_filter = self.count_statements(db, f=parse_filter())
        assert len(markup_inputs.fetch_inputs(db, item_ids=ids)) == 100
        assert by_ids[10] == by_ids[100] == by_filter
