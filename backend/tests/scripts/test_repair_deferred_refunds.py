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
        ids = repair_deferred_refunds._find_candidate_payment_ids()
        assert ids == [500]

    def test_fully_refunded_payment_is_not_a_candidate(self, db):
        db.add(MlPaymentOps(payment_id=501, order_id=2, status="refunded"))
        db.add(
            MlPaymentCharge(
                payment_id=501, name="shp_self_service_tech", type="tax", amount=Decimal("390"), refunded=Decimal("390")
            )
        )
        db.commit()
        assert repair_deferred_refunds._find_candidate_payment_ids() == []

    def test_non_refunded_payment_is_not_a_candidate(self, db):
        db.add(MlPaymentOps(payment_id=502, order_id=3, status="approved"))
        db.add(
            MlPaymentCharge(
                payment_id=502, name="shp_self_service_tech", type="tax", amount=Decimal("390"), refunded=Decimal("0")
            )
        )
        db.commit()
        assert repair_deferred_refunds._find_candidate_payment_ids() == []

    def test_every_candidate_is_selected_with_no_cap(self, db):
        # A backfill must cover the whole affected set. A cap here would
        # truncate silently, and re-running would not advance: a payment ML
        # still reports unrefunded stays a candidate forever and keeps
        # re-occupying the first slots of the payment_id ordering.
        for offset in range(201):
            _seed_affected_payment(db, payment_id=1000 + offset, order_id=1000 + offset)
        ids = repair_deferred_refunds._find_candidate_payment_ids()
        assert len(ids) == 201


class TestExitStatus:
    """The exit code has to say whether the run did what it claims.

    The write guard makes a failed payment survivable, which is right --
    but a run that could not persist 20 payments must not look identical
    to a clean one from the outside. A cron, a chained command or a
    person reading `$?` has no other signal."""

    def test_a_clean_run_exits_zero(self, db, monkeypatch):
        monkeypatch.setattr(
            repair_deferred_refunds,
            "run_repair",
            lambda **kwargs: repair_deferred_refunds.RepairResult(dry_run=False, payments_processed=3),
        )
        repair_deferred_refunds.main([])

    def test_a_run_with_write_failures_exits_non_zero(self, db, monkeypatch):
        monkeypatch.setattr(
            repair_deferred_refunds,
            "run_repair",
            lambda **kwargs: repair_deferred_refunds.RepairResult(
                dry_run=False, payments_processed=1, payments_write_failed=2
            ),
        )
        with pytest.raises(SystemExit) as exc:
            repair_deferred_refunds.main([])
        assert exc.value.code != 0, "una corrida con fallos de escritura salio como exitosa"

    def test_a_run_with_mapping_errors_exits_non_zero(self, db, monkeypatch):
        """Deterministic, but still unfinished work.

        Re-running produces the identical failure, so the message must not
        promise a re-run will fix it -- but the exit code still has to say
        the run left candidates unrepaired."""
        monkeypatch.setattr(
            repair_deferred_refunds,
            "run_repair",
            lambda **kwargs: repair_deferred_refunds.RepairResult(
                dry_run=False, payments_processed=1, payments_mapping_error=1
            ),
        )
        with pytest.raises(SystemExit) as exc:
            repair_deferred_refunds.main([])
        assert exc.value.code != 0, "un error de mapeo salio como corrida exitosa"

    def test_a_run_with_fetch_failures_exits_non_zero(self, db, monkeypatch):
        monkeypatch.setattr(
            repair_deferred_refunds,
            "run_repair",
            lambda **kwargs: repair_deferred_refunds.RepairResult(
                dry_run=False, payments_processed=1, payments_fetch_failed=1
            ),
        )
        with pytest.raises(SystemExit) as exc:
            repair_deferred_refunds.main([])
        assert exc.value.code != 0


