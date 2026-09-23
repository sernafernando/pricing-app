"""RED/GREEN -- enqueue functions + per-order row triggers (ventas-ml-rediseno
PR4.T1-T6a, design D3, D7, D8). Real Postgres only: PL/pgSQL functions,
triggers, `pg_notify` folding and commit-only delivery have no SQLite
equivalent.
"""

from __future__ import annotations

import os
import select
import uuid
from datetime import datetime, timezone

import psycopg2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "postgresql+psycopg2://postgres@localhost:5432/pricing_test")


@pytest.fixture()
def listener_connection():
    """A TRULY independent raw psycopg2 connection (its own `NullPool`
    one-off engine, never `pg_order_metrics_triggers_engine`'s pooled one):
    a pooled `raw_connection()` gets returned to the pool -- not actually
    closed -- so the NEXT test's `raw_connection()` can silently reuse the
    SAME physical backend connection, which was left LISTENing and had
    accumulated every OTHER test's notifications in the meantime (observed:
    48 stray notifies from unrelated tests instead of the expected 1)."""
    engine = create_engine(_POSTGRES_TEST_URL, poolclass=NullPool)
    raw = engine.raw_connection()
    yield raw
    raw.close()
    engine.dispose()


def _insert_order(session, order_id: int, **overrides) -> None:
    row = {
        "order_id": order_id,
        "seller_id": 999,
        "status": "paid",
        "ml_last_updated": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "date_created": datetime(2026, 8, 15, tzinfo=timezone.utc),
        "shipping_id": None,
        "pack_id": None,
        "has_no_shipping_tag": None,
    }
    row.update(overrides)
    session.execute(
        text(
            "INSERT INTO ml_orders_ops "
            "(order_id, seller_id, status, ml_last_updated, date_created, shipping_id, pack_id, has_no_shipping_tag) "
            "VALUES (:order_id, :seller_id, :status, :ml_last_updated, :date_created, :shipping_id, :pack_id, "
            ":has_no_shipping_tag)"
        ),
        row,
    )


def _dirty_row(session, order_id: int):
    return session.execute(
        text(
            "SELECT version, attempts, last_error, suspect, claimed_at, claimed_by, claim_token FROM "
            "ml_order_metrics_dirty WHERE order_id = :order_id"
        ),
        {"order_id": order_id},
    ).fetchone()


def _clear_dirty(session) -> None:
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.commit()


def _clear_orders(session, *order_ids: int) -> None:
    session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = ANY(:ids)"), {"ids": list(order_ids)})
    session.commit()


@pytest.fixture()
def clean_slate(pg_order_metrics_triggers_db):
    """Every test in this file starts from an EMPTY dirty queue and cleans
    up its own inserted orders -- the fixture's session is autocommitting
    (module-scoped engine, no rollback), see `pg_order_metrics_triggers_db`."""
    session = pg_order_metrics_triggers_db
    _clear_dirty(session)
    yield session
    _clear_dirty(session)


