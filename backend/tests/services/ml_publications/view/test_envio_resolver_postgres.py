"""`resolver_costos_envio_batch` against a real publication mirror: what it returns, and what it reads to get there.

The resolver needs only the MLAs of the ACTIVE publications of each product. Left to load them itself it built one
`PublicacionML` entity per publication, every column of it (24k entities on a 25k-publication store, about 0.5 s) to
read `item_id`, `mla` and `activo`. It now selects those columns, in one statement.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.models.publicacion_ml import PublicacionML
from app.services import envio_real_service
from app.services.envio_real_service import resolver_costos_envio_batch
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

COSTS = {"MLA1": 1000.0, "MLA2": 3000.0, "MLA3": 9999.0, "MLA5": 700.0, "MLA6": 800.0}


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
    for item_id in (70, 71, 72, 73, 74):
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}")
    add_publication(conn, "MLA1", 70)  # product 70: several MLAs, the dearest one wins
    add_publication(conn, "MLA2", 70)
    add_publication(conn, "MLA3", 70, activo=False)  # inactive: its cost is never asked for nor counted
    add_publication(conn, "MLA4", 71)  # product 71: active, but mlwebhook has no list cost for it
    # product 72 has no publication at all
    add_publication(conn, "MLA5", 73, activo=False)  # product 73: only inactive ones
    add_publication(conn, "MLA6", 74)  # product 74: one MLA


class TestResolverOutput:
    """Characterization: pinned on main before the resolver changed, and unchanged by it."""

    def test_the_max_cost_of_the_active_mlas_per_product(self, conn, db, requested) -> None:
        seed_publications(conn)
        result = resolver_costos_envio_batch(db, [70, 71, 72, 73, 74])
        assert result == {70: 3000.0, 74: 800.0}

    def test_products_without_a_resolvable_cost_are_absent(self, conn, db, requested) -> None:
        seed_publications(conn)
        result = resolver_costos_envio_batch(db, [71, 72, 73])
        assert result == {}  # callers fall back to the ERP envio

    def test_only_the_active_mlas_of_the_asked_products_are_sent_to_mlwebhook(self, conn, db, requested) -> None:
        seed_publications(conn)
        resolver_costos_envio_batch(db, [70, 71, 72, 73])
        assert requested == [["MLA1", "MLA2", "MLA4"]]

    def test_a_product_with_no_publication_at_all_issues_no_mlwebhook_query(self, conn, db, requested) -> None:
        seed_publications(conn)
        assert resolver_costos_envio_batch(db, [72]) == {}
        assert requested == []

    def test_no_item_ids_is_an_empty_result(self, conn, db, requested) -> None:
        assert resolver_costos_envio_batch(db, []) == {}
        assert requested == []

    def test_a_caller_supplied_mapping_is_used_as_is(self, conn, db, requested) -> None:
        seed_publications(conn)

        class Pub:
            def __init__(self, mla: str, activo: bool = True) -> None:
                self.mla, self.activo = mla, activo

        result = resolver_costos_envio_batch(db, [70, 74], pubs_by_item={70: [Pub("MLA3")], 74: [Pub("MLA6")]})
        assert result == {70: 9999.0, 74: 800.0}  # the caller said MLA3 is its active one
        assert requested  # the mapping, not the table, decided what was asked for


def statements_of(db, run) -> list[str]:
    recorded: list[str] = []

    def record(connection, cursor, statement, *rest) -> None:
        recorded.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    return recorded


class TestWhatTheResolverReads:
    """Structural: the publications come as plain columns, in a constant number of statements."""

    def test_it_selects_only_the_columns_it_reads(self, conn, db, requested) -> None:
        seed_publications(conn)
        recorded = statements_of(db, lambda: resolver_costos_envio_batch(db, [70, 71, 72]))
        assert len(recorded) == 1
        select_list = recorded[0].upper().split(" FROM ")[0]
        assert "ITEM_TITLE" not in select_list and "CODIGO" not in select_list and "PRICELIST_ID" not in select_list
        assert "MLA" in select_list and "ITEM_ID" in select_list

    @pytest.mark.parametrize("products", [3, 40])
    def test_the_statement_count_does_not_grow_with_the_products(self, conn, db, requested, products) -> None:
        seed_publications(conn)
        recorded = statements_of(db, lambda: resolver_costos_envio_batch(db, list(range(70, 70 + products))))
        assert len(recorded) == 1
        assert "ANY" in recorded[0].upper()  # the ids travel as ONE array parameter, not one bind per product


class TestTheMlwebhookQuery:
    """`_fetch_list_cost_by_mla` against a real table: the MLAs travel as ONE JSON text parameter."""

    @pytest.fixture()
    def shipping_table(self, env, conn, monkeypatch):  # noqa: F811
        conn.execute(
            text(
                "CREATE TABLE ml_seller_shipping_costs "
                "(mla_id text, list_cost numeric, currency_id text, logistic_type text)"
            )
        )
        rows = [
            ("MLA1", 1000, "ARS"),
            ("MLA2", 0, "ARS"),  # zero cost: excluded
            ("MLA3", None, "ARS"),  # no cost: excluded
            ("MLA4", 500, "USD"),  # not pesos: excluded
            ("MLA5", 700, "ARS"),
            ("MLA9", 123, "ARS"),  # never asked for
        ]
        for mla, cost, currency in rows:
            conn.execute(
                text("INSERT INTO ml_seller_shipping_costs VALUES (:m, :c, :cur, 'x')"),
                {"m": mla, "c": cost, "cur": currency},
            )
        monkeypatch.setattr(envio_real_service, "get_mlwebhook_engine", lambda: env)

    def test_it_returns_the_positive_peso_costs_of_the_asked_mlas(self, shipping_table) -> None:
        asked = ["MLA1", "MLA2", "MLA3", "MLA4", "MLA5", "MLA_UNKNOWN"]
        assert envio_real_service._fetch_list_cost_by_mla(asked) == {"MLA1": 1000.0, "MLA5": 700.0}

    def test_it_binds_the_ids_as_one_json_text_parameter(self, env, shipping_table) -> None:  # noqa: F811
        recorded: list[tuple[str, object]] = []

        def record(connection, cursor, statement, parameters, *rest) -> None:
            recorded.append((statement, parameters))

        event.listen(env, "before_cursor_execute", record)
        try:
            envio_real_service._fetch_list_cost_by_mla([f"MLA{n}" for n in range(1000)])
        finally:
            event.remove(env, "before_cursor_execute", record)
        ((statement, parameters),) = recorded
        assert "jsonb_array_elements_text" in statement
        values = list(parameters.values()) if isinstance(parameters, dict) else list(parameters)
        assert len(values) == 1 and isinstance(values[0], str)  # one text parameter, not an array of 1000 elements

    def test_it_returns_nothing_when_mlwebhook_is_down(self, monkeypatch) -> None:
        def down():
            raise RuntimeError("no mlwebhook")

        monkeypatch.setattr(envio_real_service, "get_mlwebhook_engine", down)
        assert envio_real_service._fetch_list_cost_by_mla(["MLA1"]) == {}


class TestTheReadDoesNotFlush:
    def test_pending_objects_of_the_caller_are_not_flushed(self, env, conn, requested) -> None:  # noqa: F811
        seed_publications(conn)
        db = sessionmaker(bind=env, autocommit=False, autoflush=True)()  # the default of the app's sessions
        pending = PublicacionML(mla="MLA_PENDING", item_id=70, codigo="C", item_title="t", pricelist_id=4, activo=True)
        db.add(pending)
        try:
            resolver_costos_envio_batch(db, [70, 71])
            assert pending in db.new  # still pending: the read did not autoflush the caller's session
            assert all("MLA_PENDING" not in asked for asked in requested)
        finally:
            db.rollback()
            db.close()
