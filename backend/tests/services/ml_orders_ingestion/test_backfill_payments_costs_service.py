"""Tests for the historical backfill of payments and shipment costs
(ml-backfill-pagos-y-costos).

Contract-first (obs #1843/#1852/#1965 lesson): assert the PROMISES --
flag-gated, candidates come from the BASE tables (not a sweep window),
`--dry-run` makes zero HTTP calls and zero writes, sealing only on a
FULLY resolved order (never on a partial result), its own run lock never
collides with the sweep's or the orders backfill's, and fetch/mapping/
sealing are the exact same functions the sweep uses -- not a second copy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOpsSyncCursor, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_orders_ingestion import backfill_payments_costs_service as service
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import ml_webhook_client


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    # `sync_payments_for_order`/`_sync_shipment_costs` are reused straight
    # from `sweep_service`, which opens ITS OWN `get_background_db()` --
    # both module bindings must land in the same sqlite test session.
    monkeypatch.setattr(service, "get_background_db", _fake_ctx(db))
    monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


@pytest.fixture(autouse=True)
def _no_real_get_order(monkeypatch):
    """A candidate whose stored `raw_order` lacks the `payments` key is
    now refetched via `get_order` (post-review fix #1/#2). Defaults to a
    failed refetch (`None`) so a test that does not care about this path
    gets "left unresolved", never a real network call; a test exercising
    the refetch brings its own mock."""
    monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=None))


def _raw_order(order_id: int, payment_ids=None) -> dict:
    """`payment_ids=None` (default) means the `payments` key is ABSENT --
    an ambiguous, "we don't know" payload, e.g. an older ingestion write
    that never persisted it. `payment_ids=[]` sets `payments: []`, ML's
    own way of saying an order genuinely has none. These are DIFFERENT
    facts on purpose (post-review blocking fix) -- do not collapse them."""
    order = {"id": order_id, "status": "paid", "order_items": []}
    if payment_ids is not None:
        order["payments"] = [{"id": pid} for pid in payment_ids]
    return order


def _payment_payload(payment_id: int, order_id: int, **overrides) -> dict:
    base = {
        "payment_id": payment_id,
        "order_id": order_id,
        "status": "approved",
        "currency_id": "ARS",
        "net_received_amount": 100.0,
        "total_paid_amount": 110.0,
        "transaction_amount": 110.0,
        "shipping_amount": 0,
        "coupon_amount": 0,
        "taxes_amount": 0,
        "transaction_amount_refunded": 0,
        "charges_details": [],
    }
    base.update(overrides)
    return base


def _shipment_costs(sender_cost, receiver_cost) -> dict:
    return {
        "gross_amount": float(sender_cost) + float(receiver_cost),
        "receiver": {"cost": receiver_cost},
        "senders": [{"cost": sender_cost, "discounts": []}],
    }


class TestFlagGate:
    def test_disabled_is_a_complete_no_op(self, db, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=datetime.now(timezone.utc)))
        db.commit()
        get_payment = AsyncMock()
        monkeypatch.setattr(ml_webhook_client, "get_payment", get_payment)

        result = service.run_backfill(limit=10)

        assert result.ran is False
        get_payment.assert_not_called()

    def test_disabled_is_not_reported_as_an_error(self, monkeypatch) -> None:
        """Finding 2: the flag-off no-op is a genuine success, not a
        failure -- `error` must stay `None`, exactly like
        `backfill_service.run_backfill`'s own flag-off branch, or the
        CLI's `sys.exit(1)` (triggered only by `result.error`) fires on
        an expected, benign outcome."""
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)

        result = service.run_backfill(limit=10)

        assert result.ran is False
        assert result.error is None

    def test_already_running_is_still_reported_as_an_error(self, db, monkeypatch) -> None:
        """The contrasting case: a REAL failure to run (another pass in
        flight) must still set `error`, or the CLI would never exit
        non-zero for it either."""
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        now = datetime.now(timezone.utc)
        db.add(MlOpsSyncCursor(name=service.CURSOR_NAME, state="running", detail=now.isoformat()))
        db.commit()

        result = service.run_backfill(limit=10)

        assert result.ran is False
        assert result.error is not None


class TestDryRun:
    def test_dry_run_counts_but_makes_zero_http_calls_and_zero_writes(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()

        get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        get_costs = AsyncMock(return_value=_shipment_costs(400, 0))
        monkeypatch.setattr(ml_webhook_client, "get_payment", get_payment)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", get_costs)

        result = service.run_backfill(limit=10, dry_run=True)

        assert result.ran is True
        assert result.dry_run is True
        assert result.order_candidates == 1
        assert result.shipment_candidates == 1
        get_payment.assert_not_called()
        get_costs.assert_not_called()
        assert db.query(MlPaymentOps).count() == 0
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is None
        assert db.query(MlShipmentOps).filter_by(shipment_id=700).one().costs_synced_at is None
        # A dry run must never take the lock either.
        assert db.query(MlOpsSyncCursor).filter_by(name=service.CURSOR_NAME).first() is None

    def test_dry_run_never_materializes_full_raw_order_rows(self, db, monkeypatch) -> None:
        """Finding 4: a dry run is what an operator runs FIRST against
        production, and its own docstring promises two COUNT queries and
        nothing else. Prove it structurally: the row-fetching functions
        that read `raw_order` (potentially several KB of JSONB per row)
        must never even be called during a dry run."""

        def _must_not_be_called(limit):
            raise AssertionError("dry-run must not fetch full candidate rows")

        monkeypatch.setattr(service, "_orders_needing_payments", _must_not_be_called)
        monkeypatch.setattr(service, "_shipments_needing_costs", _must_not_be_called)

        result = service.run_backfill(limit=10, dry_run=True)

        assert result.ran is True


class TestNewestFirst:
    def test_orders_are_ordered_newest_created_first(self, db, monkeypatch) -> None:
        """An operator watching the listing cares about recent sales --
        oldest-first would spend the whole backlog on old history before
        ever reaching what's on screen (post-review fix)."""
        base = datetime.now(timezone.utc) - timedelta(days=100)
        for order_id, age_days in ((1, 3), (2, 90), (3, 1)):
            db.add(
                MlOrdersOps(
                    order_id=order_id,
                    seller_id=999,
                    ml_last_updated=base,
                    date_created=base + timedelta(days=100 - age_days),
                    raw_order=_raw_order(order_id, payment_ids=[]),
                )
            )
        db.commit()

        candidates = service._orders_needing_payments(limit=10)

        assert [order_id for order_id, _ in candidates] == [3, 1, 2]

    def test_shipments_are_ordered_newest_id_first(self, db, monkeypatch) -> None:
        for shipment_id in (100, 300, 200):
            db.add(MlShipmentOps(shipment_id=shipment_id, order_id=shipment_id))
        db.commit()

        candidates = service._shipments_needing_costs(limit=10)

        assert candidates == [300, 200, 100]


class TestBudgetExhausted:
    def test_payments_budget_exhausted_is_surfaced_when_the_limit_outruns_it(self, db, monkeypatch) -> None:
        """Finding 3: `--limit` counts CANDIDATES, and one order can carry
        several payment ids -- the payment fetch budget can run out mid-
        run while candidates remain unresolved, silently, unless this is
        surfaced."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500, 501]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))
        monkeypatch.setattr(service, "MAX_PAYMENT_FETCHES_PER_PASS", 1)

        result = service.run_backfill(limit=10)

        assert result.payments_budget_exhausted is True
        assert result.orders_sealed == 0  # order 1 is left unresolved, not silently claimed done

    def test_payments_budget_not_exhausted_when_every_candidate_resolves(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        result = service.run_backfill(limit=10)

        assert result.payments_budget_exhausted is False
        assert result.orders_sealed == 1

    def test_costs_budget_exhausted_is_surfaced_when_the_limit_outruns_it(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.add(MlShipmentOps(shipment_id=701, order_id=2))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=_shipment_costs(400, 0)))
        monkeypatch.setattr(service, "MAX_COST_FETCHES_PER_PASS", 1)

        result = service.run_backfill(limit=10)

        assert result.costs_budget_exhausted is True
        assert result.shipment_costs_synced == 1

    def test_payments_budget_exhausted_is_not_reported_when_the_budget_exactly_matches_full_success(
        self, db, monkeypatch
    ) -> None:
        """Finding 4: `budget[0] <= 0` after every needed payment resolved
        successfully is a COMPLETE pass, not a truncated one -- the old
        check reported this exact edge as exhausted, which is the metric
        that lies by construction the rest of this module avoids."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))
        # Exactly one payment id needed, exactly one unit of budget.
        monkeypatch.setattr(service, "MAX_PAYMENT_FETCHES_PER_PASS", 1)

        result = service.run_backfill(limit=10)

        assert result.payments_budget_exhausted is False
        assert result.orders_sealed == 1

    def test_costs_budget_exhausted_is_not_reported_when_the_budget_exactly_matches_full_success(
        self, db, monkeypatch
    ) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=_shipment_costs(400, 0)))
        monkeypatch.setattr(service, "MAX_COST_FETCHES_PER_PASS", 1)

        result = service.run_backfill(limit=10)

        assert result.costs_budget_exhausted is False
        assert result.shipment_costs_synced == 1