@pytest.mark.postgres
class TestOrderMetricsEnqueueFunction:
    def test_fresh_insert_gets_version_1_and_reason(self, clean_slate) -> None:
        session = clean_slate
        session.execute(text("SELECT order_metrics_enqueue(ARRAY[123456]::bigint[], 'input_write')"))
        session.commit()

        row = _dirty_row(session, 123456)
        assert row is not None
        assert row.version == 1
        assert row.attempts == 0
        assert row.suspect is False

    def test_reenqueue_bumps_version_resets_attempts_and_last_error_but_keeps_claim_columns(self, clean_slate) -> None:
        session = clean_slate
        order_id = 123457
        token = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO ml_order_metrics_dirty "
                "(order_id, version, reason, attempts, last_error, suspect, claimed_at, claimed_by, claim_token) "
                "VALUES (:order_id, 3, 'reconcile', 5, 'boom', true, now(), 'worker-1', :token)"
            ),
            {"order_id": order_id, "token": str(token)},
        )
        session.commit()

        session.execute(
            text("SELECT order_metrics_enqueue(ARRAY[:order_id]::bigint[], 'input_write')"), {"order_id": order_id}
        )
        session.commit()

        row = _dirty_row(session, order_id)
        assert row.version == 4
        assert row.attempts == 0
        assert row.last_error is None
        # An in-flight claim stays owned -- design D3/D5 fence.
        assert row.claimed_by == "worker-1"
        assert str(row.claim_token) == str(token)

    def test_un_parks_a_parked_order(self, clean_slate) -> None:
        """PR4.T1a: attempts=5, last_error set -> reset to 0/NULL."""
        session = clean_slate
        order_id = 123458
        session.execute(
            text(
                "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, attempts, last_error) "
                "VALUES (:order_id, 1, 'input_write', 5, 'lease_expired')"
            ),
            {"order_id": order_id},
        )
        session.commit()

        session.execute(
            text("SELECT order_metrics_enqueue(ARRAY[:order_id]::bigint[], 'input_write')"), {"order_id": order_id}
        )
        session.commit()

        row = _dirty_row(session, order_id)
        assert row.attempts == 0
        assert row.last_error is None

    def test_un_parks_and_claim_dirty_can_then_claim_it(
        self, clean_slate, monkeypatch, pg_order_metrics_triggers_engine
    ) -> None:
        """PR4.T1c: a parked order (excluded from claim_dirty) that gets an
        input write is claimable again on the next pass. `claim_dirty` uses
        `get_background_db()` exclusively (PR3 design), so `SessionLocal` is
        pointed at this fixture's own engine for the duration of the test --
        same pattern as `test_queue.py::_order_metrics_db_session`."""
        from datetime import timedelta

        from app.services.order_metrics.queue import claim_dirty

        session_factory = sessionmaker(bind=pg_order_metrics_triggers_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr("app.core.database.SessionLocal", session_factory)

        session = clean_slate
        order_id = 123459
        session.execute(
            text(
                "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, attempts, last_error) "
                "VALUES (:order_id, 1, 'input_write', 5, 'boom')"
            ),
            {"order_id": order_id},
        )
        session.commit()

        session.execute(
            text("SELECT order_metrics_enqueue(ARRAY[:order_id]::bigint[], 'input_write')"), {"order_id": order_id}
        )
        session.commit()

        claims = claim_dirty(limit=200, lease=timedelta(seconds=120), worker_id="test-worker")
        assert any(c.order_id == order_id for c in claims)

    def test_clears_suspect(self, clean_slate) -> None:
        """PR4.T1d: suspect=true row + input-write enqueue -> suspect=false."""
        session = clean_slate
        order_id = 123460
        session.execute(
            text(
                "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, suspect) VALUES (:order_id, 1, 'timeout', true)"
            ),
            {"order_id": order_id},
        )
        session.commit()

        session.execute(
            text("SELECT order_metrics_enqueue(ARRAY[:order_id]::bigint[], 'input_write')"), {"order_id": order_id}
        )
        session.commit()

        row = _dirty_row(session, order_id)
        assert row.suspect is False

    def test_folds_10k_row_fanout_into_one_notify(self, listener_connection, clean_slate) -> None:
        session = clean_slate
        raw = listener_connection
        raw.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = raw.cursor()
        cur.execute("LISTEN order_metrics_dirty")

        ids = list(range(200001, 210001))  # 10k rows, same order of magnitude as the design note.
        try:
            session.execute(text("SELECT order_metrics_enqueue(CAST(:ids AS bigint[]), 'input_write')"), {"ids": ids})
            session.commit()

            ready, _, _ = select.select([raw], [], [], 5)
            assert ready, "expected at least one notification"
            raw.poll()
            notifications = list(raw.notifies)
            assert len(notifications) == 1, f"expected exactly ONE folded notify, got {len(notifications)}"
        finally:
            session.execute(text("DELETE FROM ml_order_metrics_dirty WHERE order_id = ANY(:ids)"), {"ids": ids})
            session.commit()


@pytest.mark.postgres
class TestOrderMetricsEnqueueSystemFunction:
    def test_inserts_missing_row_and_notifies(self, clean_slate) -> None:
        session = clean_slate
        order_id = 123461
        session.execute(
            text("SELECT order_metrics_enqueue_system(ARRAY[:order_id]::bigint[], 'reconcile')"), {"order_id": order_id}
        )
        session.commit()

        row = _dirty_row(session, order_id)
        assert row is not None
        assert row.version == 1

    def test_leaves_an_existing_row_completely_unchanged(self, clean_slate) -> None:
        session = clean_slate
        order_id = 123462
        token = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO ml_order_metrics_dirty "
                "(order_id, version, reason, attempts, last_error, suspect, claimed_at, claimed_by, claim_token) "
                "VALUES (:order_id, 7, 'input_write', 5, 'boom', true, now(), 'worker-2', :token)"
            ),
            {"order_id": order_id, "token": str(token)},
        )
        session.commit()
        before = _dirty_row(session, order_id)

        session.execute(
            text("SELECT order_metrics_enqueue_system(ARRAY[:order_id]::bigint[], 'reconcile')"), {"order_id": order_id}
        )
        session.commit()

        after = _dirty_row(session, order_id)
        assert after.version == before.version
        assert after.attempts == before.attempts
        assert after.last_error == before.last_error
        assert after.suspect == before.suspect
        assert after.claimed_by == before.claimed_by
        assert str(after.claim_token) == str(before.claim_token)

    def test_does_not_clear_suspect(self, clean_slate) -> None:
        """PR4.T1d second half: the system enqueue never un-parks or
        un-suspects an existing row."""
        session = clean_slate
        order_id = 123463
        session.execute(
            text(
                "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, suspect) VALUES (:order_id, 1, 'timeout', true)"
            ),
            {"order_id": order_id},
        )
        session.commit()

        session.execute(
            text("SELECT order_metrics_enqueue_system(ARRAY[:order_id]::bigint[], 'reconcile')"), {"order_id": order_id}
        )
        session.commit()

        row = _dirty_row(session, order_id)
        assert row.suspect is True


