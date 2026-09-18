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
from contextlib import contextmanager

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps
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

    def test_the_payments_key_absent_on_a_fresh_order_is_sealed_and_recorded(self, db, monkeypatch) -> None:
        """The absent key is NOT the same fact as `payments: []`, but
        `raw_order` here is FRESH off `search_orders` -- ML's own
        omission IS ML's answer. Sealing is correct (a payment-less order
        must not be re-queried forever), but it must stay VISIBLE via a
        divergence row instead of silently vanishing (post-review fix
        #1/#2, ml-backfill-pagos-y-costos): only the BACKFILL's stored,
        not-guaranteed-fresh `raw_order` must refuse to seal on this."""
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
        assert order_row.payments_synced_at is not None
        divergence = (
            db.query(MlOpsDivergence)
            .filter_by(order_id=1, kind="unknown", field=sweep_service.PAYMENTS_KEY_MISSING_FIELD)
            .one()
        )
        assert divergence is not None


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


class TestDeferredRecheckRunsIndependentlyOfSearchWindow:
    """`_orders_due_for_payments_recheck` as used
    INSIDE `process_batch` only ever sees whatever `search_orders`
    returned for THIS pass's window. `CURSOR_OVERLAP` is 15 minutes and
    `RECHECK_AFTER` is 60 -- by the time a recheck is due, the exact order
    this feature exists for (one whose `date_last_updated` stopped
    moving) has long fallen out of the window and never reaches
    `process_batch` again. `_run_deferred_payments_rechecks` must select
    it straight from the database instead."""

    def test_order_absent_from_search_results_still_gets_its_due_recheck(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        stored_raw_order = _order(1, 999, earlier, earlier, payment_ids=[500])
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
                payments_recheck_at=now - timedelta(minutes=1),  # already due
                raw_order=stored_raw_order,
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        # The search NEVER hands this order back -- it fell outside every
        # window's overlap, exactly like the production incident. The
        # test would be worthless if the mock returned the order anyway.
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1, status="refunded", net_received_amount=0))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_called_once_with(500)
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.status == "refunded"
        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_recheck_at is None

    def test_due_recheck_whose_payment_fetch_fails_is_rescheduled_forward_not_left_on_the_same_due_mark(
        self, db, monkeypatch
    ) -> None:
        """A partial/failed re-ask must NOT clear `payments_recheck_at` --
        sealing never happens on a fetch failure, so the old comment's
        claimed fallback onto `payments_synced_at IS NULL` does not
        exist, and clearing the mark anyway would lose the re-ask for
        good. But it must ALSO not sit on the SAME already-past-due
        timestamp forever -- that starves every other due order of
        budget on every future pass. `payments_recheck_at` must move
        strictly forward, roughly to `now + RECHECK_AFTER`.

        `assert payments_recheck_at is not None` alone does NOT
        distinguish the fix from the bug it replaces (leaving the mark
        untouched also leaves it not-None), so this asserts the mark
        actually advanced past its original due timestamp."""
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        original_due_at = now - timedelta(minutes=1)
        stored_raw_order = _order(1, 999, earlier, earlier, payment_ids=[500])
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
                payments_recheck_at=original_due_at,
                raw_order=stored_raw_order,
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([])))
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(side_effect=RuntimeError("proxy timeout")))

        sweep_service.run_sweep(seller_id=999, window_days=90)

        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_recheck_at is not None
        rescheduled = order_row.payments_recheck_at
        if rescheduled.tzinfo is None:
            rescheduled = rescheduled.replace(tzinfo=timezone.utc)
        # Must have moved strictly forward of the original due mark --
        # NOT left untouched at `original_due_at`.
        assert rescheduled > original_due_at
        # And it should land close to `now + RECHECK_AFTER`, not just
        # "somewhere later".
        expected = now + sweep_service.RECHECK_AFTER
        assert abs((rescheduled - expected).total_seconds()) < 5
        # Unchanged -- the failed fetch never persisted anything new.
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.status == "approved"