class TestCompleteFlagReflectsTruncation:
    """Finding 5: a run truncated by either budget must NOT be stamped as
    a completed pass (mirrors the sweep's own
    `complete=not result.budget_exhausted`), or a staleness alert on "no
    success in N minutes" never fires while this backfill keeps
    truncating."""

    def test_a_truncated_payments_pass_does_not_stamp_last_success_at(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500, 501]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))
        monkeypatch.setattr(service, "MAX_PAYMENT_FETCHES_PER_PASS", 1)

        service.run_backfill(limit=10)

        cursor = db.query(MlOpsSyncCursor).filter_by(name=service.CURSOR_NAME).one()
        assert cursor.state == "idle"
        assert cursor.last_success_at is None

    def test_a_complete_pass_does_stamp_last_success_at(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        service.run_backfill(limit=10)

        cursor = db.query(MlOpsSyncCursor).filter_by(name=service.CURSOR_NAME).one()
        assert cursor.last_success_at is not None


class TestBaseTableCandidates:
    def test_an_order_never_touched_by_any_sweep_window_is_still_found_and_sealed(self, db, monkeypatch) -> None:
        """The exact gap this script exists to close: an order whose
        `ml_last_updated` is ancient (long outside any sweep window) but
        whose `payments_synced_at` is still NULL."""
        ancient = datetime.now(timezone.utc) - timedelta(days=400)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=ancient,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()

        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        result = service.run_backfill(limit=10)

        assert result.order_candidates == 1
        assert result.payments_synced == 1
        assert result.orders_sealed == 1
        row = db.query(MlPaymentOps).filter_by(payment_id=500).one()
        assert row.net_received_amount == Decimal("100")
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is not None

    def test_an_already_sealed_order_is_never_a_candidate(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                payments_synced_at=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()
        get_payment = AsyncMock(return_value=_payment_payload(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_payment", get_payment)

        result = service.run_backfill(limit=10)

        assert result.order_candidates == 0
        get_payment.assert_not_called()

    def test_a_terminal_shipment_never_touched_by_any_sweep_window_is_still_found_and_synced(
        self, db, monkeypatch
    ) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1, status="delivered"))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=_shipment_costs(400, 0)))

        result = service.run_backfill(limit=10)

        assert result.shipment_candidates == 1
        assert result.shipment_costs_synced == 1
        row = db.query(MlShipmentOps).filter_by(shipment_id=700).one()
        assert row.sender_cost == Decimal("400")
        assert row.costs_synced_at is not None

    def test_a_shipment_already_synced_is_never_a_candidate(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlShipmentOps(shipment_id=700, order_id=1, costs_synced_at=now))
        db.commit()
        get_costs = AsyncMock(return_value=_shipment_costs(400, 0))
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", get_costs)

        result = service.run_backfill(limit=10)

        assert result.shipment_candidates == 0
        get_costs.assert_not_called()