@pytest.mark.postgres
class TestOrdersOpsTrigger:
    def test_insert_enqueues(self, clean_slate) -> None:
        session = clean_slate
        order_id = 300001
        try:
            _insert_order(session, order_id)
            session.commit()
            row = _dirty_row(session, order_id)
            assert row is not None
            assert row.version == 1
        finally:
            _clear_orders(session, order_id)

    def test_update_of_read_columns_enqueues_with_version_bump(self, clean_slate) -> None:
        session = clean_slate
        order_id = 300002
        try:
            _insert_order(session, order_id, pack_id=None)
            session.commit()
            _clear_dirty(session)  # the INSERT above already enqueued it -- isolate the UPDATE.

            session.execute(
                text("UPDATE ml_orders_ops SET pack_id = 777 WHERE order_id = :order_id"), {"order_id": order_id}
            )
            session.commit()

            row = _dirty_row(session, order_id)
            assert row is not None
            assert row.version == 1
        finally:
            _clear_orders(session, order_id)

    def test_shipping_id_change_also_enqueues_old_and_new_shipping_siblings(self, clean_slate) -> None:
        session = clean_slate
        order_a, order_b, order_c = 300003, 300004, 300005
        try:
            _insert_order(session, order_a, shipping_id=1001)
            _insert_order(session, order_b, shipping_id=1001)  # OLD sibling: still on 1001 (the pre-update label)
            _insert_order(session, order_c, shipping_id=1001)  # the row being moved: 1001 -> 2002
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_orders_ops SET shipping_id = 2002 WHERE order_id = :order_id"), {"order_id": order_c}
            )
            session.commit()

            assert _dirty_row(session, order_c) is not None  # NEW row itself
            assert _dirty_row(session, order_a) is not None  # OLD shipping_id sibling of order_a/b
            assert _dirty_row(session, order_b) is not None
        finally:
            _clear_orders(session, order_a, order_b, order_c)

    def test_delete_enqueues(self, clean_slate) -> None:
        session = clean_slate
        order_id = 300006
        _insert_order(session, order_id)
        session.commit()
        _clear_dirty(session)

        session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :order_id"), {"order_id": order_id})
        session.commit()

        row = _dirty_row(session, order_id)
        assert row is not None

    def test_rolled_back_write_enqueues_nothing(self, pg_order_metrics_triggers_engine, clean_slate) -> None:
        session = clean_slate
        order_id = 300007
        conn = pg_order_metrics_triggers_engine.connect()
        try:
            trans = conn.begin()
            conn.execute(
                text(
                    "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
                    "VALUES (:order_id, 999, 'paid', now(), now())"
                ),
                {"order_id": order_id},
            )
            trans.rollback()
        finally:
            conn.close()

        row = _dirty_row(session, order_id)
        assert row is None


