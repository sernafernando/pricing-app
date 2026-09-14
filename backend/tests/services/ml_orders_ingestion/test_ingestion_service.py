"""Tests for the ML orders ingestion write path (slice 3).

Contract, not just behaviour (obs #1843 lesson): every test here asserts
what `upsert_order`'s docstring PROMISES -- fail-closed on a mapping error,
idempotent/guarded upsert, flag-gated writes -- not merely what the code
happens to do today.
"""

from __future__ import annotations

from datetime import datetime, timezone


import pytest

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.models.ml_orders_ops import (
    INGEST_FAILED_KIND,
    MlOpsDivergence,
    MlOrderItemOps,
    MlOrdersOps,
    MlOrdersOpsCuarentena,
    MlShipmentOps,
)
from app.services.ml_orders_ingestion import ingestion_service
from app.services.ml_orders_ingestion.ingestion_service import (
    UpsertOutcome,
    retry_quarantined_orders,
    upsert_order,
    upsert_shipment,
)


def _order_payload(
    order_id: int = 111,
    seller_id: int = 999,
    last_updated: str = "2026-08-20T10:00:00.000-04:00",
    status: str = "paid",
    item_id: str = "MLA1",
) -> dict:
    return {
        "id": order_id,
        "status": status,
        "date_created": "2026-08-19T10:00:00.000-04:00",
        "date_last_updated": last_updated,
        "seller": {"id": seller_id},
        "buyer": {"id": 55, "nickname": "comprador"},
        "total_amount": 100.0,
        "paid_amount": 100.0,
        "currency_id": "ARS",
        "order_items": [
            {
                "item": {"id": item_id, "seller_sku": "SKU-1", "title": "Producto"},
                "quantity": 1,
                "unit_price": 100.0,
            }
        ],
    }


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