class TestAbsentPaymentsKeyIsNeverSealed:
    """Finding 1, BLOCKING: sealing an order whose `raw_order` never even
    HAS a `payments` key is irrecoverable, because `payments_synced_at IS
    NULL` is the only retry gate -- a false seal here means that sale's
    `--` becomes permanent, written by the very script meant to remove
    it."""

    def test_a_stored_raw_order_with_no_payments_key_at_all_is_never_sealed_on_the_stale_payload(
        self, db, monkeypatch
    ) -> None:
        """A refetch is always attempted for this case (see
        `TestAmbiguousRowsAreResolvedByRefetching`); this test covers the
        sub-case where the refetch itself FAILS -- the stale, ambiguous
        stored payload alone must never be enough to seal."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=None),  # key ABSENT, not []
            )
        )
        db.commit()
        assert "payments" not in db.query(MlOrdersOps).filter_by(order_id=1).one().raw_order
        get_payment = AsyncMock()
        monkeypatch.setattr(ml_webhook_client, "get_payment", get_payment)
        # `_no_real_get_order` fixture already defaults to a failed
        # refetch (`None`) -- explicit here for clarity.
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=None))

        result = service.run_backfill(limit=10)

        get_payment.assert_not_called()
        assert result.orders_sealed == 0
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is None

    def test_a_stored_raw_order_with_an_explicit_empty_payments_list_is_sealed(self, db, monkeypatch) -> None:
        """The contrasting case: `payments: []` IS a real fact from ML
        and must still seal -- this fix must not turn EVERY order into an
        unsealable one."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[]),  # key present, empty
            )
        )
        db.commit()

        result = service.run_backfill(limit=10)

        assert result.orders_sealed == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is not None