@pytest.mark.postgres
class TestOrderItemsOpsAndCostosTriggers:
    def test_items_ops_insert_update_delete_enqueue(self, clean_slate) -> None:
        session = clean_slate
        order_id = 310001
        try:
            _insert_order(session, order_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("INSERT INTO ml_order_items_ops (order_id, item_id, quantity) VALUES (:order_id, 'MLA1', 1)"),
                {"order_id": order_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_order_items_ops SET quantity = 2 WHERE order_id = :order_id"), {"order_id": order_id}
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
            _clear_dirty(session)

            session.execute(text("DELETE FROM ml_order_items_ops WHERE order_id = :order_id"), {"order_id": order_id})
            session.commit()
            assert _dirty_row(session, order_id) is not None
        finally:
            _clear_orders(session, order_id)

    def test_item_costos_insert_update_delete_enqueue(self, clean_slate) -> None:
        session = clean_slate
        order_id = 310002
        try:
            _insert_order(session, order_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "INSERT INTO ml_order_item_costos "
                    "(order_id, item_id, costo_origen, moneda, costo_unitario_ars, iva_pct, precio_unitario, fuente, producto_item_id) "
                    "VALUES (:order_id, 'MLA1', 10.0, 'ARS', 10.0, 21.0, 100.0, 'sku', 1)"
                ),
                {"order_id": order_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_order_item_costos SET costo_unitario_ars = 20.0 WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM ml_order_item_costos WHERE order_id = :order_id"), {"order_id": order_id})
            session.commit()
            _clear_orders(session, order_id)


@pytest.mark.postgres
class TestPaymentsOpsAndChargesTriggers:
    def test_payments_ops_insert_update_delete_enqueue(self, clean_slate) -> None:
        session = clean_slate
        order_id = 320001
        payment_id = 900000001
        try:
            _insert_order(session, order_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "INSERT INTO ml_payments_ops (payment_id, order_id, status) VALUES (:payment_id, :order_id, 'approved')"
                ),
                {"payment_id": payment_id, "order_id": order_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_payments_ops SET status = 'refunded' WHERE payment_id = :payment_id"),
                {"payment_id": payment_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
            _clear_dirty(session)

            session.execute(
                text("DELETE FROM ml_payments_ops WHERE payment_id = :payment_id"), {"payment_id": payment_id}
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
        finally:
            _clear_orders(session, order_id)

    def test_payment_charges_resolve_order_id_through_payment(self, clean_slate) -> None:
        session = clean_slate
        order_id = 320002
        payment_id = 900000002
        try:
            _insert_order(session, order_id)
            session.execute(
                text(
                    "INSERT INTO ml_payments_ops (payment_id, order_id, status) VALUES (:payment_id, :order_id, 'approved')"
                ),
                {"payment_id": payment_id, "order_id": order_id},
            )
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("INSERT INTO ml_payment_charges (payment_id, name, amount) VALUES (:payment_id, 'meli_fee', 5.0)"),
                {"payment_id": payment_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(
                text("DELETE FROM ml_payment_charges WHERE payment_id = :payment_id"), {"payment_id": payment_id}
            )
            session.execute(
                text("DELETE FROM ml_payments_ops WHERE payment_id = :payment_id"), {"payment_id": payment_id}
            )
            session.commit()
            _clear_orders(session, order_id)

    def test_payment_charges_payment_id_change_enqueues_both_old_and_new_order(self, clean_slate) -> None:
        """F6 (review): `compute_breakdown`/`compute_neto_by_order_ids`
        (`app/services/ml_ventas_desglose/breakdown_service.py`) join charges
        to a payment via `MlPaymentCharge.payment_id`, and a payment belongs
        to exactly one order (`ml_payments_ops.order_id`) -- so moving a
        charge from one payment to another moves it from one order's read
        set to another's. Both the losing (OLD) and gaining (NEW) order must
        be enqueued, mirroring the sibling-fanout shape the orders_ops
        trigger already uses for `shipping_id`."""
        session = clean_slate
        order_old, order_new = 320003, 320004
        payment_old, payment_new = 900000004, 900000005
        charge_id = None
        try:
            _insert_order(session, order_old)
            _insert_order(session, order_new)
            session.execute(
                text(
                    "INSERT INTO ml_payments_ops (payment_id, order_id, status) VALUES (:payment_id, :order_id, 'approved')"
                ),
                {"payment_id": payment_old, "order_id": order_old},
            )
            session.execute(
                text(
                    "INSERT INTO ml_payments_ops (payment_id, order_id, status) VALUES (:payment_id, :order_id, 'approved')"
                ),
                {"payment_id": payment_new, "order_id": order_new},
            )
            charge_id = session.execute(
                text(
                    "INSERT INTO ml_payment_charges (payment_id, name, amount) VALUES (:payment_id, 'meli_fee', 5.0) "
                    "RETURNING id"
                ),
                {"payment_id": payment_old},
            ).scalar()
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_payment_charges SET payment_id = :payment_new WHERE id = :charge_id"),
                {"payment_new": payment_new, "charge_id": charge_id},
            )
            session.commit()

            assert _dirty_row(session, order_old) is not None, "losing order must be re-enqueued"
            assert _dirty_row(session, order_new) is not None, "gaining order must be re-enqueued"
        finally:
            if charge_id is not None:
                session.execute(text("DELETE FROM ml_payment_charges WHERE id = :charge_id"), {"charge_id": charge_id})
            session.execute(
                text("DELETE FROM ml_payments_ops WHERE payment_id IN (:p1, :p2)"),
                {"p1": payment_old, "p2": payment_new},
            )
            session.commit()
            _clear_orders(session, order_old, order_new)


@pytest.mark.postgres
class TestShipmentsOpsTrigger:
    def test_insert_enqueues(self, clean_slate) -> None:
        """F1 (review): `_upsert_shipment_row`
        (`app/services/ml_orders_ingestion/ingestion_service.py`) is an
        `INSERT ... ON CONFLICT`, so a shipment's FIRST appearance is a pure
        INSERT. Before this fix, only `AFTER UPDATE OF logistic_type,
        receiver_address` existed, so an order computed before its shipment
        ever arrived (fetch budget exhausted / a failed fetch) stayed stale
        forever the moment the shipment finally landed."""
        session = clean_slate
        order_id = 330003
        shipment_id = 800000003
        try:
            _insert_order(session, order_id, shipping_id=shipment_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type) "
                    "VALUES (:shipment_id, :order_id, 'drop_off')"
                ),
                {"shipment_id": shipment_id, "order_id": order_id},
            )
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(
                text("DELETE FROM ml_shipments_ops WHERE shipment_id = :shipment_id"), {"shipment_id": shipment_id}
            )
            session.commit()
            _clear_orders(session, order_id)

    def test_delete_enqueues(self, clean_slate) -> None:
        """F1 (review): a DELETE must use OLD, and was entirely uncovered."""
        session = clean_slate
        order_id = 330004
        shipment_id = 800000004
        try:
            _insert_order(session, order_id, shipping_id=shipment_id)
            session.execute(
                text(
                    "INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type) "
                    "VALUES (:shipment_id, :order_id, 'drop_off')"
                ),
                {"shipment_id": shipment_id, "order_id": order_id},
            )
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("DELETE FROM ml_shipments_ops WHERE shipment_id = :shipment_id"), {"shipment_id": shipment_id}
            )
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            _clear_orders(session, order_id)

    def test_logistic_type_change_enqueues_pack_siblings_sharing_the_shipment(self, clean_slate) -> None:
        """F2 (review): the formula resolves shipments by
        `MlShipmentOps.shipment_id IN (<orders' shipping_id>)`
        (`breakdown_service.py`), never by `ml_shipments_ops.order_id`. A
        pack (or shared Flex) has several orders sharing one `shipping_id`;
        before this fix the trigger only enqueued `NEW.order_id`, so sibling
        orders sharing that shipment were never recomputed when
        `logistic_type`/`receiver_address` changed."""
        session = clean_slate
        order_owner, order_sibling = 330005, 330006
        shipment_id = 800000005
        try:
            _insert_order(session, order_owner, shipping_id=shipment_id)
            _insert_order(session, order_sibling, shipping_id=shipment_id)
            session.execute(
                text(
                    "INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type) "
                    "VALUES (:shipment_id, :order_id, 'drop_off')"
                ),
                {"shipment_id": shipment_id, "order_id": order_owner},
            )
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_shipments_ops SET logistic_type = 'self_service' WHERE shipment_id = :shipment_id"),
                {"shipment_id": shipment_id},
            )
            session.commit()

            assert _dirty_row(session, order_owner) is not None
            assert _dirty_row(session, order_sibling) is not None, (
                "sibling sharing the shipment must be re-enqueued too"
            )
        finally:
            session.execute(
                text("DELETE FROM ml_shipments_ops WHERE shipment_id = :shipment_id"), {"shipment_id": shipment_id}
            )
            session.commit()
            _clear_orders(session, order_owner, order_sibling)

    def test_logistic_type_change_enqueues(self, clean_slate) -> None:
        session = clean_slate
        order_id = 330001
        shipment_id = 800000001
        try:
            _insert_order(session, order_id, shipping_id=shipment_id)
            session.execute(
                text(
                    "INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type) "
                    "VALUES (:shipment_id, :order_id, 'drop_off')"
                ),
                {"shipment_id": shipment_id, "order_id": order_id},
            )
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_shipments_ops SET logistic_type = 'self_service' WHERE shipment_id = :shipment_id"),
                {"shipment_id": shipment_id},
            )
            session.commit()
            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(
                text("DELETE FROM ml_shipments_ops WHERE shipment_id = :shipment_id"), {"shipment_id": shipment_id}
            )
            session.commit()
            _clear_orders(session, order_id)

    def test_sender_receiver_cost_and_raw_costs_changes_do_not_fire(self, clean_slate) -> None:
        session = clean_slate
        order_id = 330002
        shipment_id = 800000002
        try:
            _insert_order(session, order_id)
            session.execute(
                text(
                    "INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type, sender_cost, receiver_cost) "
                    "VALUES (:shipment_id, :order_id, 'drop_off', 0, 0)"
                ),
                {"shipment_id": shipment_id, "order_id": order_id},
            )
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "UPDATE ml_shipments_ops SET sender_cost = 15.5, receiver_cost = 3.0, "
                    "raw_costs = '{\"gross_amount\": 15.5}'::jsonb WHERE shipment_id = :shipment_id"
                ),
                {"shipment_id": shipment_id},
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(
                text("DELETE FROM ml_shipments_ops WHERE shipment_id = :shipment_id"), {"shipment_id": shipment_id}
            )
            session.commit()
            _clear_orders(session, order_id)


