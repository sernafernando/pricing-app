"""The shipping step of the markup: the real resolver fed with the active publications as plain columns.

`resolver_costos_envio_batch` loaded every `PublicacionML` of the priced products as ORM entities (24k objects and
all their columns on a 25k-publication store, about 40% of a set-wide request) to read two attributes of each. The
markup now hands it a mapping built from the two columns it reads. The figures must not change.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.models.publicacion_ml import PublicacionML
from app.services import envio_real_service
from app.services.ml_publications.view import markup_service, markup_shipping
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_unit_markup import make_ctx

pytestmark = pytest.mark.postgres

COSTS = {"MLA1": 1000.0, "MLA2": 3000.0, "MLA3": 9999.0, "MLA4": 5000.0}


@pytest.fixture()
def conn(env):  # noqa: F811
    PublicacionML.__table__.create(bind=env)
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
def requested(monkeypatch) -> list[list[str]]:
    """The mlwebhook table, stubbed: records the MLAs asked for and answers from `COSTS`."""
    asked: list[list[str]] = []

    def fetch(mla_ids):
        asked.append(sorted(mla_ids))
        return {mla: COSTS[mla] for mla in mla_ids if mla in COSTS}

    monkeypatch.setattr(envio_real_service, "_fetch_list_cost_by_mla", fetch)
    return asked


def add_publication(conn, mla: str, product: int, activo: bool = True) -> None:
    conn.execute(
        text(
            "INSERT INTO publicaciones_ml (mla, item_id, codigo, item_title, pricelist_id, activo) "
            "VALUES (:mla, :item, 'C', 'a long title the shipping step never needs', 4, :activo)"
        ),
        {"mla": mla, "item": product, "activo": activo},
    )


def seed_publications(conn) -> None:
    for item_id in (70, 71, 72):
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}")
    add_publication(conn, "MLA1", 70)
    add_publication(conn, "MLA2", 70)
    add_publication(conn, "MLA3", 70, activo=False)  # inactive: its cost is never asked for
    add_publication(conn, "MLA4", 71, activo=False)
    # product 72 has no publication at all


class TestActivePublications:
    def test_it_holds_the_active_mlas_of_each_product(self, conn, db) -> None:
        seed_publications(conn)
        by_item = markup_shipping.ActivePublications(db, [70, 71, 72])
        assert sorted(pub.mla for pub in by_item.get(70, [])) == ["MLA1", "MLA2"]
        assert all(pub.activo for pub in by_item.get(70, []))
        assert by_item.get(71, []) == [] and by_item.get(72, []) == []

    def test_it_is_lazy_and_reads_two_columns_in_one_statement(self, conn, db) -> None:
        seed_publications(conn)
        recorded: list[str] = []

        def record(connection, cursor, statement, *rest) -> None:
            recorded.append(statement)

        by_item = markup_shipping.ActivePublications(db, [70, 71, 72])
        event.listen(db.get_bind(), "before_cursor_execute", record)
        try:
            assert recorded == []  # nothing is read until the resolver asks
            by_item.get(70, [])
            by_item.get(71, [])
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)
        assert len(recorded) == 1
        assert "item_title" not in recorded[0] and "codigo" not in recorded[0]
        assert "ANY" in recorded[0].upper()  # the ids travel as ONE array parameter, not one bind per product


class TestTheMarkupUsesIt:
    def test_the_figures_are_the_ones_of_the_orm_resolver(self, conn, db, requested, monkeypatch) -> None:
        seed_publications(conn)
        seed.add_cost(conn, 70, 50000.0)
        seed.add_item(conn, "MLA1", listing_type_id="gold_pro", price=90000)
        seed.add_link(conn, "MLA1", 70)
        monkeypatch.setattr(markup_service, "build_pricing_context", lambda session: make_ctx())

        def legacy(session, ids, **_ignored):
            return envio_real_service.resolver_costos_envio_batch(session, ids)

        with monkeypatch.context() as patch:
            patch.setattr(markup_service, "resolver_costos_envio_batch", legacy)
            before = markup_service.compute_markups(db, db, f=parse_filter()).items["MLA1"].markup
        asked_before = list(requested)
        requested.clear()
        after = markup_service.compute_markups(db, db, f=parse_filter()).items["MLA1"].markup
        assert after == before
        assert after.variations[0].costo_ars == 50000.0 and after.variations[0].value is not None
        assert requested == asked_before == [["MLA1", "MLA2"]]  # the inactive ones are never asked for