class TestAmbiguousRowsAreResolvedByRefetching:
    """Findings 1/2, round 2 (BLOCKING): refusing to seal an ambiguous
    stored row is not enough on its own -- this backfill NEVER re-asks
    ML for anything else, so without a refetch the exact same row is
    reselected forever and blocks every candidate behind it. This is the
    regression the first round of the fix reintroduced."""

    def test_a_successful_refetch_confirming_no_payments_resolves_and_seals(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=None),  # stale, ambiguous
            )
        )
        db.commit()
        # ML's FRESH answer confirms the order genuinely has none.
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_raw_order(1, payment_ids=[])))
        get_payment = AsyncMock()
        monkeypatch.setattr(ml_webhook_client, "get_payment", get_payment)

        result = service.run_backfill(limit=10)

        get_payment.assert_not_called()
        assert result.orders_sealed == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is not None

    def test_a_successful_refetch_with_real_payments_fetches_and_seals(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=None),  # stale, ambiguous
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_raw_order(1, payment_ids=[500])))
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        result = service.run_backfill(limit=10)

        assert result.orders_sealed == 1
        assert db.query(MlPaymentOps).filter_by(payment_id=500).count() == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is not None

    def test_a_second_run_advances_past_an_ambiguous_row_once_it_resolves(self, db, monkeypatch) -> None:
        """The exact regression: with a working refetch, a second run
        must NOT reselect the same row -- it must have made progress."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                date_created=now,
                raw_order=_raw_order(1, payment_ids=None),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_raw_order(1, payment_ids=[])))

        first = service.run_backfill(limit=10)
        assert first.order_candidates == 1
        assert first.orders_sealed == 1

        second = service.run_backfill(limit=10)

        assert second.order_candidates == 0  # NOT the same row again

    def test_a_second_run_still_advances_when_other_candidates_exist_behind_a_stuck_ambiguous_row(
        self, db, monkeypatch
    ) -> None:
        """Regression guard: even while order 1's refetch keeps failing
        (permanently ambiguous), an order behind it must still be
        resolved -- the stuck row must not be the ONLY thing blocking an
        otherwise-resolvable candidate in the same run."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                date_created=now,
                raw_order=_raw_order(1, payment_ids=None),
            )
        )
        db.add(
            MlOrdersOps(
                order_id=2,
                seller_id=999,
                ml_last_updated=now,
                date_created=now - timedelta(days=1),
                raw_order=_raw_order(2, payment_ids=[]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=None))  # keeps failing

        result = service.run_backfill(limit=10)

        assert result.orders_sealed == 1  # order 2, not order 1
        assert db.query(MlOrdersOps).filter_by(order_id=2).one().payments_synced_at is not None
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is None


class TestPartialFailureNeverSealsMoney:
    def test_a_payment_fetch_failure_is_fail_open_and_leaves_the_order_unsealed(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500, 501]),
            )
        )
        db.commit()

        async def flaky(payment_id):
            if payment_id == 500:
                return _payment_payload(500, 1)
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_payment", flaky)

        result = service.run_backfill(limit=10)

        assert result.error is None
        assert db.query(MlPaymentOps).filter_by(payment_id=500).count() == 1
        assert db.query(MlPaymentOps).filter_by(payment_id=501).count() == 0
        row = db.query(MlOrdersOps).filter_by(order_id=1).one()
        assert row.payments_synced_at is None  # NOT sealed: must retry next run
        assert result.orders_sealed == 0

    def test_a_cost_fetch_failure_is_fail_open_and_leaves_the_shipment_unsynced(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()

        async def raises(shipment_id):
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", raises)

        result = service.run_backfill(limit=10)

        assert result.error is None
        row = db.query(MlShipmentOps).filter_by(shipment_id=700).one()
        assert row.costs_synced_at is None
        assert result.shipment_costs_synced == 0


class TestShipmentCostSyncGivesUpAfterRepeatedFailure:
    """Finding 3: a shipment ML never fully settles would otherwise sit
    at the head of `shipment_id DESC` forever, spending one real HTTP
    fetch per run while blocking every candidate behind it."""

    def _always_fails(self, shipment_id):
        raise ValueError("boom")

    def test_a_shipment_stuck_below_the_attempt_limit_is_still_a_candidate(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._always_fails)

        for _ in range(service.MAX_COST_SYNC_ATTEMPTS - 1):
            result = service.run_backfill(limit=10)
            assert result.shipment_candidates == 1

    def test_a_shipment_stuck_at_the_attempt_limit_stops_being_a_candidate(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._always_fails)

        last_result = None
        for _ in range(service.MAX_COST_SYNC_ATTEMPTS):
            last_result = service.run_backfill(limit=10)

        assert last_result.shipments_gave_up == 1

        # It has now given up -- the NEXT run must not spend an HTTP call
        # on it at all.
        get_costs = AsyncMock(side_effect=self._always_fails)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", get_costs)
        result = service.run_backfill(limit=10)

        assert result.shipment_candidates == 0
        get_costs.assert_not_called()

    def test_a_shipment_that_eventually_succeeds_never_gives_up(self, db, monkeypatch) -> None:
        """The escape hatch must not fire on a shipment that is simply
        slow to settle -- only on one that never resolves within the
        attempt budget."""
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._always_fails)

        for _ in range(service.MAX_COST_SYNC_ATTEMPTS - 1):
            service.run_backfill(limit=10)

        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=_shipment_costs(400, 0)))
        result = service.run_backfill(limit=10)

        assert result.shipment_costs_synced == 1
        assert result.shipments_gave_up == 0
        assert db.query(MlShipmentOps).filter_by(shipment_id=700).one().costs_synced_at is not None