class TestDeferredRecheckSelectionQuery:
    """`_run_deferred_payments_rechecks`'s own SQL selection: a row with
    no `raw_order` must not consume a LIMIT slot, the LIMIT must drain
    oldest-due-first, and the query must be scoped to the requesting
    seller."""

    def _due_order(self, db, order_id: int, seller_id: int, recheck_at: datetime, payment_id: int, raw_order=...):
        kwargs = dict(
            order_id=order_id,
            seller_id=seller_id,
            ml_last_updated=recheck_at - timedelta(days=1),
            date_created=recheck_at - timedelta(days=1),
            payments_synced_at=recheck_at - timedelta(days=1),
            payments_recheck_at=recheck_at,
        )
        # `raw_order` is a JSONB column with SQLAlchemy's default
        # `none_as_null=False`: explicitly assigning Python `None` writes
        # a JSON *literal* null, NOT SQL NULL. A genuinely un-backfilled
        # row (the real-world case this recheck query must exclude) is
        # one where the column was simply never written -- true SQL
        # NULL. The sentinel default lets a caller omit `raw_order`
        # entirely to reproduce that, while still allowing an explicit
        # payload to be passed for the normal case.
        if raw_order is not ...:
            kwargs["raw_order"] = raw_order
        db.add(MlOrdersOps(**kwargs))
        if payment_id is not None:
            db.add(MlPaymentOps(payment_id=payment_id, order_id=order_id, status="approved"))

    def test_row_with_null_raw_order_does_not_consume_the_limit_slot(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        # The NULL-payload row is due FIRST (earlier recheck_at) so, if the
        # SQL filter did not exclude it, it would win the LIMIT-1 slot.
        # `raw_order` is intentionally omitted (never written) so the
        # column is true SQL NULL -- see `_due_order`'s docstring.
        self._due_order(db, order_id=1, seller_id=999, recheck_at=now - timedelta(minutes=10), payment_id=None)
        self._due_order(
            db,
            order_id=2,
            seller_id=999,
            recheck_at=now - timedelta(minutes=1),
            payment_id=500,
            raw_order=_order(2, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[500]),
        )
        db.commit()

        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 2, status="refunded"))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[2], pass_started_at=now, seller_id=999)

        # Order 2's payment fetch happened even though the LIMIT was 1 and
        # order 1 (NULL raw_order) was due earlier -- proving order 1 never
        # occupied the slot.
        mock_get_payment.assert_called_once_with(500)

    def test_limit_drains_oldest_due_first(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        # Both insertion order AND primary-key order are DELIBERATELY the
        # REVERSE of due-date order: order_id=1 (lower pk, inserted
        # first) is due LAST (only 1 minute ago); order_id=2 (higher pk,
        # inserted second) is due FIRST (30 minutes ago). SQLite's
        # implicit ordering without an explicit ORDER BY tends to follow
        # rowid/insertion order, so this layout cannot pass by accident --
        # only a real `ORDER BY payments_recheck_at ASC` selects order 2.
        self._due_order(
            db,
            order_id=1,
            seller_id=999,
            recheck_at=now - timedelta(minutes=1),
            payment_id=500,
            raw_order=_order(1, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[500]),
        )
        self._due_order(
            db,
            order_id=2,
            seller_id=999,
            recheck_at=now - timedelta(minutes=30),
            payment_id=501,
            raw_order=_order(2, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[501]),
        )
        db.commit()

        mock_get_payment = AsyncMock(
            side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, status="refunded")
        )
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[2], pass_started_at=now, seller_id=999)

        # Order 2 was due 30 minutes ago (oldest); order 1 only 1 minute
        # ago. With a budget of exactly 1, only the OLDEST due order may
        # be fetched.
        mock_get_payment.assert_called_once_with(501)

    def test_query_is_scoped_to_the_requesting_seller(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        self._due_order(
            db,
            order_id=1,
            seller_id=999,
            recheck_at=now - timedelta(minutes=5),
            payment_id=500,
            raw_order=_order(1, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[500]),
        )
        self._due_order(
            db,
            order_id=2,
            seller_id=888,
            recheck_at=now - timedelta(minutes=5),
            payment_id=501,
            raw_order=_order(2, 888, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[501]),
        )
        db.commit()

        mock_get_payment = AsyncMock(
            side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, status="refunded")
        )
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        # Only seller 999's order was fetched -- seller 888's due order,
        # despite being equally due, belongs to a different account and
        # must not be touched by this call.
        mock_get_payment.assert_called_once_with(500)
        other_seller_row = db.query(MlOrdersOps).filter_by(order_id=2).one()
        assert other_seller_row.payments_recheck_at is not None
        other_recheck_at = other_seller_row.payments_recheck_at
        if other_recheck_at.tzinfo is None:
            other_recheck_at = other_recheck_at.replace(tzinfo=timezone.utc)
        # Untouched -- still at its original due timestamp (SQLite loses
        # tzinfo on refresh; compare as UTC-aware).
        assert other_recheck_at <= now


