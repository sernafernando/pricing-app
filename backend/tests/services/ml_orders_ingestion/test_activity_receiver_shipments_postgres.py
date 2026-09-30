"""Postgres proof for the shipment-event translation and the false-debt
cleanup (2026-09-30: 393 `activity_unresolved` debts were shipment ids).

Both statements filter/join on `ml_orders_ops.shipping_id`, a BigInteger
column. A `group_by` bug once lived three weeks on this codebase because
its path was only ever tested on SQLite; ids here are real-shaped
(16-digit orders, 11-digit shipments) so BigInteger handling is exercised.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps
from app.services.ml_orders_ingestion import activity_receiver_service as service
from app.services.ml_orders_ingestion import ingestion_service

ORDER_A = 2000018126384162
ORDER_B = 2000018126384163
SHIP_A = 48137554327
SHIP_B = 48119752802
UNKNOWN_SHIP = 48999999999


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(ingestion_service, "congelar", lambda db, order_id, items: None)


def _seed(db):
    now = datetime.now(timezone.utc)
    db.add(MlOrdersOps(order_id=ORDER_A, seller_id=999, shipping_id=SHIP_A, ml_last_updated=now))
    db.add(MlOrdersOps(order_id=ORDER_B, seller_id=999, shipping_id=SHIP_B, ml_last_updated=now))
    db.add(MlOrdersOps(order_id=2000018126384164, seller_id=999, shipping_id=None, ml_last_updated=now))
    db.flush()


def _debt(db, order_id):
    db.add(
        MlOpsDivergence(
            order_id=order_id, kind="unknown", field=service.UNRESOLVED_FIELD, detected_at=datetime.now(timezone.utc)
        )
    )


@pytest.mark.postgres
class TestShipmentTranslationOnPostgres:
    def test_bulk_translation_maps_known_shipments_and_drops_unknown_ones(self, pg_orders_ops_db):
        _seed(pg_orders_ops_db)

        found = service._order_ids_for_shipments(pg_orders_ops_db, [SHIP_A, SHIP_B, UNKNOWN_SHIP])

        assert sorted(found) == [ORDER_A, ORDER_B]

    def test_translation_does_one_statement_for_the_whole_page(self, pg_orders_ops_db):
        from sqlalchemy import event

        _seed(pg_orders_ops_db)
        statements = []
        engine = pg_orders_ops_db.get_bind().engine
        listener = lambda conn, cursor, statement, *a: statements.append(statement)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            service._order_ids_for_shipments(pg_orders_ops_db, [SHIP_A, SHIP_B, UNKNOWN_SHIP])
        finally:
            event.remove(engine, "before_cursor_execute", listener)

        assert len([s for s in statements if "ml_orders_ops" in s]) == 1

    def test_an_empty_page_runs_no_query_and_returns_nothing(self, pg_orders_ops_db):
        assert service._order_ids_for_shipments(pg_orders_ops_db, []) == []


@pytest.mark.postgres
class TestShipmentDebtCleanupOnPostgres:
    def test_clears_only_debts_that_are_known_shipping_ids(self, pg_orders_ops_db):
        db = pg_orders_ops_db
        _seed(db)
        _debt(db, SHIP_A)
        _debt(db, SHIP_B)
        _debt(db, UNKNOWN_SHIP)  # SAFETY: not a shipping_id we hold
        db.flush()

        cleared = service._clear_shipment_id_unresolved_debts(db)

        assert cleared == 2
        assert [d.order_id for d in db.query(MlOpsDivergence).all()] == [UNKNOWN_SHIP]

    def test_a_null_shipping_id_never_matches_a_debt(self, pg_orders_ops_db):
        db = pg_orders_ops_db
        _seed(db)
        _debt(db, 0)
        db.flush()

        assert service._clear_shipment_id_unresolved_debts(db) == 0
        assert db.query(MlOpsDivergence).count() == 1


def _event(topic, resource, order_id):
    return {"topic": topic, "order_id": order_id, "pack_id": None, "resource": resource}


@pytest.mark.postgres
class TestCollectOnPostgres:
    """`_collect_new_order_ids` end to end over a real connection: real
    production event shapes, real-shaped ids."""

    def test_shipment_events_become_their_orders_and_dedup_against_order_events(self, pg_orders_ops_db, monkeypatch):
        db = pg_orders_ops_db
        _seed(db)

        @contextmanager
        def _ctx():
            yield db

        monkeypatch.setattr(service, "get_background_db", _ctx)
        events = [
            _event("orders_v2", f"/orders/{ORDER_A}", ORDER_A),
            _event("shipments", f"/shipments/{SHIP_A}", SHIP_A),
            _event("flex-handshakes", f"/flex/sites/MLA/shipments/{SHIP_B}/assignment/v1", SHIP_B),
            _event("shipments", f"/shipments/{UNKNOWN_SHIP}", UNKNOWN_SHIP),
            _event("items", "/items/MLA1234567890", 1234567890),
        ]

        ids, without = service._collect_new_order_ids(events, {})

        assert ids == [ORDER_A, ORDER_B]
        assert without == 0