class TestLimit:
    def _add_three_orders(self, db) -> None:
        now = datetime.now(timezone.utc)
        # Distinct `date_created` per row -- ordering is now newest-first
        # (post-review fix), and a tie on the sort key would make which
        # 2-of-3 land in a `limit=2` slice implementation-defined.
        for order_id, age_days in ((1, 3), (2, 2), (3, 1)):
            db.add(
                MlOrdersOps(
                    order_id=order_id,
                    seller_id=999,
                    ml_last_updated=now,
                    date_created=now - timedelta(days=age_days),
                    raw_order=_raw_order(order_id, payment_ids=[]),
                )
            )
        db.commit()

    def test_limit_bounds_the_number_of_candidates_pulled_per_run(self, db, monkeypatch) -> None:
        self._add_three_orders(db)

        result = service.run_backfill(limit=2)

        assert result.order_candidates == 2

    def test_a_second_run_resumes_where_the_first_left_off(self, db, monkeypatch) -> None:
        """Reanudable by construction: a sealed order drops out of the
        `payments_synced_at IS NULL` query, so a second bounded run picks
        up whatever the first one did not reach -- no separate cursor
        bookkeeping needed for this part."""
        self._add_three_orders(db)

        first = service.run_backfill(limit=2)
        assert first.order_candidates == 2
        assert first.orders_sealed == 2

        second = service.run_backfill(limit=2)
        assert second.order_candidates == 1
        assert second.orders_sealed == 1


