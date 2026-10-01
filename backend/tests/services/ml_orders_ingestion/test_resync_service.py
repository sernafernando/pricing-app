"""ODD `ventas-ml-ui-pendiente` T7 / spec `ml-order-resync` R22-R24.

The promises under test:
  - R23: a successful resync enqueues the order's metrics EXPLICITLY, even
    when ML's answer is identical to what is stored (the capture triggers
    ignore no-op writes, so they cannot be relied on).
  - R24 / scenario 3: any failure to fetch (order, payments, shipment) leaves
    the stored data completely untouched and says so -- every HTTP call
    happens BEFORE the first write.
  - Scenario 4: a resync already running (or one that just finished) for the
    same order is refused, never raced.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_orders_ingestion import resync_service
from app.services.ml_orders_ingestion.resync_service import (
    OrderNotFound,
    ResyncFailed,
    ResyncInProgress,
    resync_order,
)
from app.services.ml_webhook_client import ml_webhook_client
from app.services.order_metrics.queue import enqueue_order_metrics

ORDER_ID = 2000018378699734
SHIPMENT_ID = 47976892759
PAYMENT_ID = 177235887841
STORED_AT = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    resync_service._reset_guard_for_tests()


@pytest.fixture
def enqueued(monkeypatch):
    calls = []
    monkeypatch.setattr(
        resync_service, "enqueue_order_metrics", lambda db, ids, reason: calls.append((list(ids), reason))
    )
    return calls


def _ml_order(*, status="paid", last_updated=STORED_AT, with_shipping=True, payment_ids=(PAYMENT_ID,)):
    """The shape `/orders/<id>` returns (`last_updated`, not `date_last_updated`)."""
    return {
        "id": ORDER_ID,
        "status": status,
        "date_created": (STORED_AT - timedelta(days=1)).isoformat(),
        "last_updated": last_updated.isoformat(),
        "seller": {"id": 999},
        "buyer": {"id": 1, "nickname": "comprador"},
        "order_items": [],
        "shipping": {"id": SHIPMENT_ID} if with_shipping else {},
        "payments": [{"id": pid} for pid in payment_ids],
    }


def _ml_payment(status="approved"):
    # The shape `get_payment` returns through the ml-webhook proxy:
    # `payment_id`, not `id` (`ml_payments_ingestion.mapper.map_payment`).
    return {
        "payment_id": PAYMENT_ID,
        "order_id": ORDER_ID,
        "status": status,
        "transaction_amount": 1000.0,
        "total_paid_amount": 1000.0,
        "currency_id": "ARS",
        "date_approved": STORED_AT.isoformat(),
    }


def _ml_shipment(status="shipped"):
    return {
        "id": SHIPMENT_ID,
        "order_id": ORDER_ID,
        "status": status,
        "substatus": None,
        "logistic_type": "cross_docking",
        "tracking_number": "TRK1",
        "date_created": (STORED_AT - timedelta(days=1)).isoformat(),
        "last_updated": STORED_AT.isoformat(),
        "receiver_address": {"city": {"name": "Rosario"}},
    }


def _store_order(db, status="paid"):
    db.add(
        MlOrdersOps(
            order_id=ORDER_ID,
            status=status,
            ml_last_updated=STORED_AT,
            date_created=STORED_AT - timedelta(days=1),
            seller_id=999,
            shipping_id=SHIPMENT_ID,
        )
    )
    # Committed, like the real stored order: the service releases its read
    # transaction with a rollback, which must not discard what was stored.
    db.commit()


def _ml(monkeypatch, *, order=None, payment=None, shipment=None):
    monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=order))
    monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=payment))
    monkeypatch.setattr(ml_webhook_client, "get_shipment", AsyncMock(return_value=shipment))
    monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=None))


class TestSuccessfulResync:
    def test_writes_what_ml_says_and_enqueues_the_metrics(self, db, monkeypatch, enqueued):
        _store_order(db, status="paid")
        newer = STORED_AT + timedelta(hours=1)
        _ml(
            monkeypatch,
            order=_ml_order(status="cancelled", last_updated=newer),
            payment=_ml_payment(),
            shipment=_ml_shipment(),
        )

        result = resync_order(db, ORDER_ID)

        assert result.order_id == ORDER_ID
        assert db.query(MlOrdersOps).filter_by(order_id=ORDER_ID).one().status == "cancelled"
        assert db.query(MlPaymentOps).filter_by(payment_id=PAYMENT_ID).count() == 1
        assert db.query(MlShipmentOps).filter_by(shipment_id=SHIPMENT_ID).count() == 1
        assert enqueued == [([ORDER_ID], "resync")]

    def test_enqueues_even_when_ml_answers_exactly_what_is_stored(self, db, monkeypatch, enqueued):
        _store_order(db, status="paid")
        _ml(monkeypatch, order=_ml_order(status="paid"), payment=_ml_payment(), shipment=_ml_shipment())

        resync_order(db, ORDER_ID)

        assert enqueued == [([ORDER_ID], "resync")]

    def test_an_order_with_no_shipment_resyncs_without_asking_for_one(self, db, monkeypatch, enqueued):
        _store_order(db)
        _ml(monkeypatch, order=_ml_order(with_shipping=False), payment=_ml_payment())

        resync_order(db, ORDER_ID)

        ml_webhook_client.get_shipment.assert_not_called()
        assert enqueued == [([ORDER_ID], "resync")]


class TestFailuresLeaveStoredDataUntouched:
    def test_order_fetch_failure(self, db, monkeypatch, enqueued):
        _store_order(db, status="paid")
        _ml(monkeypatch, order=None)

        with pytest.raises(ResyncFailed) as exc:
            resync_order(db, ORDER_ID)

        assert "Mercado Libre" in str(exc.value)
        assert db.query(MlOrdersOps).filter_by(order_id=ORDER_ID).one().status == "paid"
        assert enqueued == []

    def test_payment_fetch_failure_does_not_overwrite_the_order(self, db, monkeypatch, enqueued):
        _store_order(db, status="paid")
        newer = STORED_AT + timedelta(hours=1)
        _ml(monkeypatch, order=_ml_order(status="cancelled", last_updated=newer), payment=None, shipment=_ml_shipment())

        with pytest.raises(ResyncFailed):
            resync_order(db, ORDER_ID)

        assert db.query(MlOrdersOps).filter_by(order_id=ORDER_ID).one().status == "paid"
        assert db.query(MlPaymentOps).count() == 0
        assert enqueued == []

    def test_shipment_fetch_failure_does_not_overwrite_the_order(self, db, monkeypatch, enqueued):
        _store_order(db, status="paid")
        newer = STORED_AT + timedelta(hours=1)
        _ml(monkeypatch, order=_ml_order(status="cancelled", last_updated=newer), payment=_ml_payment(), shipment=None)

        with pytest.raises(ResyncFailed):
            resync_order(db, ORDER_ID)

        assert db.query(MlOrdersOps).filter_by(order_id=ORDER_ID).one().status == "paid"
        assert db.query(MlShipmentOps).count() == 0
        assert enqueued == []

    def test_an_order_ml_payload_that_cannot_be_mapped_is_a_failure_not_a_silent_success(
        self, db, monkeypatch, enqueued
    ):
        _store_order(db)
        broken = _ml_order()
        del broken["id"]
        _ml(monkeypatch, order=broken, payment=_ml_payment(), shipment=_ml_shipment())

        with pytest.raises(ResyncFailed):
            resync_order(db, ORDER_ID)

        assert enqueued == []

    def test_a_payment_ml_returns_unmappable_is_a_failure_before_anything_is_written(self, db, monkeypatch, enqueued):
        _store_order(db, status="paid")
        newer = STORED_AT + timedelta(hours=1)
        broken_payment = _ml_payment()
        del broken_payment["status"]
        _ml(
            monkeypatch,
            order=_ml_order(status="cancelled", last_updated=newer),
            payment=broken_payment,
            shipment=_ml_shipment(),
        )

        with pytest.raises(ResyncFailed):
            resync_order(db, ORDER_ID)

        assert db.query(MlOrdersOps).filter_by(order_id=ORDER_ID).one().status == "paid"
        assert enqueued == []

    def test_unknown_order(self, db, monkeypatch, enqueued):
        _ml(monkeypatch, order=_ml_order())
        with pytest.raises(OrderNotFound):
            resync_order(db, ORDER_ID)
        ml_webhook_client.get_order.assert_not_called()


class TestRepeatedResync:
    def test_a_second_resync_while_one_runs_is_refused(self, db, monkeypatch, enqueued):
        _store_order(db)
        _ml(monkeypatch, order=_ml_order(), payment=_ml_payment(), shipment=_ml_shipment())
        assert resync_service._try_begin(ORDER_ID)

        with pytest.raises(ResyncInProgress):
            resync_order(db, ORDER_ID)

        assert enqueued == []
        ml_webhook_client.get_order.assert_not_called()

    def test_a_resync_right_after_a_finished_one_is_refused_then_allowed(self, db, monkeypatch, enqueued):
        _store_order(db)
        _ml(monkeypatch, order=_ml_order(), payment=_ml_payment(), shipment=_ml_shipment())
        clock = [1000.0]

        resync_order(db, ORDER_ID, monotonic=lambda: clock[0])
        with pytest.raises(ResyncInProgress):
            resync_order(db, ORDER_ID, monotonic=lambda: clock[0] + 1)
        resync_order(db, ORDER_ID, monotonic=lambda: clock[0] + resync_service.COOLDOWN_SECONDS + 1)

        assert len(enqueued) == 2

    def test_a_failed_resync_releases_the_guard_so_the_operator_can_retry_at_once(self, db, monkeypatch, enqueued):
        _store_order(db)
        _ml(monkeypatch, order=None)
        with pytest.raises(ResyncFailed):
            resync_order(db, ORDER_ID)

        _ml(monkeypatch, order=_ml_order(), payment=_ml_payment(), shipment=_ml_shipment())
        resync_order(db, ORDER_ID)

        assert enqueued == [([ORDER_ID], "resync")]


class TestNoConnectionHeldWhileWaitingOnMl:
    """Every HTTP call to ML must run with the DB session idle: a pooled
    connection pinned for the duration of up to 3 round trips is the
    QueuePool-exhaustion defect class (PR #811)."""

    def test_the_session_has_no_open_transaction_during_any_ml_call(self, db, monkeypatch, enqueued):
        _store_order(db)
        seen = []

        def watching(name, payload):
            async def _call(*args, **kwargs):
                seen.append((name, db.in_transaction()))
                return payload

            return _call

        monkeypatch.setattr(ml_webhook_client, "get_order", watching("order", _ml_order()))
        monkeypatch.setattr(ml_webhook_client, "get_payment", watching("payment", _ml_payment()))
        monkeypatch.setattr(ml_webhook_client, "get_shipment", watching("shipment", _ml_shipment()))
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", watching("costs", None))

        resync_order(db, ORDER_ID)

        assert {name for name, _ in seen} >= {"order", "payment", "shipment"}
        assert [name for name, in_tx in seen if in_tx] == []
        assert enqueued == [([ORDER_ID], "resync")]


class TestReleasingTheConnectionNeverCommitsOthersWrites:
    """The existence check is a read: ending its transaction must not persist
    unrelated pending writes the caller's session holds, nor commit when the
    guard then refuses."""

    def _pending_unrelated_write(self, db):
        other = ORDER_ID + 1
        db.add(
            MlOrdersOps(
                order_id=other,
                status="paid",
                ml_last_updated=STORED_AT,
                date_created=STORED_AT,
                seller_id=999,
            )
        )
        return other

    def _persisted(self, db, order_id):
        return db.query(MlOrdersOps.order_id).filter(MlOrdersOps.order_id == order_id).first() is not None

    def test_a_refused_resync_does_not_commit_pending_writes(self, db, monkeypatch, enqueued):
        _store_order(db)
        _ml(monkeypatch, order=_ml_order(), payment=_ml_payment(), shipment=_ml_shipment())
        assert resync_service._try_begin(ORDER_ID)
        other = self._pending_unrelated_write(db)

        with pytest.raises(ResyncInProgress):
            resync_order(db, ORDER_ID)

        assert not self._persisted(db, other)

    def test_a_resync_does_not_commit_pending_writes_while_waiting_on_ml(self, db, monkeypatch, enqueued):
        _store_order(db)
        other = self._pending_unrelated_write(db)
        seen = []

        async def _order(*args, **kwargs):
            seen.append(self._persisted(db, other))
            return None

        monkeypatch.setattr(ml_webhook_client, "get_order", _order)

        with pytest.raises(ResyncFailed):
            resync_order(db, ORDER_ID)

        assert seen == [False]


class TestGuardPrunesExpiredEntries:
    def test_a_finished_entry_is_dropped_once_its_cooldown_passed(self, db, monkeypatch, enqueued):
        _store_order(db)
        _ml(monkeypatch, order=_ml_order(), payment=_ml_payment(), shipment=_ml_shipment())
        resync_order(db, ORDER_ID, monotonic=lambda: 1000.0)
        assert ORDER_ID in resync_service._finished_at

        later = 1000.0 + resync_service.COOLDOWN_SECONDS + 1
        assert resync_service._try_begin(ORDER_ID + 1, monotonic=lambda: later)

        assert ORDER_ID not in resync_service._finished_at

    def test_end_prunes_too_and_keeps_entries_still_cooling_down(self):
        resync_service._finished_at[1] = 1000.0
        resync_service._finished_at[2] = 1500.0
        resync_service._in_flight.add(3)

        resync_service._end(3, completed=True, monotonic=lambda: 1500.0 + 1)

        assert set(resync_service._finished_at) == {2, 3}


class TestEnqueueOrderMetrics:
    """The portable half of the explicit enqueue (SQLite here; Postgres runs
    the PL/pgSQL `order_metrics_enqueue`, same semantics)."""

    def test_inserts_a_dirty_row(self, db):
        db.add(MlOrdersOps(order_id=ORDER_ID, status="paid", ml_last_updated=STORED_AT, seller_id=999))
        db.flush()
        enqueue_order_metrics(db, [ORDER_ID], "resync")
        row = db.query(MlOrderMetricsDirty).filter_by(order_id=ORDER_ID).one()
        assert (row.reason, row.version, row.attempts) == ("resync", 1, 0)

    def test_requeues_an_already_dirty_row_bumping_the_version_and_clearing_the_failure(self, db):
        db.add(MlOrdersOps(order_id=ORDER_ID, status="paid", ml_last_updated=STORED_AT, seller_id=999))
        db.flush()
        db.add(MlOrderMetricsDirty(order_id=ORDER_ID, reason="x", version=3, attempts=5, last_error="boom"))
        db.flush()
        enqueue_order_metrics(db, [ORDER_ID], "resync")
        row = db.query(MlOrderMetricsDirty).filter_by(order_id=ORDER_ID).one()
        assert (row.version, row.attempts, row.last_error, row.reason) == (4, 0, None, "resync")