class TestDeferredRecheckExceptionIsolation:
    """One order's recheck blowing up must not abort the rest of the
    pass's due orders."""

    def test_exception_on_one_order_does_not_stop_the_others(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now - timedelta(days=1),
                date_created=now - timedelta(days=1),
                payments_synced_at=now - timedelta(days=1),
                payments_recheck_at=now - timedelta(minutes=10),
                raw_order=_order(1, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[500]),
            )
        )
        db.add(
            MlOrdersOps(
                order_id=2,
                seller_id=999,
                ml_last_updated=now - timedelta(days=1),
                date_created=now - timedelta(days=1),
                payments_synced_at=now - timedelta(days=1),
                payments_recheck_at=now - timedelta(minutes=5),
                raw_order=_order(2, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[501]),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.add(MlPaymentOps(payment_id=501, order_id=2, status="approved"))
        db.commit()

        mock_get_payment = AsyncMock(
            side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, status="refunded")
        )
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        real_sync = sweep_service.sync_payments_for_order

        def _boom_for_order_1(db_arg, order_id, raw_order, payments_payload, **kwargs):
            if order_id == 1:
                raise RuntimeError("boom")
            return real_sync(db_arg, order_id, raw_order, payments_payload, **kwargs)

        monkeypatch.setattr(sweep_service, "sync_payments_for_order", _boom_for_order_1)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        # Order 2 must still have been processed and sealed despite order
        # 1 raising.
        row2 = db.query(MlOrdersOps).filter_by(order_id=2).one()
        assert row2.payments_recheck_at is None
        payment2 = db.query(MlPaymentOps).filter_by(payment_id=501).one()
        assert payment2.status == "refunded"
        # Order 1's mark survives the crash (not cleared, not lost).
        row1 = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row1.payments_recheck_at is not None

    def test_db_flush_error_on_one_order_does_not_stop_the_others(self, db, monkeypatch) -> None:
        """A DATABASE failure, not a plain Python one, is the discriminating
        case for the per-order isolation.

        `test_exception_on_one_order_does_not_stop_the_others` raises a bare
        RuntimeError, which leaves the SQLAlchemy Session perfectly usable --
        so it passes whether or not the loop rolls back. A failure during a
        FLUSH does not: the Session refuses every later statement with
        PendingRollbackError, and `get_background_db` commits only once at
        block exit, so a catch-and-continue with no rollback loses the orders
        that had already succeeded. This test fails without the rollback and
        the per-order commit."""
        now = datetime.now(timezone.utc)
        for oid, pid, mins in ((1, 500, 10), (2, 501, 5)):
            db.add(
                MlOrdersOps(
                    order_id=oid,
                    seller_id=999,
                    ml_last_updated=now - timedelta(days=1),
                    date_created=now - timedelta(days=1),
                    payments_synced_at=now - timedelta(days=1),
                    payments_recheck_at=now - timedelta(minutes=mins),
                    raw_order=_order(oid, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[pid]),
                )
            )
            db.add(MlPaymentOps(payment_id=pid, order_id=oid, status="approved"))
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, status="refunded")),
        )

        real_sync = sweep_service.sync_payments_for_order

        def _flush_error_for_order_1(db_arg, order_id, raw_order, payments_payload, **kwargs):
            if order_id == 1:
                # Duplicate primary key -> IntegrityError on flush, which is
                # what actually poisons the Session.
                db_arg.add(MlPaymentOps(payment_id=500, order_id=1, status="dup"))
                db_arg.flush()
            return real_sync(db_arg, order_id, raw_order, payments_payload, **kwargs)

        monkeypatch.setattr(sweep_service, "sync_payments_for_order", _flush_error_for_order_1)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        # Order 2 came after the poisoned one and must still be sealed.
        payment2 = db.query(MlPaymentOps).filter_by(payment_id=501).one()
        assert payment2.status == "refunded"
        row2 = db.query(MlOrdersOps).filter_by(order_id=2).one()
        assert row2.payments_recheck_at is None
        # Order 1 keeps its mark: nothing was resolved for it.
        row1 = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row1.payments_recheck_at is not None

    def test_an_earlier_orders_work_survives_a_later_orders_db_error(self, db, monkeypatch) -> None:
        """The rollback alone is not enough -- the per-order COMMIT is what
        keeps already-finished work.

        `get_background_db` commits once, at block exit. So if order 1 seals
        and order 2 then fails during a flush, a rollback with no earlier
        commit discards order 1's seal along with order 2's garbage: an
        order that was successfully re-asked silently loses its result and
        its cleared mark. Ordering matters here -- the failure has to come
        SECOND, which is exactly what the sibling flush-error test (failure
        first) cannot show."""
        now = datetime.now(timezone.utc)
        # Order 1 is due OLDER, so FIFO ordering puts it first; order 2 is
        # the one that blows up.
        for oid, pid, mins in ((1, 500, 10), (2, 501, 5)):
            db.add(
                MlOrdersOps(
                    order_id=oid,
                    seller_id=999,
                    ml_last_updated=now - timedelta(days=1),
                    date_created=now - timedelta(days=1),
                    payments_synced_at=now - timedelta(days=1),
                    payments_recheck_at=now - timedelta(minutes=mins),
                    raw_order=_order(oid, 999, now - timedelta(days=1), now - timedelta(days=1), payment_ids=[pid]),
                )
            )
            db.add(MlPaymentOps(payment_id=pid, order_id=oid, status="approved"))
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, status="refunded")),
        )

        real_sync = sweep_service.sync_payments_for_order

        def _flush_error_for_order_2(db_arg, order_id, raw_order, payments_payload, **kwargs):
            if order_id == 2:
                db_arg.add(MlPaymentOps(payment_id=501, order_id=2, status="dup"))
                db_arg.flush()
            return real_sync(db_arg, order_id, raw_order, payments_payload, **kwargs)

        monkeypatch.setattr(sweep_service, "sync_payments_for_order", _flush_error_for_order_2)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        # Order 1 finished BEFORE the crash and must keep its result.
        payment1 = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert payment1.status == "refunded"
        row1 = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row1.payments_recheck_at is None