class TestOwnLockDoesNotCollide:
    def test_own_cursor_name_is_distinct_from_sweep_and_orders_backfill(self) -> None:
        assert service.CURSOR_NAME == "backfill_payments_costs"
        assert service.CURSOR_NAME != sweep_service.CURSOR_NAME
        assert service.CURSOR_NAME != "backfill"

    def test_a_concurrent_run_is_skipped_not_raced(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlOpsSyncCursor(name=service.CURSOR_NAME, state="running", detail=now.isoformat()))
        db.commit()
        get_payment = AsyncMock()
        monkeypatch.setattr(ml_webhook_client, "get_payment", get_payment)

        result = service.run_backfill(limit=10)

        assert result.ran is False
        get_payment.assert_not_called()

    def test_the_sweeps_own_running_lock_does_not_block_this_backfill(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlOpsSyncCursor(name=sweep_service.CURSOR_NAME, state="running", detail=now.isoformat()))
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        result = service.run_backfill(limit=10)

        assert result.ran is True
        assert result.orders_sealed == 1


class TestSharedImplementationWithTheSweep:
    def test_run_backfill_calls_the_sweeps_exact_sealing_function(self, db, monkeypatch) -> None:
        """Guards against a future edit reintroducing a second, drifting
        copy of the sealing rule (obs #1965/#1966 lesson)."""
        now = datetime.now(timezone.utc)
        db.add(
            MlOrdersOps(
                order_id=1,
                seller_id=999,
                ml_last_updated=now,
                raw_order=_raw_order(1, payment_ids=[500]),
            )
        )
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(500, 1)))

        calls = []
        original = service.sync_payments_for_order

        def spy(db_arg, order_id, raw_order, payments_payload, **kwargs):
            calls.append(order_id)
            return original(db_arg, order_id, raw_order, payments_payload, **kwargs)

        monkeypatch.setattr(service, "sync_payments_for_order", spy)

        service.run_backfill(limit=10)

        assert calls == [1]


class TestOnlyAnActualFetchCountsAsAnAttempt:
    """The give-up counter must only be charged to a shipment this run
    actually spent an HTTP fetch on -- never to one the cost budget never
    reached. With a backlog wider than the budget, a shipment could
    be abandoned after `MAX_COST_SYNC_ATTEMPTS` runs without ML ever
    having been asked about it once."""

    def _always_fails(self, shipment_id):
        raise ValueError("boom")

    def _cost_sync_attempts(self, db) -> dict:
        rows = (
            db.query(MlOpsDivergence.field, MlOpsDivergence.ml_value)
            .filter(MlOpsDivergence.kind == service._COST_SYNC_DIVERGENCE_KIND)
            .all()
        )
        return {field: ml_value for field, ml_value in rows}

    def test_a_shipment_the_budget_never_reached_is_not_charged_an_attempt(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.add(MlShipmentOps(shipment_id=701, order_id=2))
        db.commit()
        # Room for exactly ONE fetch, and two candidates needing one.
        monkeypatch.setattr(service, "MAX_COST_FETCHES_PER_PASS", 1)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._always_fails)

        service.run_backfill(limit=10)

        attempts = self._cost_sync_attempts(db)
        # 700 is read first and spends the only fetch; 701 is never
        # reached, so it must carry no attempt at all.
        assert attempts == {service._cost_sync_field(700): "1"}

    def test_a_starved_shipment_never_gives_up(self, db, monkeypatch) -> None:
        """The whole point: run it far more times than the attempt limit
        while the budget is always spent elsewhere. The starved shipment
        must still be a candidate at the end."""
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.add(MlShipmentOps(shipment_id=701, order_id=2))
        db.commit()
        monkeypatch.setattr(service, "MAX_COST_FETCHES_PER_PASS", 1)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._always_fails)

        for _ in range(service.MAX_COST_SYNC_ATTEMPTS + 2):
            service.run_backfill(limit=10)

        # 700 burned through its attempts and gave up. Only once it is
        # out of the way does the budget ever reach 701 -- which is the
        # point: 701 is never charged for the runs it did not take part
        # in, so it cannot be abandoned unasked.
        assert 700 in service._gave_up_shipment_ids(db)
        assert 701 not in service._gave_up_shipment_ids(db)

    def test_the_attempt_counter_is_clamped_at_the_limit(self, db) -> None:
        """`_gave_up_shipment_ids` filters on ONE exact
        stored value in SQL, which only holds if the counter stops growing
        at the limit. Driven straight through `_record_cost_sync_attempt`
        on purpose: via `run_backfill` a shipment leaves the candidate set
        the moment it gives up, so the overflow this guards against is
        unreachable from there and a test going through it would pass
        whether the clamp existed or not."""
        for _ in range(service.MAX_COST_SYNC_ATTEMPTS + 3):
            attempts = service._record_cost_sync_attempt(db, 700)
        db.commit()

        assert attempts == service.MAX_COST_SYNC_ATTEMPTS
        assert self._cost_sync_attempts(db) == {service._cost_sync_field(700): str(service.MAX_COST_SYNC_ATTEMPTS)}
        assert 700 in service._gave_up_shipment_ids(db)


