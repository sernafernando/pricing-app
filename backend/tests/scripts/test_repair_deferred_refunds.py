"""ml-ventas-repreguntar-pagos-diferido: one-off repair for payments ML
finished refunding after our last look. Candidate selection is a
`refunded` payment with at least one charge stuck at `refunded=0` against
a positive `amount` -- the shape of the production incident (order
2000018524489386). The report must count CHARGES ACTUALLY CHANGED, not
payments sent."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.scripts import repair_deferred_refunds
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
    monkeypatch.setattr(repair_deferred_refunds, "get_background_db", _fake_ctx(db))


def _payment_payload(payment_id: int, order_id: int, charges: list) -> dict:
    return {
        "payment_id": payment_id,
        "order_id": order_id,
        "status": "refunded",
        "currency_id": "ARS",
        "net_received_amount": 0,
        "total_paid_amount": 0,
        "transaction_amount": 0,
        "shipping_amount": 0,
        "coupon_amount": 0,
        "taxes_amount": 0,
        "transaction_amount_refunded": 390,
        "charges_details": charges,
    }


def _seed_affected_payment(db, payment_id: int = 500, order_id: int = 1) -> None:
    db.add(MlPaymentOps(payment_id=payment_id, order_id=order_id, status="refunded"))
    db.add(
        MlPaymentCharge(
            payment_id=payment_id,
            name="shp_self_service_tech",
            type="tax",
            amount=Decimal("390"),
            refunded=Decimal("0"),
        )
    )
    db.commit()


class TestCandidateSelection:
    def test_refunded_payment_with_unrefunded_charge_is_a_candidate(self, db):
        _seed_affected_payment(db)
        ids = repair_deferred_refunds._find_candidate_payment_ids(limit=100)
        assert ids == [500]

    def test_fully_refunded_payment_is_not_a_candidate(self, db):
        db.add(MlPaymentOps(payment_id=501, order_id=2, status="refunded"))
        db.add(
            MlPaymentCharge(
                payment_id=501, name="shp_self_service_tech", type="tax", amount=Decimal("390"), refunded=Decimal("390")
            )
        )
        db.commit()
        assert repair_deferred_refunds._find_candidate_payment_ids(limit=100) == []

    def test_non_refunded_payment_is_not_a_candidate(self, db):
        db.add(MlPaymentOps(payment_id=502, order_id=3, status="approved"))
        db.add(
            MlPaymentCharge(
                payment_id=502, name="shp_self_service_tech", type="tax", amount=Decimal("390"), refunded=Decimal("0")
            )
        )
        db.commit()
        assert repair_deferred_refunds._find_candidate_payment_ids(limit=100) == []


class TestRepairRun:
    def test_dry_run_makes_no_http_calls_and_no_writes(self, db, monkeypatch):
        _seed_affected_payment(db)
        mock_get_payment = AsyncMock()
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        result = repair_deferred_refunds.run_repair(limit=100, dry_run=True)

        mock_get_payment.assert_not_called()
        assert result.candidates_found == 1
        assert result.payments_processed == 0
        charge = db.query(MlPaymentCharge).filter_by(payment_id=500).one()
        assert charge.refunded == Decimal("0")

    def test_a_charge_ml_now_reports_refunded_is_corrected_and_counted_as_changed(self, db, monkeypatch):
        _seed_affected_payment(db)
        payload = _payment_payload(
            500,
            1,
            charges=[{"name": "shp_self_service_tech", "type": "tax", "amount": 390, "refunded": 390}],
        )
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=payload))

        result = repair_deferred_refunds.run_repair(limit=100, dry_run=False)

        assert result.payments_processed == 1
        assert result.charges_changed == 1
        assert result.charges_unchanged == 0
        charge = db.query(MlPaymentCharge).filter_by(payment_id=500).one()
        assert charge.refunded == Decimal("390")

    def test_a_charge_still_unrefunded_is_left_alone_and_counted_as_unchanged(self, db, monkeypatch):
        _seed_affected_payment(db)
        payload = _payment_payload(
            500,
            1,
            charges=[{"name": "shp_self_service_tech", "type": "tax", "amount": 390, "refunded": 0}],
        )
        monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=payload))

        result = repair_deferred_refunds.run_repair(limit=100, dry_run=False)

        assert result.charges_changed == 0
        assert result.charges_unchanged == 1
        charge = db.query(MlPaymentCharge).filter_by(payment_id=500).one()
        assert charge.refunded == Decimal("0")

    def test_fetch_failure_is_counted_and_does_not_crash(self, db, monkeypatch):
        _seed_affected_payment(db)

        async def raises(payment_id):
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_payment", raises)

        result = repair_deferred_refunds.run_repair(limit=100, dry_run=False)

        assert result.payments_fetch_failed == 1
        assert result.payments_processed == 0