class TestDeferredRecheckGate:
    """ml-ventas-repreguntar-pagos-diferido: the THIRD payment-candidate
    gate. Production incident: ML can finish reversing a charge (e.g. a
    Flex shipping fee) AFTER an order's own `ml_last_updated` stops
    moving, so the two existing gates (staleness, `payments_synced_at IS
    NULL`) never fire again for that order. `payments_recheck_at` is an
    EXPLICIT one-time re-ask, not a heuristic."""

    def test_first_sync_schedules_a_recheck(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        order = _order(1, 999, recent, recent, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        sweep_service.run_sweep(seller_id=999, window_days=90)

        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_synced_at is not None
        assert order_row.payments_recheck_at is not None
        expected = order_row.payments_synced_at + sweep_service.RECHECK_AFTER
        assert abs((order_row.payments_recheck_at - expected).total_seconds()) < 5

    def test_order_due_for_recheck_is_a_candidate_even_though_not_stale_and_already_synced(
        self, db, monkeypatch
    ) -> None:
        """The exact bug this closes: an order that is NEITHER stale NOR
        missing its `payments_synced_at` seal must still be refetched
        once its recheck is due."""
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
                payments_recheck_at=now - timedelta(minutes=1),  # already due
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        # Same `ml_last_updated` as stored -- NOT stale by the first gate.
        order = _order(1, 999, earlier, earlier, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1, status="refunded", net_received_amount=0))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_called_once_with(500)
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.status == "refunded"

    def test_recheck_is_cleared_once_it_runs_so_it_fires_exactly_once(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
                payments_recheck_at=now - timedelta(minutes=1),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        order = _order(1, 999, earlier, earlier, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        sweep_service.run_sweep(seller_id=999, window_days=90)

        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert order_row.payments_recheck_at is None

        # A second pass over the SAME unchanged order must NOT refetch
        # again -- the recheck fired once and cleared itself; the order
        # is neither stale nor missing its seal any more.
        mock_get_payment_2 = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment_2)
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment_2.assert_not_called()

    def test_due_recheck_seen_by_the_search_window_whose_fetch_fails_reschedules_the_mark_forward(
        self, db, monkeypatch
    ) -> None:
        """A re-ask that does not seal must not lose its mark -- the same
        guarantee `TestDeferredRecheckRunsIndependentlyOfSearchWindow`
        pins for the DB-driven path, here exercised through
        `process_batch`'s own `recheck_due_ids` gate: the order IS in
        this pass's search
        results, and the fetch still fails. Clearing the mark here would
        be just as wrong as clearing it in the DB-driven path."""
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
                payments_recheck_at=now - timedelta(minutes=1),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        order = _order(1, 999, earlier, earlier, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(side_effect=RuntimeError("proxy timeout")))

        sweep_service.run_sweep(seller_id=999, window_days=90)

        order_row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        # `is not None` alone would pass just as happily with the mark
        # frozen on its original, already-due timestamp -- the very bug
        # that makes one order due on every future pass. Assert it MOVED
        # FORWARD, past now, which is the only shape that both keeps the
        # retry and releases the queue.
        assert order_row.payments_recheck_at is not None
        assert sweep_service.tz_aware(order_row.payments_recheck_at) > now
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.status == "approved"

    def test_in_window_order_the_budget_never_reached_keeps_its_due_mark(self, db, monkeypatch) -> None:
        """Being a payment candidate is not the same as having been asked.

        `_fetch_payments` stops when the budget runs out, so an order at
        the tail of the batch reaches the settlement line with no request
        ever made for it. Rescheduling it would report a failure that
        never happened -- exactly what the deferred pass already refuses
        to do, and this gate must agree."""
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        for oid, pid in ((1, 500), (2, 501)):
            db.add(
                MlOrdersOps(
                    order_id=oid,
                    seller_id=999,
                    ml_last_updated=earlier,
                    date_created=earlier,
                    payments_synced_at=earlier,
                    payments_recheck_at=now - timedelta(minutes=oid),
                )
            )
            db.add(MlPaymentOps(payment_id=pid, order_id=oid, status="approved"))
        db.commit()
        due_before = {row.order_id: row.payments_recheck_at for row in db.query(MlOrdersOps).all()}

        orders = [
            _order(1, 999, earlier, earlier, payment_ids=[500]),
            _order(2, 999, earlier, earlier, payment_ids=[501]),
        ]
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page(orders)))
        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )
        # Only ONE payment request fits in the whole pass.
        monkeypatch.setattr(sweep_service, "MAX_PAYMENT_FETCHES_PER_PASS", 1)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        db.expire_all()
        rows = {row.order_id: row.payments_recheck_at for row in db.query(MlOrdersOps).all()}
        untouched = [oid for oid in (1, 2) if rows[oid] == due_before[oid]]
        # BOTH halves. "At least one untouched" alone also holds when the
        # in-window gate settles NOTHING -- it passed with that gate
        # switched off entirely. Exactly one request fit, so exactly one
        # order was asked and must have been settled, and exactly the
        # other one was never reached and must be left as it was.
        assert len(untouched) == 1, f"se esperaba exactamente una intacta, quedaron {untouched}"
        (settled_oid,) = [oid for oid in (1, 2) if oid not in untouched]
        assert rows[settled_oid] != due_before[settled_oid], "la orden que si se pregunto no se liquido"

    def test_order_not_due_for_recheck_is_not_a_candidate(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=2)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=earlier,
                date_created=earlier,
                payments_synced_at=earlier,
                payments_recheck_at=now + timedelta(minutes=59),  # not due yet
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved", net_received_amount=Decimal("6800.50")))
        db.commit()

        order = _order(1, 999, earlier, earlier, payment_ids=[500])
        monkeypatch.setattr(ml_webhook_client, "search_orders", AsyncMock(return_value=_page([order])))
        mock_get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_payment.assert_not_called()