class TestARefetchThatRaisesDoesNotTakeTheRunDown:
    """A refetch is one network call among many on a fail-open path: one
    proxy 5xx must not abort the entire run through `run_backfill`'s outer
    handler, taking the shipment cost sync down with it."""

    def test_the_run_survives_and_still_syncs_shipment_costs(self, db, monkeypatch) -> None:
        # An order whose stored payload has NO `payments` key: the only
        # path that triggers a refetch.
        now = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=now, raw_order=_raw_order(1, payment_ids=None)))
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()

        def _boom(order_id):
            raise ConnectionError("proxy 502")

        monkeypatch.setattr(ml_webhook_client, "get_order", _boom)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=_shipment_costs(400, 0)))

        result = service.run_backfill(limit=10)

        assert result.error is None
        assert result.shipment_costs_synced == 1
        # The order stayed unresolved -- never sealed on a failed refetch.
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is None

    def test_the_refetch_answers_to_the_payment_budget(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        for order_id in (1, 2):
            db.add(
                MlOrdersOps(
                    order_id=order_id,
                    seller_id=999,
                    ml_last_updated=now,
                    raw_order=_raw_order(order_id, payment_ids=None),
                )
            )
        db.commit()
        monkeypatch.setattr(service, "MAX_PAYMENT_FETCHES_PER_PASS", 1)
        get_order = AsyncMock(return_value=None)
        monkeypatch.setattr(ml_webhook_client, "get_order", get_order)

        service.run_backfill(limit=10)

        assert get_order.call_count == 1


class TestATruncatedRefetchIsNeverStampedComplete:
    """A candidate the refetch budget never reached leaves no trace in
    `raw_orders`, so the payment-side truncation check cannot see it. If
    that run were stamped complete, `last_success_at` would move and the
    staleness alert would stay quiet while the backlog kept growing --
    the exact failure the truncation flags exist to prevent."""

    def _ambiguous_orders(self, db, count: int) -> None:
        now = datetime.now(timezone.utc)
        for order_id in range(1, count + 1):
            db.add(
                MlOrdersOps(
                    order_id=order_id,
                    seller_id=999,
                    ml_last_updated=now,
                    raw_order=_raw_order(order_id, payment_ids=None),
                )
            )
        db.commit()

    def test_a_run_the_refetch_budget_truncated_reports_it(self, db, monkeypatch) -> None:
        self._ambiguous_orders(db, 2)
        monkeypatch.setattr(service, "MAX_PAYMENT_FETCHES_PER_PASS", 1)
        # Every refetch RESOLVES, and to an order with no payments at all
        # -- so nothing is left unresolved on the payment side and the
        # only evidence of truncation is the starved candidate.
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value={"id": 1, "payments": []}))

        result = service.run_backfill(limit=10)

        assert result.payments_budget_exhausted is True

    def test_a_run_that_resolved_everything_is_not_reported_as_truncated(self, db, monkeypatch) -> None:
        """The mirror image: spending the budget exactly is a complete
        pass, not a truncated one."""
        self._ambiguous_orders(db, 2)
        monkeypatch.setattr(service, "MAX_PAYMENT_FETCHES_PER_PASS", 2)
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value={"id": 1, "payments": []}))

        result = service.run_backfill(limit=10)

        assert result.payments_budget_exhausted is False