class TestUpsertOrderFlagGate:
    def test_flag_off_writes_nothing(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        outcome = upsert_order(db, _order_payload())
        assert outcome == UpsertOutcome.DISABLED
        assert db.query(MlOrdersOps).count() == 0
        assert db.query(MlOrderItemOps).count() == 0


class TestUpsertOrderHappyPath:
    def test_creates_order_and_items(self, db):
        outcome = upsert_order(db, _order_payload())
        assert outcome == UpsertOutcome.OK

        row = db.query(MlOrdersOps).filter_by(order_id=111).one()
        assert row.status == "paid"
        assert row.seller_id == 999

        items = db.query(MlOrderItemOps).filter_by(order_id=111).all()
        assert len(items) == 1
        assert items[0].item_id == "MLA1"

    def test_never_raises_on_malformed_payload(self, db):
        """Fail-closed contract: a broken payload NEVER propagates an
        exception up to the caller (this is exactly the shape of the
        slice-2 mapper bug, obs #1843 -- the sweep must not die mid-window
        because one row is malformed)."""
        outcome = upsert_order(db, {"id": "not-an-int"})
        assert outcome == UpsertOutcome.MAPPING_ERROR
        assert db.query(MlOrdersOps).count() == 0


class TestUpsertOrderIdempotency:
    def test_same_payload_twice_is_a_structural_noop(self, db):
        """Re-ingesting the identical payload (same order_id, same
        ml_last_updated) must never duplicate the row or corrupt it -- the
        `ON CONFLICT ... WHERE excluded.ml_last_updated > stored` guard
        makes a genuinely identical re-ingest a no-op on the second call."""
        payload = _order_payload()
        first = upsert_order(db, payload)
        second = upsert_order(db, payload)

        assert first == UpsertOutcome.OK
        assert second == UpsertOutcome.SKIPPED_STALE
        assert db.query(MlOrdersOps).filter_by(order_id=111).count() == 1
        assert db.query(MlOrderItemOps).filter_by(order_id=111).count() == 1

    def test_newer_update_overwrites_stored_row(self, db):
        payload_v1 = _order_payload(status="paid", last_updated="2026-08-20T10:00:00.000-04:00")
        payload_v2 = _order_payload(status="cancelled", last_updated="2026-08-21T10:00:00.000-04:00")

        upsert_order(db, payload_v1)
        outcome = upsert_order(db, payload_v2)

        assert outcome == UpsertOutcome.OK
        row = db.query(MlOrdersOps).filter_by(order_id=111).one()
        assert row.status == "cancelled"
        assert db.query(MlOrdersOps).filter_by(order_id=111).count() == 1

    def test_stale_update_arriving_after_newer_is_discarded(self, db):
        """Out-of-order webhook/sweep race: an OLDER `date_last_updated`
        arriving after a NEWER one has already been stored must leave the
        stored row completely unchanged, and must be reported explicitly
        so the caller can log it rather than silently overwrite truth."""
        newer = _order_payload(status="paid", last_updated="2026-08-21T10:00:00.000-04:00")
        older = _order_payload(status="cancelled", last_updated="2026-08-20T10:00:00.000-04:00")

        upsert_order(db, newer)
        outcome = upsert_order(db, older)

        assert outcome == UpsertOutcome.SKIPPED_STALE
        row = db.query(MlOrdersOps).filter_by(order_id=111).one()
        assert row.status == "paid"  # unchanged -- the stale write never applied


class TestUpsertOrderNoDuplicateItems:
    def test_re_ingesting_a_newer_payload_does_not_duplicate_items(self, db):
        # variation_id is set (not None) here: the unique constraint on
        # (order_id, item_id, variation_id) is declared
        # `postgresql_nulls_not_distinct=True` so a NULL variation_id still
        # dedupes correctly on real Postgres, but SQLite (this test's
        # engine, see tests/conftest.py) has no equivalent for a NULL
        # column in a UNIQUE index -- same accepted gap as slice 1's model
        # tests (obs #1827, item 5: no live Postgres round-trip available
        # in this environment).
        v1 = _order_payload(last_updated="2026-08-20T10:00:00.000-04:00")
        v1["order_items"][0]["item"]["variation_id"] = 77
        v2 = _order_payload(last_updated="2026-08-21T10:00:00.000-04:00")
        v2["order_items"][0]["item"]["variation_id"] = 77
        upsert_order(db, v1)
        upsert_order(db, v2)

        assert db.query(MlOrderItemOps).filter_by(order_id=111, item_id="MLA1").count() == 1


class TestUpsertOrderDeletesStaleItems:
    def test_item_removed_from_a_newer_payload_is_deleted(self, db):
        """A source-of-truth table cannot accumulate phantom items: if a
        newer payload for the same order no longer lists an item (partial
        cancellation, variation change), the stale
        `ml_order_items_ops` row for it must be deleted in the SAME
        transaction as the upsert -- not just left to rot forever."""
        v1 = _order_payload(last_updated="2026-08-20T10:00:00.000-04:00")
        v1["order_items"] = [
            {"item": {"id": "MLA1", "seller_sku": "SKU-1"}, "quantity": 1, "unit_price": 100.0},
            {"item": {"id": "MLA2", "seller_sku": "SKU-2"}, "quantity": 1, "unit_price": 50.0},
        ]
        v2 = _order_payload(last_updated="2026-08-21T10:00:00.000-04:00")
        v2["order_items"] = [
            {"item": {"id": "MLA1", "seller_sku": "SKU-1"}, "quantity": 1, "unit_price": 100.0},
        ]

        first = upsert_order(db, v1)
        assert db.query(MlOrderItemOps).filter_by(order_id=111).count() == 2

        second = upsert_order(db, v2)

        assert first == UpsertOutcome.OK
        assert second == UpsertOutcome.OK
        remaining = db.query(MlOrderItemOps).filter_by(order_id=111).all()
        assert {row.item_id for row in remaining} == {"MLA1"}

    def test_stale_update_does_not_delete_items(self, db):
        """A `SKIPPED_STALE` outcome must leave the items table exactly as
        untouched as the order row -- deleting items on a stale/no-op
        write would be worse than not deleting them at all."""
        newer = _order_payload(last_updated="2026-08-21T10:00:00.000-04:00")
        newer["order_items"] = [
            {"item": {"id": "MLA1"}, "quantity": 1, "unit_price": 100.0},
        ]
        older_but_fewer_items = _order_payload(last_updated="2026-08-20T10:00:00.000-04:00")
        older_but_fewer_items["order_items"] = []

        upsert_order(db, newer)
        outcome = upsert_order(db, older_but_fewer_items)

        assert outcome == UpsertOutcome.SKIPPED_STALE
        assert db.query(MlOrderItemOps).filter_by(order_id=111).count() == 1


def _shipment_payload(
    shipment_id: int = 900,
    order_id: int = 111,
    status: str = "shipped",
    last_updated: str = "2026-08-20T10:00:00.000-04:00",
) -> dict:
    return {
        "id": shipment_id,
        "order_id": order_id,
        "status": status,
        "substatus": None,
        "logistic_type": "cross_docking",
        "tracking_number": "TRACK1",
        "tracking_method": "correo",
        "date_created": "2026-08-19T10:00:00.000-04:00",
        "last_updated": last_updated,
        "receiver_address": {"city": "CABA"},
    }


class TestUpsertShipmentFlagGate:
    def test_flag_off_writes_nothing(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        outcome = upsert_shipment(db, _shipment_payload())
        assert outcome == UpsertOutcome.DISABLED
        assert db.query(MlShipmentOps).count() == 0


class TestUpsertShipment:
    def test_creates_shipment_row(self, db):
        outcome = upsert_shipment(db, _shipment_payload())

        assert outcome == UpsertOutcome.OK
        row = db.query(MlShipmentOps).filter_by(shipment_id=900).one()
        assert row.order_id == 111
        assert row.status == "shipped"
        assert row.tracking_number == "TRACK1"

    def test_mapping_error_for_malformed_payload_writes_nothing(self, db):
        outcome = upsert_shipment(db, {"order_id": 111})  # missing required "id"

        assert outcome == UpsertOutcome.MAPPING_ERROR
        assert db.query(MlShipmentOps).count() == 0

    def test_never_raises_on_malformed_payload(self, db):
        outcome = upsert_shipment(db, "not-a-dict")  # type: ignore[arg-type]
        assert outcome == UpsertOutcome.MAPPING_ERROR

    def test_newer_update_overwrites_stored_row(self, db):
        upsert_shipment(db, _shipment_payload(status="ready_to_ship", last_updated="2026-08-20T10:00:00.000-04:00"))
        outcome = upsert_shipment(
            db, _shipment_payload(status="delivered", last_updated="2026-08-21T10:00:00.000-04:00")
        )

        assert outcome == UpsertOutcome.OK
        row = db.query(MlShipmentOps).filter_by(shipment_id=900).one()
        assert row.status == "delivered"

    def test_stale_update_is_skipped(self, db):
        upsert_shipment(db, _shipment_payload(status="delivered", last_updated="2026-08-21T10:00:00.000-04:00"))
        outcome = upsert_shipment(
            db, _shipment_payload(status="ready_to_ship", last_updated="2026-08-20T10:00:00.000-04:00")
        )

        assert outcome == UpsertOutcome.SKIPPED_STALE
        row = db.query(MlShipmentOps).filter_by(shipment_id=900).one()
        assert row.status == "delivered"

    def test_shipment_with_no_last_updated_always_overwrites(self, db):
        """A shipment payload that ever omits `last_updated` has nothing
        to compare against, so it must always apply rather than getting
        permanently stuck as stale against itself."""
        upsert_shipment(db, _shipment_payload(status="shipped", last_updated=""))
        payload2 = _shipment_payload(status="delivered", last_updated="")
        outcome = upsert_shipment(db, payload2)

        assert outcome == UpsertOutcome.OK
        row = db.query(MlShipmentOps).filter_by(shipment_id=900).one()
        assert row.status == "delivered"


class TestTheNoShippingTagIsPersisted:
    """The router reads `ml_orders_ops.has_no_shipping_tag` to resolve the
    logistic mode. If the write path stops filling it, every store-pickup
    sale silently reads as `desconocido` -- green tests, wrong production."""

    def test_an_order_tagged_no_shipping_stores_true(self, db):
        payload = _order_payload(order_id=901)
        payload["tags"] = ["paid", "no_shipping"]

        assert upsert_order(db, payload) == UpsertOutcome.OK

        row = db.query(MlOrdersOps).filter_by(order_id=901).one()
        assert row.has_no_shipping_tag is True

    def test_an_order_without_the_tag_stores_false_not_null(self, db):
        """False, not NULL: the router coerces with `bool(...)`, so a NULL
        reads the same as False and would hide a write path that never
        ran."""
        payload = _order_payload(order_id=902)
        payload["tags"] = ["paid"]

        assert upsert_order(db, payload) == UpsertOutcome.OK

        row = db.query(MlOrdersOps).filter_by(order_id=902).one()
        assert row.has_no_shipping_tag is False


class TestUpsertOrderWriteError:
    """2026-09-14 incident: a `status_detail` payload shaped as a dict
    poisoned the batch transaction and stalled ingestion for four days.
    `WRITE_ERROR` is the isolation half of the fix -- see
    `TestRetryQuarantinedOrders` for the recovery half."""

    def test_a_db_write_failure_returns_write_error_and_writes_nothing(self, db, monkeypatch):
        def _boom(*args, **kwargs):
            raise SQLAlchemyError("can't adapt type 'dict'")

        monkeypatch.setattr(ingestion_service, "_upsert_item_row", _boom)

        outcome = upsert_order(db, _order_payload(order_id=222))

        assert outcome == UpsertOutcome.WRITE_ERROR
        assert db.query(MlOrdersOps).filter_by(order_id=222).count() == 0
        assert db.query(MlOrderItemOps).filter_by(order_id=222).count() == 0

    def test_never_raises_for_a_db_write_failure(self, db, monkeypatch):
        def _boom(*args, **kwargs):
            raise SQLAlchemyError("boom")

        monkeypatch.setattr(ingestion_service, "_upsert_item_row", _boom)

        # Must not raise -- this IS the assertion.
        outcome = upsert_order(db, _order_payload(order_id=223))
        assert outcome == UpsertOutcome.WRITE_ERROR

    def test_write_error_quarantines_the_raw_payload(self, db, monkeypatch):
        def _boom(*args, **kwargs):
            raise SQLAlchemyError("can't adapt type 'dict'")

        monkeypatch.setattr(ingestion_service, "_upsert_item_row", _boom)
        payload = _order_payload(order_id=224)

        upsert_order(db, payload)

        row = db.query(MlOrdersOpsCuarentena).filter_by(order_id=224).one()
        assert row.raw_order == payload
        assert "can't adapt type 'dict'" in row.error
        assert row.intentos == 1

    def test_write_error_opens_an_ingest_failed_divergence(self, db, monkeypatch):
        """The user's explicit requirement: a quarantined order must be
        VISIBLE on the divergences dashboard, not just in a log line."""

        def _boom(*args, **kwargs):
            raise SQLAlchemyError("boom")

        monkeypatch.setattr(ingestion_service, "_upsert_item_row", _boom)

        upsert_order(db, _order_payload(order_id=225))

        row = db.query(MlOpsDivergence).filter_by(order_id=225, kind=INGEST_FAILED_KIND).one()
        assert row.state == "open"
        assert "boom" in row.ml_value

    def test_a_healthy_order_in_the_same_session_is_unaffected_by_a_prior_write_error(self, db, monkeypatch):
        """SQLite-only guardrail (see the Postgres-marked test in
        test_sweep_service.py for the real transaction-poisoning proof):
        at minimum, the ORM-level state after a `WRITE_ERROR` must not
        prevent the very next call in the same session from succeeding."""

        def _boom(*args, **kwargs):
            raise SQLAlchemyError("boom")

        monkeypatch.setattr(ingestion_service, "_upsert_item_row", _boom)
        upsert_order(db, _order_payload(order_id=226))

        monkeypatch.undo()
        outcome = upsert_order(db, _order_payload(order_id=227))

        assert outcome == UpsertOutcome.OK
        assert db.query(MlOrdersOps).filter_by(order_id=227).count() == 1


class TestRetryQuarantinedOrders:
    def test_recovers_an_order_once_the_defect_is_fixed(self, db):
        payload = _order_payload(order_id=333)
        db.add(
            MlOrdersOpsCuarentena(
                order_id=333,
                raw_order=payload,
                error="can't adapt type 'dict'",
                intentos=1,
            )
        )
        db.flush()

        result = retry_quarantined_orders(db)

        assert result.attempted == 1
        assert result.recovered == 1
        assert result.still_failed == 0
        assert db.query(MlOrdersOps).filter_by(order_id=333).count() == 1
        assert db.query(MlOrdersOpsCuarentena).filter_by(order_id=333).count() == 0

    def test_recovering_an_order_resolves_its_ingest_failed_divergence(self, db):
        """An alarm for a problem that fixed itself must not stay open
        forever (explicit user requirement)."""
        payload = _order_payload(order_id=334)
        db.add(MlOrdersOpsCuarentena(order_id=334, raw_order=payload, error="boom", intentos=1))
        db.add(
            MlOpsDivergence(
                order_id=334,
                kind=INGEST_FAILED_KIND,
                field=None,
                ml_value="boom",
                state="open",
            )
        )
        db.flush()

        retry_quarantined_orders(db)

        row = db.query(MlOpsDivergence).filter_by(order_id=334, kind=INGEST_FAILED_KIND).one()
        assert row.state == "resolved"

    def test_an_order_that_still_fails_stays_quarantined_with_incremented_attempts(self, db, monkeypatch):
        def _boom(*args, **kwargs):
            raise SQLAlchemyError("still broken")

        payload = _order_payload(order_id=335)
        db.add(MlOrdersOpsCuarentena(order_id=335, raw_order=payload, error="boom", intentos=1))
        db.flush()

        monkeypatch.setattr(ingestion_service, "_upsert_item_row", _boom)
        result = retry_quarantined_orders(db)

        assert result.attempted == 1
        assert result.recovered == 0
        assert result.still_failed == 1
        row = db.query(MlOrdersOpsCuarentena).filter_by(order_id=335).one()
        assert row.intentos == 2
        assert "still broken" in row.error

    def test_zero_http_calls_are_made(self, db, monkeypatch):
        """The whole point of storing `raw_order` is that a retry replays
        it directly -- no re-fetch from ML."""
        import app.services.ml_webhook_client as ml_webhook_client_module

        def _fail_any_http_call(*args, **kwargs):
            raise AssertionError("retry_quarantined_orders must not make HTTP calls")

        monkeypatch.setattr(ml_webhook_client_module.ml_webhook_client, "get", _fail_any_http_call, raising=False)

        payload = _order_payload(order_id=336)
        db.add(MlOrdersOpsCuarentena(order_id=336, raw_order=payload, error="boom", intentos=1))
        db.flush()

        result = retry_quarantined_orders(db)
        assert result.recovered == 1

    def test_respects_a_per_pass_retry_limit(self, db):
        for order_id in range(400, 410):
            db.add(
                MlOrdersOpsCuarentena(
                    order_id=order_id,
                    raw_order=_order_payload(order_id=order_id),
                    error="boom",
                    intentos=1,
                )
            )
        db.flush()

        result = retry_quarantined_orders(db, limit=3)

        assert result.attempted == 3
        assert db.query(MlOrdersOpsCuarentena).count() == 7

    def test_no_quarantined_rows_is_a_cheap_noop(self, db):
        result = retry_quarantined_orders(db)
        assert result.attempted == 0
        assert result.recovered == 0
        assert result.still_failed == 0


class TestThePoisonPillCannotBlockTheQueue:
    """Ordering the retry by FIRST failure puts the oldest quarantined
    order first on every pass -- and the oldest is, by definition, the one
    that has been failing longest. A permanently poisoned order would be
    retried first forever, and past `limit` of them the newly quarantined
    ones would never get a turn at all: the queue blocked by exactly the
    rows that cannot move."""

    def test_the_least_recently_attempted_order_goes_first(self, db):
        vieja = _order_payload(order_id=801)
        nueva = _order_payload(order_id=802)
        # `801` failed first AND was retried a moment ago; `802` failed
        # later but has never been attempted since.
        db.add(
            MlOrdersOpsCuarentena(
                order_id=801,
                raw_order=vieja,
                error="boom",
                intentos=40,
                primera_falla_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                ultimo_intento_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            MlOrdersOpsCuarentena(
                order_id=802,
                raw_order=nueva,
                error="boom",
                intentos=1,
                primera_falla_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
                ultimo_intento_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            )
        )
        db.commit()

        result = retry_quarantined_orders(db, limit=1)

        assert result.attempted == 1
        # 802 is the one that has waited longest for a turn, even though
        # 801 has been in quarantine longer.
        assert db.query(MlOrdersOps).filter_by(order_id=802).count() == 1
        assert db.query(MlOrdersOps).filter_by(order_id=801).count() == 0
