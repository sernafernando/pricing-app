"""ODD `metricas-ml-tablero` T1: the store filter against real Postgres.

The SQLite router tests prove the semantics; this file proves the two things
SQLite cannot: the query runs with real 16-digit BigInteger ids through the
endpoint's group/sort/page shape, and the MLA -> store lookup inside the
correlated EXISTS is index-friendly (the planner CAN answer it from the
`mlp_publicationid` index -- migration 20261001_ix_mlp_publicationid).
"""

from __future__ import annotations

import pytest
import json
from datetime import datetime, timezone

from sqlalchemy import event, func, text
from sqlalchemy import inspect as sa_inspect

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_sales_query.filters import NO_STORE, SalesFilter, build_scope, store_facet_counts

ORDER_GAUSS = 2000012345678901
ORDER_NONE = 2000012345678902
PACK = 2000098765432101
PACK_TPLINK = 2000012345678903
PACK_NONE = 2000012345678904
ALL_ON = dict(include_unknown=True, include_in_dispute=True, include_mixed=True, include_provisional=True)


def _order(session, order_id: int, pack_id: int | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO ml_orders_ops "
            "(order_id, seller_id, status, ml_last_updated, date_created, pack_id, "
            " total_amount, paid_amount, currency_id) "
            "VALUES (:oid, 999, 'paid', now(), now(), :pid, 100, 100, 'ARS')"
        ),
        {"oid": order_id, "pid": pack_id},
    )


def _item(session, order_id: int, mla: str) -> None:
    session.execute(
        text("INSERT INTO ml_order_items_ops (order_id, item_id, quantity) VALUES (:oid, :mla, 1)"),
        {"oid": order_id, "mla": mla},
    )


def _publication(session, mlp_id: int, mla: str, store_id: int | None) -> None:
    session.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, mlp_official_store_id) "
            "VALUES (:id, :mla, :store)"
        ),
        {"id": mlp_id, "mla": mla, "store": store_id},
    )


@pytest.fixture()
def slate(pg_order_metrics_triggers_db, monkeypatch):
    from app.core.config import settings
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
    from app.models.ml_order_metrics import MlOrderMetrics
    from app.models.ml_orders_ops import MlOperationLink
    from app.models.rma_claim_ml import RmaClaimML
    from tests.conftest import _restore_pristine_pg_types

    monkeypatch.setattr(settings, "ML_USER_ID", "999", raising=False)
    session = pg_order_metrics_triggers_db
    tablas = (
        MlOrderMetrics.__table__,
        MlOperationLink.__table__,
        RmaClaimML.__table__,
        MercadoLibreItemPublicado.__table__,
    )
    _restore_pristine_pg_types(tablas)
    # DDL through the ENGINE (its own committed transaction), not the
    # session's connection: the session must start clean so its commits
    # below are real commits this file's teardown can clean up.
    engine = session.get_bind().engine
    creadas = [tabla for tabla in tablas if not sa_inspect(engine).has_table(tabla.name)]
    for tabla in creadas:
        tabla.create(engine)
    for stmt in (
        "DELETE FROM ml_payments_ops WHERE order_id IN (SELECT order_id FROM ml_orders_ops WHERE seller_id = 999)",
        "DELETE FROM ml_order_items_ops WHERE order_id IN (SELECT order_id FROM ml_orders_ops WHERE seller_id = 999)",
        "DELETE FROM ml_orders_ops WHERE seller_id = 999",
        "DELETE FROM tb_mercadolibre_items_publicados WHERE mlp_id BETWEEN 990001 AND 990099",
    ):
        session.execute(text(stmt))
    session.commit()

    _order(session, ORDER_GAUSS)
    _order(session, ORDER_NONE)
    _order(session, PACK_TPLINK, PACK)
    _order(session, PACK_NONE, PACK)
    _publication(session, 990001, "MLA9900001", 57997)
    _publication(session, 990003, "MLA9900003", 2645)
    _item(session, ORDER_GAUSS, "MLA9900001")
    _item(session, ORDER_NONE, "MLA9900002")
    _item(session, PACK_TPLINK, "MLA9900003")
    _item(session, PACK_NONE, "MLA9900004")
    session.commit()
    yield session
    session.rollback()
    for stmt in (
        "DELETE FROM ml_payments_ops WHERE order_id IN (SELECT order_id FROM ml_orders_ops WHERE seller_id = 999)",
        "DELETE FROM ml_order_items_ops WHERE order_id IN (SELECT order_id FROM ml_orders_ops WHERE seller_id = 999)",
        "DELETE FROM ml_orders_ops WHERE seller_id = 999",
        "DELETE FROM tb_mercadolibre_items_publicados WHERE mlp_id BETWEEN 990001 AND 990099",
    ):
        session.execute(text(stmt))
    session.commit()
    session.close()
    # Leave the shared test DB as found: a lingering `ml_order_metrics` (FK to
    # `ml_orders_ops`) makes the module engine's own teardown fail to drop
    # `ml_orders_ops` for every later Postgres module.
    for tabla in reversed(creadas):
        tabla.drop(engine, checkfirst=True)