class TestNewestFirstDoesNotPutNullsAtTheHead:
    """Postgres defaults `ORDER BY x DESC` to NULLS FIRST, so a row whose
    `date_created` was never persisted -- plausible in exactly the legacy
    population this backfill targets -- would head every run instead of
    the newest sale. SQLite orders NULLs last, so a behavioural test here
    would pass with or without the fix; the compiled SQL is asserted
    instead."""

    def test_the_candidate_ordering_asks_for_nulls_last(self) -> None:
        assert "NULLS LAST" in str(service._orders_newest_first().compile()).upper()


class TestCostTruncationMeasuresWhatWasNeverReached:
    """`costs_budget_exhausted` decides whether the run is stamped
    complete, so it must mean "the budget cut this pass short", not "some
    shipment did not settle". A shipment that WAS fetched and still came
    back unresolved is ML being slow -- reporting that as truncation
    raises the staleness alert on a run that did everything it could."""

    def _fails(self, shipment_id):
        raise ValueError("boom")

    def test_a_fetched_but_unresolved_shipment_is_not_truncation(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()
        # Budget of exactly one, and exactly one candidate: the budget is
        # spent to zero, yet nothing went unreached.
        monkeypatch.setattr(service, "MAX_COST_FETCHES_PER_PASS", 1)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._fails)

        result = service.run_backfill(limit=10)

        assert result.shipment_costs_synced == 0
        assert result.costs_budget_exhausted is False

    def test_a_shipment_the_budget_never_reached_is_truncation(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.add(MlShipmentOps(shipment_id=701, order_id=2))
        db.commit()
        monkeypatch.setattr(service, "MAX_COST_FETCHES_PER_PASS", 1)
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._fails)

        result = service.run_backfill(limit=10)

        assert result.costs_budget_exhausted is True


class TestAFreshPayloadStillMissingPaymentsStaysVisible:
    """Sealing on an omitted `payments` key is correct once the payload is
    fresh off ML -- the omission IS ML's answer. But it is the same fact
    the sweep records a divergence for, and it must not disappear into
    the seal just because it arrived through the backfill instead."""

    def test_the_omission_is_recorded_before_sealing(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=now, raw_order=_raw_order(1, payment_ids=None)))
        db.commit()
        # The refetch SUCCEEDS, and what comes back still has no key.
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value={"id": 1}))

        result = service.run_backfill(limit=10)

        assert result.orders_sealed == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1).one().payments_synced_at is not None
        recorded = (
            db.query(MlOpsDivergence)
            .filter(
                MlOpsDivergence.order_id == 1,
                MlOpsDivergence.field == sweep_service.PAYMENTS_KEY_MISSING_FIELD,
            )
            .one_or_none()
        )
        assert recorded is not None

    def test_an_order_that_does_have_payments_records_nothing(self, db, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=now, raw_order=_raw_order(1, payment_ids=[9])))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=_payment_payload(9, 1)))

        service.run_backfill(limit=10)

        assert (
            db.query(MlOpsDivergence).filter(MlOpsDivergence.field == sweep_service.PAYMENTS_KEY_MISSING_FIELD).count()
            == 0
        )


class TestASuccessClearsTheGiveUpStreak:
    """The cost-sync counter stands for a streak of runs that ended
    without a cost. A shipment that stalls twice, resolves, then stalls
    again must get the full attempt budget the second time -- otherwise
    the stored count spends attempts belonging to a streak that is over."""

    def _fails(self, shipment_id):
        raise ValueError("boom")

    def test_the_counter_is_dropped_when_the_shipment_resolves(self, db, monkeypatch) -> None:
        db.add(MlShipmentOps(shipment_id=700, order_id=1))
        db.commit()
        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", self._fails)
        for _ in range(2):
            service.run_backfill(limit=10)
        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.field == service._cost_sync_field(700)).count() == 1

        monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=_shipment_costs(400, 0)))
        service.run_backfill(limit=10)

        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.field == service._cost_sync_field(700)).count() == 0