class TestRepairRun:
    def test_dry_run_makes_no_http_calls_and_no_writes(self, db, monkeypatch):
        _seed_affected_payment(db)
        mock_get_payment = AsyncMock()
        monkeypatch.setattr(ml_webhook_client, "get_payment", mock_get_payment)

        result = repair_deferred_refunds.run_repair(dry_run=True)

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

        result = repair_deferred_refunds.run_repair(dry_run=False)

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

        result = repair_deferred_refunds.run_repair(dry_run=False)

        assert result.charges_changed == 0
        assert result.charges_unchanged == 1
        charge = db.query(MlPaymentCharge).filter_by(payment_id=500).one()
        assert charge.refunded == Decimal("0")

    def test_payments_changed_counts_payments_not_charges(self, db, monkeypatch):
        """The question `RECHECK_AFTER` has to answer is how many PAYMENTS
        ML reversed late, not how many charge rows moved.

        One payment with three reversed charges is one late reversal, not
        three. Counting charges makes a handful of multi-charge payments
        look like a wave and would push the window in the wrong
        direction."""
        db.add(MlPaymentOps(payment_id=500, order_id=1, status="refunded"))
        for name in ("shp_self_service_tech", "mercadopago_fee", "financing_fee"):
            db.add(
                MlPaymentCharge(
                    payment_id=500,
                    name=name,
                    type="tax",
                    amount=Decimal("100"),
                    refunded=Decimal("0"),
                )
            )
        db.commit()

        charges = [
            {"name": "shp_self_service_tech", "type": "tax", "amount": 100, "refunded": 100},
            {"name": "mercadopago_fee", "type": "tax", "amount": 100, "refunded": 100},
            {"name": "financing_fee", "type": "tax", "amount": 100, "refunded": 100},
        ]
        monkeypatch.setattr(
            ml_webhook_client, "get_payment", AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1, charges))
        )

        result = repair_deferred_refunds.run_repair(dry_run=False)

        assert result.charges_changed == 3, "los cargos siguen contandose uno por uno"
        assert result.payments_changed == 1, f"un pago con 3 cargos conto como {result.payments_changed} pagos"

    def test_a_write_failure_does_not_abort_the_remaining_payments(self, db, monkeypatch):
        """A failed WRITE must not end the run.

        The fetch already has its own guard; the upsert does not, so one
        payment that fails to persist takes the whole loop down and every
        candidate after it is silently never repaired. On a production run
        over the affected payments that looks like a clean finish with a
        smaller number, which is the worst kind of wrong."""
        _seed_affected_payment(db, payment_id=500, order_id=1)
        _seed_affected_payment(db, payment_id=501, order_id=2)

        charges = [{"name": "shp_self_service_tech", "type": "tax", "amount": 390, "refunded": 390}]
        monkeypatch.setattr(
            ml_webhook_client,
            "get_payment",
            AsyncMock(side_effect=lambda pid: _payment_payload(pid, 1 if pid == 500 else 2, charges)),
        )

        real_upsert = repair_deferred_refunds.upsert_payment

        def _fails_for_the_first(db_arg, mapped):
            if mapped.payment_id == 500:
                raise RuntimeError("no se pudo escribir")
            return real_upsert(db_arg, mapped)

        monkeypatch.setattr(repair_deferred_refunds, "upsert_payment", _fails_for_the_first)

        result = repair_deferred_refunds.run_repair(dry_run=False)

        assert result.payments_processed == 1, "el fallo de escritura corto la corrida"
        assert result.payments_write_failed == 1, "no se conto el fallo de escritura"
        # PROOF that the second payment was really repaired, not just
        # counted: the counters alone would also hold if the loop stopped
        # and the numbers happened to line up. The charge in the DB is the
        # only thing that cannot be faked by accounting.
        db.expire_all()
        repaired = db.query(MlPaymentCharge).filter_by(payment_id=501).one()
        assert repaired.refunded == Decimal("390"), "la orden siguiente no se reparo de verdad"
        not_repaired = db.query(MlPaymentCharge).filter_by(payment_id=500).one()
        assert not_repaired.refunded == Decimal("0"), "el pago que fallo al escribir quedo a medias"

    def test_fetch_failure_is_counted_and_does_not_crash(self, db, monkeypatch):
        _seed_affected_payment(db)

        async def raises(payment_id):
            raise ValueError("boom")

        monkeypatch.setattr(ml_webhook_client, "get_payment", raises)

        result = repair_deferred_refunds.run_repair(dry_run=False)

        assert result.payments_fetch_failed == 1
        assert result.payments_processed == 0