def _key_page(scope):
    """The endpoint's group/sort/page shape over the listing query."""
    return [
        row.group_key
        for row in scope.listing_query.with_entities(scope.group_key.label("group_key"))
        .group_by(scope.group_key)
        .order_by(func.max(MlOrdersOps.order_id).desc())
        .limit(50)
        .all()
    ]


@pytest.mark.postgres
class TestStoreFilterOnPostgres:
    def test_one_store_with_real_size_ids(self, slate) -> None:
        scope = build_scope(slate, SalesFilter(stores=("57997",), **ALL_ON))
        assert _key_page(scope) == [f"o:{ORDER_GAUSS}"]

    def test_a_pack_matches_whole_through_one_member(self, slate) -> None:
        scope = build_scope(slate, SalesFilter(stores=("2645",), **ALL_ON))
        assert _key_page(scope) == [f"p:{PACK}"]

    def test_sin_tienda(self, slate) -> None:
        scope = build_scope(slate, SalesFilter(stores=(NO_STORE,), **ALL_ON))
        assert sorted(_key_page(scope)) == sorted([f"o:{ORDER_NONE}", f"p:{PACK}"])

    def test_facet_counts(self, slate) -> None:
        scope = build_scope(slate, SalesFilter(stores=("57997",), **ALL_ON))
        counts, total = store_facet_counts(scope)
        assert counts == {"57997": 1, "2645": 1, NO_STORE: 2}
        assert total == 3

    def test_the_store_lookup_can_use_the_publication_index(self, slate) -> None:
        """With sequential scans priced out, the plan must reach
        `tb_mercadolibre_items_publicados` through an index on
        `mlp_publicationid`: the predicate is sargable (no function wraps the
        column). If someone wraps it (`upper(...)`, a cast), this fails."""
        scope = build_scope(slate, SalesFilter(stores=("57997", NO_STORE), **ALL_ON))
        query = scope.listing_query.with_entities(MlOrdersOps.order_id)
        compiled = query.statement.compile(dialect=slate.get_bind().dialect, compile_kwargs={"literal_binds": True})
        slate.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(row[0] for row in slate.execute(text(f"EXPLAIN {compiled}")))
        assert "mlp_publicationid" in plan
        assert "Seq Scan on tb_mercadolibre_items_publicados" not in plan


def _rows_read_from(plan: dict, relation: str) -> int:
    """Rows a JSON `EXPLAIN ANALYZE` plan actually pulled out of `relation`
    (actual rows x loops, summed over every node that reads it)."""
    total = 0
    if plan.get("Relation Name") == relation:
        total += int(plan.get("Actual Rows", 0)) * int(plan.get("Actual Loops", 1))
    for child in plan.get("Plans", []):
        total += _rows_read_from(child, relation)
    return total