@pytest.mark.postgres
class TestNoOpWritesNeverEnqueue:
    """PR4.T6a (design D3 rev 5): rewriting the SAME value the trigger's
    UPDATE OF column list watches enqueues nothing on every row-trigger
    table -- and a previously parked order stays parked across repeated
    no-op sweep writes."""

    def test_orders_ops_same_value_rewrite_is_a_no_op(self, clean_slate) -> None:
        session = clean_slate
        order_id = 340001
        try:
            _insert_order(session, order_id, pack_id=55)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_orders_ops SET pack_id = 55 WHERE order_id = :order_id"), {"order_id": order_id}
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            _clear_orders(session, order_id)

    def test_a_parked_order_stays_parked_across_repeated_no_op_writes(self, clean_slate) -> None:
        session = clean_slate
        order_id = 340002
        try:
            _insert_order(session, order_id, pack_id=55)
            session.commit()

            session.execute(
                text("UPDATE ml_order_metrics_dirty SET attempts = 5, last_error = 'boom' WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            session.commit()

            for _ in range(3):
                session.execute(
                    text("UPDATE ml_orders_ops SET pack_id = 55 WHERE order_id = :order_id"), {"order_id": order_id}
                )
                session.commit()

            row = _dirty_row(session, order_id)
            assert row.attempts == 5
            assert row.last_error == "boom"
        finally:
            _clear_orders(session, order_id)

    def test_payments_ops_same_value_rewrite_is_a_no_op(self, clean_slate) -> None:
        session = clean_slate
        order_id = 340003
        payment_id = 900000003
        try:
            _insert_order(session, order_id)
            session.execute(
                text(
                    "INSERT INTO ml_payments_ops (payment_id, order_id, status, net_received_amount) "
                    "VALUES (:payment_id, :order_id, 'approved', 100.0)"
                ),
                {"payment_id": payment_id, "order_id": order_id},
            )
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "UPDATE ml_payments_ops SET status = 'approved', net_received_amount = 100.0 "
                    "WHERE payment_id = :payment_id"
                ),
                {"payment_id": payment_id},
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(
                text("DELETE FROM ml_payments_ops WHERE payment_id = :payment_id"), {"payment_id": payment_id}
            )
            session.commit()
            _clear_orders(session, order_id)


@pytest.mark.postgres
class TestNotifyOnlyOnCommit:
    """PR4.T12: a second raw connection LISTENs; zero notifications on
    rollback, exactly one on commit regardless of row count."""

    def test_rollback_delivers_nothing_commit_delivers_exactly_one(
        self, pg_order_metrics_triggers_engine, listener_connection, clean_slate
    ) -> None:
        session = clean_slate
        raw = listener_connection
        order_ids = [350001, 350002, 350003]
        try:
            raw.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            cur = raw.cursor()
            cur.execute("LISTEN order_metrics_dirty")

            # Rolled-back write: nothing delivered.
            conn = pg_order_metrics_triggers_engine.connect()
            trans = conn.begin()
            for order_id in order_ids:
                conn.execute(
                    text(
                        "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
                        "VALUES (:order_id, 999, 'paid', now(), now())"
                    ),
                    {"order_id": order_id},
                )
            trans.rollback()
            conn.close()

            ready, _, _ = select.select([raw], [], [], 1)
            assert not ready, "rollback must deliver zero notifications"

            # Committed multi-row write: exactly one folded notify.
            conn = pg_order_metrics_triggers_engine.connect()
            trans = conn.begin()
            for order_id in order_ids:
                conn.execute(
                    text(
                        "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
                        "VALUES (:order_id, 999, 'paid', now(), now())"
                    ),
                    {"order_id": order_id},
                )
            trans.commit()
            conn.close()

            ready, _, _ = select.select([raw], [], [], 5)
            assert ready
            raw.poll()
            assert len(raw.notifies) == 1
        finally:
            _clear_orders(session, *order_ids)
