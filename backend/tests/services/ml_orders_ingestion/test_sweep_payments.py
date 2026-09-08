"""
RED/GREEN — payment ingestion wired into the existing orders sweep
(ml-ventas-desglose-costos, corte 5).

No new cron/sweep: `order.payments[]` ids (already in the search page)
drive `get_payment` + `upsert_payment`. Retry gate: `MlOrdersOps.
payments_synced_at IS NULL`, mirroring `MlShipmentOps.costs_synced_at`
(post-review fix, pre-push finding 1) -- independent of the order's own
`ml_last_updated` staleness.

Spec coverage (obs #1960/#1965, measured against 514 real payments):
  REQ-1 — every `payments[].id` on a NEW order is fetched via
          `get_payment` and persisted; `payments_synced_at` is sealed.
  REQ-2 — an order already sealed (`payments_synced_at IS NOT NULL`) does
          NOT refetch its payments, even while stale -- same discipline
          as the shipment/cost sync, avoiding wasted calls on the
          steady-state overlap window.
  REQ-3 — a RE-INGESTED order (its own `date_last_updated` moved, e.g. a
          return), EVEN WHEN its `payments_synced_at` was already sealed
          by an earlier pass, DOES still refetch -- see
          `test_reingestion_refetches_even_when_already_sealed`.
  REQ-4 — order 2000018322969636 (obs #1960 §a): TWO `approved` payments
          split the order's total and shipping between them; the sweep
          persists BOTH as separate `MlPaymentOps` rows.
  REQ-5 — a payment fetch failure/mapping error is fail-open (never
          blocks the order upsert or crashes the pass) AND leaves
          `payments_synced_at` NULL so the NEXT pass retries -- this is
          finding 1's core fix: the old trigger (`UpsertOutcome.OK`) was
          one-shot and lost a failed payment forever once the order
          stopped being stale.
  REQ-6 — `PASS_TIME_BUDGET` cuts the payment sync short exactly like it
          does the shipment/cost sync: an order whose deadline is
          already spent is left with `payments_synced_at` NULL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import ml_webhook_client


def _order(order_id: int, seller_id: int, when: datetime, created: datetime, payment_ids=None) -> dict:
    order = {
        "id": order_id,
        "status": "paid",
        "date_created": created.isoformat(),
        "date_last_updated": when.isoformat(),
        "seller": {"id": seller_id},
        "buyer": {"id": 1, "nickname": "x"},
        "order_items": [],
    }
    if payment_ids is not None:
        order["payments"] = [{"id": pid} for pid in payment_ids]
    return order


def _page(results, total=None):
    return {"results": results, "paging": {"total": total if total is not None else len(results)}}


def _payment_payload(payment_id: int, order_id: int, **overrides) -> dict:
    base = {
        "payment_id": payment_id,
        "order_id": order_id,
        "status": "approved",
        "currency_id": "ARS",
        "net_received_amount": 6800.50,
        "total_paid_amount": 7371.11,
        "transaction_amount": 7371.11,
        "shipping_amount": 0,
        "coupon_amount": 0,
        "taxes_amount": 0,
        "transaction_amount_refunded": 0,
        "charges_details": [],
    }
    base.update(overrides)
    return base


def _fake_ctx(db):
    """Bridges `sweep_service.get_background_db()` to the sqlite `db`
    fixture -- same pattern as `test_sweep_service.py`."""

    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 90)


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))


@pytest.fixture(autouse=True)
def _no_real_cost_fetch(monkeypatch):
    """This module never exercises the cost sync; cut it to a benign
    structurally-valid payload so it never reaches the network."""
    monkeypatch.setattr(
        ml_webhook_client,
        "get_shipment_costs",
        AsyncMock(return_value={"gross_amount": 0, "receiver": {"cost": 0}, "senders": [{"cost": 0}]}),
    )


class TestPaymentFetchOnIngest:
    def test_payment_ids_are_fetched_and_persisted(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_called_once_with(500)
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.order_id == 1
        assert row.net_received_amount == Decimal("6800.50")

        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is not None

    def test_already_sealed_order_never_refetches_even_while_stale(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=now, date_created=now, payments_synced_at=now))
        db.commit()

        order = _order(1, 999, now, now, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_not_called()
        assert db.query(MlPaymentOps).count() == 0

    def test_reingestion_refetches_even_when_already_sealed(self, db, monkeypatch) -> None:
        """A return moves the order's OWN `date_last_updated` -- it must
        refetch its payments even though `payments_synced_at` was already
        set by an earlier pass. The retry gate (finding 1) augments the
        original trigger, it does not replace it."""
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        order = _order(1, 999, now, earlier, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1, status="refunded", net_received_amount=0))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_called_once_with(500)
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.status == "refunded"
        assert row.net_received_amount == Decimal("0")

    def test_split_payments_both_persist_as_separate_rows(self, db, monkeypatch) -> None:
        """Order 2000018322969636 (obs #1960): two `approved` payments
        split the order's total AND its shipping amount between them."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(2000018322969636, 999, recent, recent, payment_ids=[1, 2])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))

        async def mock_get_payment(payment_id):
            if payment_id == 1:
                return _payment_payload(
                    1, 2000018322969636, net_received_amount=7371.11, shipping_amount=6990, transaction_amount=7371.11
                )
            return _payment_payload(
                2, 2000018322969636, net_received_amount=12528.89, shipping_amount=0, transaction_amount=12528.89
            )

        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        rows = db.query(MlPaymentOps).filter_by(order_id=2000018322969636).all()
        assert len(rows) == 2
        totals = {row.payment_id: row.net_received_amount for row in rows}
        assert totals[1] == Decimal("7371.11")
        assert totals[2] == Decimal("12528.89")
        shipping = {row.payment_id: row.shipping_amount for row in rows}
        assert shipping[1] == Decimal("6990")
        assert shipping[2] == Decimal("0")

    def test_order_with_no_payments_never_calls_get_payment_but_is_sealed(self, db, monkeypatch) -> None:
        """`payments: []` -- ML's own contract says this order genuinely
        has none -- is trivially "fully synced" and must still seal
        `payments_synced_at`, or a payment-less order would be re-queried
        on every single pass forever. Note this is `payment_ids=[]`, NOT
        the key absent entirely: an absent key is a different, unknown-
        state fact (see `sync_payments_for_order`'s post-review fix) and
        must NOT seal."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_not_called()
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is not None

    def test_the_payments_key_absent_entirely_is_never_sealed(self, db, monkeypatch) -> None:
        """The absent key is NOT the same fact as `payments: []` -- it
        means the source never told us either way, and must be treated
        as unresolved, never as "zero payments, done" (post-review
        blocking fix, ml-backfill-pagos-y-costos)."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=None)
        assert "payments" not in order
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_not_called()
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is None


class TestRetryGate:
    """Finding 1 (BLOCKING): the retry gate must survive a failed fetch,
    not lose the payment forever once the order stops being stale."""

    def test_fetch_failure_leaves_the_order_unsealed_and_order_upsert_unblocked(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))

        async def raises(payment_id):
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_payment", raises)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.error is None
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row is not None  # the order itself was NOT blocked by the payment failure
        assert order_row.payments_synced_at is None  # left NULL: must retry next pass
        assert db.query(MlPaymentOps).count() == 0

    def test_the_next_pass_retries_and_succeeds(self, db, monkeypatch) -> None:
        """The exact regression this fix closes: a failed fetch, followed
        by a pass where the order is no longer stale, must STILL retry --
        the old `UpsertOutcome.OK`-only trigger would have skipped this
        pass entirely and left the payment missing forever."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))

        async def raises(payment_id):
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_payment", raises)
        sweep_service.run_sweep(seller_id=999, window_days=90)
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is None

        # Second pass: the SAME (now unchanged/stale) order, but the
        # payment fetch succeeds this time.
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_called_once_with(500)
        assert db.query(MlPaymentOps).filter_by(payment_id=500).one() is not None
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is not None

    def test_partial_success_across_two_payment_ids_leaves_the_order_unsealed(self, db, monkeypatch) -> None:
        """One payment id resolves, the other fails: BOTH must be retried
        next pass -- sealing on a partial result would silently lose the
        one that failed."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500, 501])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))

        async def flaky(payment_id):
            if payment_id == 500:
                return _payment_payload(500, 1)
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_payment", flaky)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert db.query(MlPaymentOps).filter_by(payment_id=500).one() is not None
        assert db.query(MlPaymentOps).filter_by(payment_id=501).count() == 0
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is None


class TestPassTimeBudgetCutsPaymentSync:
    def test_deadline_already_spent_leaves_the_order_unsealed(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        long_ago = now - sweep_service.PASS_TIME_BUDGET - timedelta(minutes=1)
        payment_budget: list = [sweep_service.MAX_PAYMENT_FETCHES_PER_PASS]
        result = sweep_service.SweepResult(ran=True)

        sweep_service.process_batch(
            [order],
            recent - timedelta(days=1),
            result,
            pass_started_at=long_ago,
            payment_budget=payment_budget,
        )

        mock_get_payment.assert_not_called()
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is None

    def test_payment_budget_exhausted_leaves_the_order_unsealed(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        result = sweep_service.SweepResult(ran=True)
        sweep_service.process_batch(
            [order],
            recent - timedelta(days=1),
            result,
            pass_started_at=now,
            payment_budget=[0],
        )

        mock_get_payment.assert_not_called()
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is None