@pytest.mark.postgres
class TestStoreFacetCostFollowsTheScope:
    def test_the_store_facet_reads_the_scopes_items_not_the_sellers_history(self, slate) -> None:
        """2.000 sales in January, one in September; the September facet must
        read the items of the September group(s), not the whole history."""
        slate.execute(
            text(
                "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, "
                "total_amount, paid_amount, currency_id) "
                "SELECT 2000090000000000 + i, 999, 'paid', TIMESTAMPTZ '2026-01-15', TIMESTAMPTZ '2026-01-15', "
                "100, 100, 'ARS' FROM generate_series(1, 2000) AS i"
            )
        )
        slate.execute(
            text(
                "INSERT INTO ml_order_items_ops (order_id, item_id, quantity) "
                "SELECT 2000090000000000 + i, 'MLA9900001', 1 FROM generate_series(1, 2000) AS i"
            )
        )
        slate.execute(
            text(
                "INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) "
                "VALUES (2000090000000001, :oid, 'approved', TIMESTAMPTZ '2026-09-10 12:00+00')"
            ),
            {"oid": ORDER_GAUSS},
        )
        slate.commit()
        slate.execute(text("ANALYZE ml_orders_ops"))
        slate.execute(text("ANALYZE ml_order_items_ops"))
        september = (datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc))
        scope = build_scope(slate, SalesFilter(date_range=september, **ALL_ON))

        statements = []
        connection = slate.connection()

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append((statement, parameters))

        event.listen(connection, "before_cursor_execute", record)
        try:
            counts, total = store_facet_counts(scope)
        finally:
            event.remove(connection, "before_cursor_execute", record)

        assert counts == {"57997": 1} and total == 1
        facet_sql, params = next((s, p) for s, p in statements if "ml_order_items_ops" in s)
        # Sequential scans priced out: a 2.000-row table is cheap to scan
        # whole, so on its own the planner would; what is being proven is
        # that the query CAN be answered from the scope's orders alone. The
        # unscoped version read every item of the history even then.
        cursor = connection.connection.cursor()
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + facet_sql, params)
        raw = cursor.fetchone()[0]
        plan = (raw if isinstance(raw, list) else json.loads(raw))[0]["Plan"]
        assert _rows_read_from(plan, "ml_order_items_ops") <= 10, json.dumps(plan, indent=1)[:4000]


@pytest.mark.postgres
class TestStoreFacetStaysInsideTheSeller:
    def test_another_sellers_order_sharing_a_pack_id_never_counts(self, slate) -> None:
        """Pack ids are ML's, not ours: another seller's order can carry the
        same `pack_id`. It must not add a store bucket to our pack -- the
        chip count must equal what clicking the chip returns (nothing).
        The seller in scope is the `slate` fixture's ML_USER_ID (999)."""
        try:
            slate.execute(
                text(
                    "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, pack_id, "
                    "total_amount, paid_amount, currency_id) "
                    "VALUES (2000012345679999, 555, 'paid', now(), now(), :pack, 100, 100, 'ARS')"
                ),
                {"pack": PACK},
            )
            _publication(slate, 990044, "MLA9900044", 144)
            _item(slate, 2000012345679999, "MLA9900044")
            slate.commit()

            counts, _total = store_facet_counts(build_scope(slate, SalesFilter(**ALL_ON)))
            clicked = _key_page(build_scope(slate, SalesFilter(stores=("144",), **ALL_ON)))

            assert "144" not in counts
            assert clicked == []
        finally:
            slate.rollback()
            slate.execute(text("DELETE FROM ml_order_items_ops WHERE order_id = 2000012345679999"))
            slate.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 2000012345679999"))
            slate.execute(text("DELETE FROM tb_mercadolibre_items_publicados WHERE mlp_id = 990044"))
            slate.commit()