class TestDeferredRecheckSettlementPolicy:
    """What happens to `payments_recheck_at` after a re-ask -- cleared,
    left alone, pushed forward or given up on. All four outcomes live in
    `_settle_payments_recheck`, so they are pinned together here instead
    of scattered through the gate's own tests."""

    def _seed_due(self, db, oid, pid, mins_due, created_days_ago=1):
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=created_days_ago)
        db.add(
            MlOrdersOps(
                order_id=oid,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=mins_due),
                raw_order=_order(oid, 999, created, created, payment_ids=[pid]),
            )
        )
        db.add(MlPaymentOps(payment_id=pid, order_id=oid, status="approved"))
        return now

    def test_an_order_the_budget_never_reached_keeps_its_original_due_mark(self, db, monkeypatch) -> None:
        """Never attempted is NOT the same as failed.

        With only enough payment budget for the first order, the second
        one's id is never requested at all. Pushing its mark forward would
        punish it for the sweep's own budgeting and report a failure that
        never happened -- it must stay due so the next pass takes it
        first."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        # Order 1 carries FOUR payment ids, so fetching it alone drains the
        # whole budget. Order 2 is still SELECTED (the row limit is its own
        # separate bound) but its id is never requested -- which is exactly
        # the situation "not attempted" has to recognise.
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                raw_order=_order(1, 999, created, created, payment_ids=[500, 502, 503, 504]),
            )
        )
        self._seed_due(db, 2, 501, 5)
        db.commit()
        original_due = db.query(MlOrdersOps).filter_by(order_id=2).one().payments_recheck_at

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        result = sweep_service.SweepResult(ran=True)
        # Budget 4 -> deferred share 2 (both rows selected), and order 1's four ids
        # spend all four requests before order 2 is ever reached.
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[4], pass_started_at=now, seller_id=999)

        db.expire_all()
        row2 = db.query(MlOrdersOps).filter_by(order_id=2).one()
        assert row2.payments_recheck_at == original_due, "una orden que nunca se intento no puede reprogramarse"

    def test_a_backlog_of_rechecks_leaves_budget_for_the_windows_own_orders(self, db, monkeypatch) -> None:
        """The deferred pass runs BEFORE the page walk and shares one
        payment budget with it. If a backlog could claim the whole budget,
        the window's freshly-arrived orders would get no payment sync at
        all -- the ordinary path starved by the exceptional one."""
        now = datetime.now(timezone.utc)
        for oid in (1, 2, 3, 4):
            self._seed_due(db, oid, 500 + oid, 10 + oid)
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, pid - 500, status="refunded")),
        )

        budget = [4]
        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=budget, pass_started_at=now, seller_id=999)

        # Four orders were due and the budget was four, yet the deferred
        # pass must not have spent it all.
        assert budget[0] > 0, "el recheck diferido se comio todo el presupuesto de pagos"

    def test_one_order_with_many_payments_cannot_drain_the_shared_budget(self, db, monkeypatch) -> None:
        """Capping ROWS bounds nothing -- one order carries any number of
        payment ids, and each id costs one request.

        A single due order with ten payments, against a budget of ten, is
        the case a row cap cannot catch: one row is well under any row
        limit, and it still spends everything the window's own orders
        need. Only a cap on the SPEND survives this."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                raw_order=_order(1, 999, created, created, payment_ids=list(range(500, 510))),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        budget = [10]
        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=budget, pass_started_at=now, seller_id=999)

        assert budget[0] > 0, "una sola orden con muchos pagos vacio el presupuesto compartido"

    def test_an_order_is_given_up_on_only_after_the_full_allowance_of_attempts(self, db, monkeypatch) -> None:
        """The bound is ATTEMPTS, and it must grant every one of them.

        The previous version of this bound measured from `date_created`,
        which abandoned an order that was already old when its first
        recheck came due -- zero retries from a rule written to stop an
        endless one. So this pins BOTH edges: attempt number
        MAX_RECHECK_ATTEMPTS - 1 must still leave the order due, and only
        the last one clears it."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=400)  # ANCIENT: irrelevant to the bound
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=0,
                raw_order=_order(1, 999, created, created, payment_ids=[500]),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.commit()

        # Answers for an id this order is not waiting on: never seals.
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value={"id": 999999, "status": "x"}))

        for attempt in range(1, sweep_service.MAX_RECHECK_ATTEMPTS + 1):
            db.query(MlOrdersOps).filter_by(order_id=1).update({"payments_recheck_at": now - timedelta(minutes=10)})
            db.commit()
            result = sweep_service.SweepResult(ran=True)
            sweep_service._run_deferred_payments_rechecks(
                result, payment_budget=[10], pass_started_at=now, seller_id=999
            )
            db.expire_all()
            row = db.query(MlOrdersOps).filter_by(order_id=1).one()
            if attempt < sweep_service.MAX_RECHECK_ATTEMPTS:
                assert row.payments_recheck_at is not None, (
                    f"abandonada en el intento {attempt}, antes de agotar los "
                    f"{sweep_service.MAX_RECHECK_ATTEMPTS} permitidos"
                )
            else:
                assert row.payments_recheck_at is None, "no se abandono tras agotar los intentos"

    def test_an_order_with_no_payment_ids_still_leaves_the_queue(self, db, monkeypatch) -> None:
        """An order with nothing to ask is not an order that was skipped.

        `attempted` is computed as `any(pid in attempted_ids for pid in
        ids)`, and `any()` over an EMPTY sequence is False -- so an order
        whose payload carries no extractable payment ids (empty list,
        missing key, malformed) looks exactly like one the budget never
        reached. Its mark is then never cleared, never rescheduled and
        never counted, so it escapes MAX_RECHECK_ATTEMPTS entirely and
        stays due forever. Worse, it costs no budget, so it is re-selected
        oldest-due-first on every pass: enough of these fill the LIMIT and
        no real due order is ever picked again -- the head-of-line
        starvation this whole mechanism exists to prevent."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=0,
                raw_order=_order(1, 999, created, created, payment_ids=[]),
            )
        )
        db.commit()
        original_due = db.query(MlOrdersOps).filter_by(order_id=1).one().payments_recheck_at

        monkeypatch.setattr(
            ml_webhook_client, "get_payment", AsyncMock(side_effect=AssertionError("no hay nada que pedir"))
        )

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        # An EMPTY payments list is ML answering "none": every one of the
        # order's (zero) ids resolved, so it seals and the mark is
        # cleared. What matters is that it LEAVES the queue either way.
        moved = row.payments_recheck_at is None or sweep_service.tz_aware(
            row.payments_recheck_at
        ) > sweep_service.tz_aware(original_due)
        assert moved, "la orden sin ids de pago quedo clavada en la cabeza de la cola para siempre"

    def test_an_order_whose_payload_has_no_payments_key_counts_its_attempt(self, db, monkeypatch) -> None:
        """The malformed half of the same finding.

        A payload with NO `payments` key does not seal on the deferred
        path (`missing_key_is_empty` stays False there: an absent key is
        an unknown, not an answer). It also yields no ids to fetch. So it
        must be counted as an attempt and rescheduled -- otherwise it
        never reaches MAX_RECHECK_ATTEMPTS and stays due forever, which
        is precisely the 'permanently malformed payload' that bound was
        written for."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        raw = _order(1, 999, created, created, payment_ids=[])
        raw.pop("payments", None)
        assert "payments" not in raw
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=0,
                raw_order=raw,
            )
        )
        db.commit()
        original_due = db.query(MlOrdersOps).filter_by(order_id=1).one().payments_recheck_at

        monkeypatch.setattr(
            ml_webhook_client, "get_payment", AsyncMock(side_effect=AssertionError("no hay nada que pedir"))
        )

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row.payments_recheck_attempts > 0, "no se conto el intento: escapa al tope de reintentos"
        assert sweep_service.tz_aware(row.payments_recheck_at) > sweep_service.tz_aware(original_due)

    def test_an_order_too_big_to_fetch_in_full_still_makes_progress(self, db, monkeypatch) -> None:
        """A partial fetch counts as an attempt, ON PURPOSE.

        The fair-looking rule -- only a COMPLETE fetch spends an attempt
        -- is a trap. An order with more payment ids than the deferred
        share can never be fetched in full, and it is first in the
        oldest-due-first queue: every pass spends the whole share on its
        same leading ids, calls it "not attempted", leaves its mark
        untouched, and repeats. It never reaches MAX_RECHECK_ATTEMPTS,
        never leaves the head, and starves every order behind it forever.

        So progress wins over fairness: this order burns attempts and is
        eventually retired, which is the honest reading of an order that
        cannot be answered this way."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=0,
                raw_order=_order(1, 999, created, created, payment_ids=[500, 501, 502, 503]),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.commit()
        original_due = db.query(MlOrdersOps).filter_by(order_id=1).one().payments_recheck_at

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        # Budget 2 -> deferred share 1: only the first of the four ids is
        # ever requested, so this order can NEVER complete.
        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[2], pass_started_at=now, seller_id=999)

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row.payments_recheck_attempts > 0, "no conto el intento: la orden se queda en la cabeza para siempre"
        assert sweep_service.tz_aware(row.payments_recheck_at) > sweep_service.tz_aware(original_due), (
            "no se reprogramo: bloquea la cola de todas las demas"
        )

    def test_the_deferred_slice_bounds_the_http_phase_not_just_the_bookkeeping(self, db, monkeypatch) -> None:
        """The slice has to bound the HTTP calls, which is where the time
        actually goes.

        NO WALL-CLOCK RACE: the slice is INJECTED, already expired, while
        `pass_started_at` stays fresh so the pass's own deadline is far
        away. An earlier version raced ~300ms of slice against ~500ms of
        real `time.sleep`, which a loaded CI box could tip either way --
        and worse, the two bounds are coupled by construction (the slice
        IS half of what the pass has left), so shrinking one shrinks the
        other and neither can be tested in isolation by timing alone.
        Injecting is the only way to ask about this bound and no other.

        An even earlier version slowed `sync_payments_for_order` -- the
        cheap per-order DB loop -- and so stayed green with the cutoff
        missing from the fetch entirely."""
        now = datetime.now(timezone.utc)
        for oid in range(1, 6):
            self._seed_due(db, oid, 500 + oid, 30 - oid)
        db.commit()

        calls = {"n": 0}

        async def _counted_payment(pid):
            calls["n"] += 1
            return _payment_payload(pid, pid - 500, status="refunded")

        monkeypatch.setattr(ml_webhook_client, "get_payment", _counted_payment)
        # Slice already spent; pass deadline untouched and far away.
        monkeypatch.setattr(sweep_service, "_deferred_pass_deadline", lambda started: datetime.now(timezone.utc))

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[50], pass_started_at=now, seller_id=999)

        # The COUNT OF HTTP CALLS is the only thing that isolates this.
        # Asserting that some orders are still due proves nothing: the
        # settlement loop leaves rows due for other reasons entirely.
        assert calls["n"] < 5, f"el fetch hizo las {calls['n']} llamadas: el corte no alcanzo la fase HTTP"

    def test_the_deferred_slice_is_half_of_what_the_pass_has_left(self) -> None:
        """The slice itself, as arithmetic -- no clock racing, no I/O."""
        now = datetime.now(timezone.utc)
        started = now - (sweep_service.PASS_TIME_BUDGET - timedelta(seconds=60))
        deadline = sweep_service._deferred_pass_deadline(started)
        remaining = (started + sweep_service.PASS_TIME_BUDGET) - now
        slice_len = deadline - now
        # ~30s of the ~60s left, with a wide tolerance: the assertion is
        # "about half", not a stopwatch reading.
        assert timedelta(seconds=20) < slice_len < timedelta(seconds=40), (
            f"la porcion no es la mitad de lo que queda (quedaban {remaining}, dio {slice_len})"
        )

    def test_the_deferred_slice_is_never_negative_on_an_exhausted_pass(self) -> None:
        """A pass already past its budget must not hand back a deadline in
        the past that reads as 'plenty of time' anywhere downstream."""
        started = datetime.now(timezone.utc) - (sweep_service.PASS_TIME_BUDGET + timedelta(minutes=5))
        deadline = sweep_service._deferred_pass_deadline(started)
        assert deadline <= datetime.now(timezone.utc) + timedelta(seconds=1)

    def test_work_bought_before_the_slice_expired_is_still_persisted(self, db, monkeypatch) -> None:
        """When the slice has run out, what WAS fetched must still land.

        The slice bounds the HTTP phase. If the cheap settlement loop
        checked it too, then -- since time only moves forward -- the loop
        would break before its first order every single time the fetch
        stopped on the slice: every payment already paid for in requests
        discarded, no attempt counted, no mark moved, and the next pass
        repeating the same zero result. A livelock.

        NO WALL-CLOCK: the slice is injected as already expired, and the
        fetch is made to ignore it -- standing in for "these payments were
        bought before the slice ran out". That leaves exactly one thing
        deciding whether anything is persisted: whether the settlement
        loop consults the slice. Nothing else in the system can produce
        or hide that outcome, so the test asks about that and only that."""
        now = datetime.now(timezone.utc)
        for oid in range(1, 4):
            self._seed_due(db, oid, 500 + oid, 30 - oid)
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, pid - 500, status="refunded")),
        )
        monkeypatch.setattr(sweep_service, "_deferred_pass_deadline", lambda started: datetime.now(timezone.utc))

        real_fetch = sweep_service._fetch_payments

        def _fetch_already_bought(*args, **kwargs):
            kwargs["deadline"] = None
            return real_fetch(*args, **kwargs)

        monkeypatch.setattr(sweep_service, "_fetch_payments", _fetch_already_bought)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[50], pass_started_at=now, seller_id=999)

        db.expire_all()
        refunded = db.query(MlPaymentOps).filter_by(status="refunded").count()
        assert refunded == 3, f"se tiro lo ya comprado en requests (livelock): {refunded} de 3 persistidos"

    def test_giving_up_also_resets_the_counter_so_a_later_re_ask_is_not_born_exhausted(self, db, monkeypatch) -> None:
        """Retiring one question must not disqualify the next.

        If the counter were left at its exhausted value, the NEXT recheck
        scheduled for this order -- a new question, after some later
        payment sync -- would start already out of attempts and be
        retired on its very first pass, never asking ML anything."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=sweep_service.MAX_RECHECK_ATTEMPTS - 1,
                raw_order=_order(1, 999, created, created, payment_ids=[500]),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.commit()

        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value={"id": 999999, "status": "x"}))

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row.payments_recheck_at is None, "no se abandono tras agotar los intentos"
        assert row.payments_recheck_attempts == 0, "quedo el contador agotado: el proximo re-ask nace muerto"

    def test_the_rescue_reschedule_opens_its_own_session(self, db, monkeypatch) -> None:
        """The rescue write must not ride the session that just failed.

        Rolling back clears the failed transaction, but the CONNECTION can
        be what broke (dropped socket, statement timeout, poisoned pool
        entry). A rescue on that same session dies too, the mark never
        moves, and the poisoned row is back at the head of the queue on
        every future pass.

        NOTE ON WHAT THIS PINS: the suite's `get_background_db` hands back
        the one test session, so a behavioural test cannot tell the two
        apart -- breaking 'the' session breaks the one the assertions run
        on. What is checked is structural: the failure path OPENS AN
        ADDITIONAL session instead of reusing the working one. That is
        the property the fix is, and the most this harness can honestly
        show."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=0,
                raw_order=_order(1, 999, created, created, payment_ids=[500]),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.commit()
        original_due = db.query(MlOrdersOps).filter_by(order_id=1).one().payments_recheck_at

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        opens = {"n": 0}
        real_ctx = sweep_service.get_background_db

        @contextmanager
        def _counting_ctx(*a, **k):
            opens["n"] += 1
            with real_ctx(*a, **k) as session:
                yield session

        monkeypatch.setattr(sweep_service, "get_background_db", _counting_ctx)

        def _boom(db_arg, order_id, raw_order, payments_payload, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(sweep_service, "sync_payments_for_order", _boom)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        # One for the due-row SELECT, one for the working loop, and a
        # THIRD opened by the rescue. Without the fix the rescue reuses
        # the loop's session and only two are ever opened.
        assert opens["n"] >= 3, f"el rescate no abrio sesion propia (aperturas={opens['n']})"

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert sweep_service.tz_aware(row.payments_recheck_at) > sweep_service.tz_aware(original_due)

    def test_a_payload_that_breaks_the_attempted_check_only_kills_its_own_order(self, db, monkeypatch) -> None:
        """`attempted` is computed from the stored payload, so a malformed
        one can make that computation itself raise.

        Computed OUTSIDE the per-order try, such a payload takes down the
        whole remaining loop instead of just its own order -- every order
        behind it loses its already-fetched payments, exactly the blast
        radius the per-order isolation exists to contain."""
        now = datetime.now(timezone.utc)
        self._seed_due(db, 1, 500, 10)
        self._seed_due(db, 2, 501, 5)
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, status="refunded")),
        )

        real_extract = sweep_service._extract_payment_ids
        seen = {"n": 0}

        def _explode_on_the_first_order(raw_order):
            # The FETCH phase calls this too; only blow up once the
            # settlement loop reaches order 1.
            ids = real_extract(raw_order)
            if ids == [500]:
                seen["n"] += 1
                if seen["n"] > 1:
                    raise ValueError("payload malformado")
            return ids

        monkeypatch.setattr(sweep_service, "_extract_payment_ids", _explode_on_the_first_order)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        payment2 = db.query(MlPaymentOps).filter_by(payment_id=501).one()
        assert payment2.status == "refunded", "la orden 2 murio por un payload malformado de la orden 1"

    def test_the_last_request_of_the_budget_is_left_to_the_window(self, db, monkeypatch) -> None:
        """`max(1, budget // 2)` defeats the halving at the bottom.

        With one request left in the shared budget, that formula hands the
        deferred pass the WHOLE remainder -- the exceptional path taking
        the ordinary one's last request, which is the opposite of what
        sharing was for. At that point the recheck can simply wait a pass."""
        now = datetime.now(timezone.utc)
        self._seed_due(db, 1, 500, 10)
        db.commit()

        calls = {"n": 0}

        async def _counted(pid):
            calls["n"] += 1
            return _payment_payload(pid, 1, status="refunded")

        monkeypatch.setattr(ml_webhook_client, "get_payment", _counted)

        budget = [1]
        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=budget, pass_started_at=now, seller_id=999)

        assert calls["n"] == 0, "el diferido se quedo con el ultimo request del presupuesto"
        assert budget[0] == 1, "gasto presupuesto que le tocaba a la ventana"

    def test_a_seal_resets_the_attempt_counter(self, db, monkeypatch) -> None:
        """A future re-ask is a new question and gets its full allowance,
        instead of inheriting attempts an already-answered one spent."""
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=1)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=created,
                date_created=created,
                payments_synced_at=created,
                payments_recheck_at=now - timedelta(minutes=10),
                payments_recheck_attempts=sweep_service.MAX_RECHECK_ATTEMPTS - 1,
                raw_order=_order(1, 999, created, created, payment_ids=[500]),
            )
        )
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="approved"))
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row.payments_recheck_at is None
        assert row.payments_recheck_attempts == 0

    def test_an_order_that_raises_is_rescheduled_so_it_stops_blocking_the_queue(self, db, monkeypatch) -> None:
        """Head-of-line: FIFO order means a row that reliably explodes
        would be selected FIRST on every pass forever, crashing the same
        way and blocking everything behind it. The failed order's mark has
        to move too."""
        now = self._seed_due(db, 1, 500, 10)
        db.commit()
        original_due = db.query(MlOrdersOps).filter_by(order_id=1).one().payments_recheck_at

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        def _boom(db_arg, order_id, raw_order, payments_payload, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(sweep_service, "sync_payments_for_order", _boom)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        db.expire_all()
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row.payments_recheck_at is not None
        assert sweep_service.tz_aware(row.payments_recheck_at) > sweep_service.tz_aware(original_due)

    def test_payments_synced_is_not_credited_when_the_commit_fails(self, db, monkeypatch) -> None:
        """`payments_synced` is reported as rows actually written, so work
        a failed commit rolled back must not be counted."""
        now = self._seed_due(db, 1, 500, 10)
        db.commit()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, status="refunded")),
        )

        # The failure has to land ON the commit. Poisoning the session
        # earlier (a duplicate row, say) blows up in an autoflush BEFORE
        # the counter line is ever reached, so it proves nothing about the
        # ordering -- which is what an earlier version of this test did.
        real_ctx = sweep_service.get_background_db

        @contextmanager
        def _commit_fails_once(*args, **kwargs):
            with real_ctx(*args, **kwargs) as session:
                real_commit = session.commit
                state = {"first": True}

                def _commit():
                    if state["first"]:
                        state["first"] = False
                        raise RuntimeError("commit failed")
                    return real_commit()

                session.commit = _commit
                try:
                    yield session
                finally:
                    session.commit = real_commit

        monkeypatch.setattr(sweep_service, "get_background_db", _commit_fails_once)

        result = sweep_service.SweepResult(ran=True)
        sweep_service._run_deferred_payments_rechecks(result, payment_budget=[10], pass_started_at=now, seller_id=999)

        assert result.payments_synced == 0
