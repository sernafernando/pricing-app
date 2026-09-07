"""
RED/GREEN — `upsert_payment` (ml-ventas-desglose-costos, corte 5).

Spec coverage:
  REQ-1 — one `PaymentDTO` persists as one `MlPaymentOps` row plus one
          `MlPaymentCharge` row per charge.
  REQ-2 — idempotent: re-upserting the SAME dto does not duplicate rows.
  REQ-3 — a REFETCH (order re-ingested after a return) must UPDATE the
          existing charge row's `amount`/`refunded`, not leave it stale --
          unlike the billing charge bridge (`ON CONFLICT DO NOTHING`), a
          payment's own charges can change (e.g. `refunded` growing from
          0 to the full amount).
  REQ-4 — pure/testable in isolation: takes a `Session` and a DTO, no
          HTTP, no sweep loop inside it.
  REQ-5 (pre-push review finding 2, BLOCKING) — a refetch that returns
          FEWER charges than a previous one must DELETE the charge(s) that
          disappeared, not just leave the old row untouched. The old
          purely-additive upsert left a "ghost" charge that a read-time
          SUM (the seller-vs-buyer exclusion rule) would keep counting
          forever after ML reclassified/annulled it.
  REQ-6 (pre-push review finding 3, BLOCKING) — two charge lines in the
          SAME payload sharing `(name, type)` must not crash the whole
          batch's transaction. Postgres raises `ON CONFLICT DO UPDATE
          command cannot affect row a second time` for that shape;
          SQLite does NOT reproduce it (same class of gap as the
          `BigInteger` overflow this change's own module docstring
          documents) -- REQ-6's own test therefore runs against real
          PostgreSQL (`@pytest.mark.postgres`), never SQLite.
  REQ-7 (pre-push review finding 4, minor) — `synced_at` is written with
          the current time, never left permanently NULL.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_payments_ingestion.ingestion_service import upsert_payment
from app.services.ml_payments_ingestion.mapper import ChargeDTO, PaymentDTO


def _dto(**overrides) -> PaymentDTO:
    base = dict(
        payment_id=21000018322969636,
        order_id=2000018322969636,
        status="approved",
        currency_id="ARS",
        date_approved=None,
        transaction_amount=Decimal("7371.11"),
        shipping_amount=Decimal("0"),
        coupon_amount=Decimal("0"),
        total_paid_amount=Decimal("7371.11"),
        net_received_amount=Decimal("6800.50"),
        transaction_amount_refunded=Decimal("0"),
        taxes_amount=Decimal("0"),
        charges=[ChargeDTO(name="mercadopago_fee", type="fee", amount=Decimal("570.61"), refunded=Decimal("0"))],
        raw_payload={"payment_id": 21000018322969636},
    )
    base.update(overrides)
    return PaymentDTO(**base)


class TestUpsertPayment:
    def test_persists_payment_and_charge_rows(self, db) -> None:
        upsert_payment(db, _dto())
        db.commit()

        payments = db.query(MlPaymentOps).all()
        charges = db.query(MlPaymentCharge).all()

        assert len(payments) == 1
        assert payments[0].payment_id == 21000018322969636
        assert payments[0].order_id == 2000018322969636
        assert payments[0].net_received_amount == Decimal("6800.50")
        assert len(charges) == 1
        assert charges[0].name == "mercadopago_fee"
        assert charges[0].amount == Decimal("570.61")

    def test_reupserting_the_same_dto_does_not_duplicate(self, db) -> None:
        upsert_payment(db, _dto())
        db.commit()
        upsert_payment(db, _dto())
        db.commit()

        assert db.query(MlPaymentOps).count() == 1
        assert db.query(MlPaymentCharge).count() == 1

    def test_refetch_updates_charge_refunded_amount(self, db) -> None:
        """A returned order re-triggers a payment refetch; the SAME charge
        (name, type) must reflect the new `refunded` amount, not keep the
        stale value from before the return."""
        upsert_payment(db, _dto())
        db.commit()

        refunded_dto = _dto(
            status="refunded",
            net_received_amount=Decimal("0"),
            transaction_amount_refunded=Decimal("7371.11"),
            charges=[
                ChargeDTO(name="mercadopago_fee", type="fee", amount=Decimal("570.61"), refunded=Decimal("570.61"))
            ],
        )
        upsert_payment(db, refunded_dto)
        db.commit()

        payment = db.query(MlPaymentOps).one()
        charge = db.query(MlPaymentCharge).one()
        assert payment.status == "refunded"
        assert payment.net_received_amount == Decimal("0")
        assert charge.refunded == Decimal("570.61")

    def test_multiple_approved_payments_for_one_order_both_persist(self, db) -> None:
        """Order 2000018322969636 (obs #1960): two approved payments split
        the total. Both must persist as SEPARATE rows -- never merged into
        one, since they are keyed on `payment_id`, not `order_id`."""
        first = _dto(payment_id=1, net_received_amount=Decimal("7371.11"), shipping_amount=Decimal("6990"))
        second = _dto(payment_id=2, net_received_amount=Decimal("12528.89"), shipping_amount=Decimal("0"))

        upsert_payment(db, first)
        upsert_payment(db, second)
        db.commit()

        rows = db.query(MlPaymentOps).filter_by(order_id=2000018322969636).all()
        assert len(rows) == 2
        assert {row.payment_id for row in rows} == {1, 2}

    def test_synced_at_is_stamped(self, db) -> None:
        upsert_payment(db, _dto())
        db.commit()

        payment = db.query(MlPaymentOps).one()
        assert payment.synced_at is not None

    def test_refetch_with_fewer_charges_deletes_the_disappeared_one(self, db) -> None:
        """A charge ML reclassifies/annuls out of `charges_details[]` on a
        later fetch must be REMOVED, not left as a ghost row a read-time
        SUM keeps counting forever."""
        two_charges = _dto(
            charges=[
                ChargeDTO(name="mercadopago_fee", type="fee", amount=Decimal("570.61"), refunded=Decimal("0")),
                ChargeDTO(name="financing_fee", type="fee", amount=Decimal("100.00"), refunded=Decimal("0")),
            ]
        )
        upsert_payment(db, two_charges)
        db.commit()
        assert db.query(MlPaymentCharge).count() == 2

        one_charge = _dto(
            charges=[
                ChargeDTO(name="mercadopago_fee", type="fee", amount=Decimal("570.61"), refunded=Decimal("0")),
            ]
        )
        upsert_payment(db, one_charge)
        db.commit()

        remaining = db.query(MlPaymentCharge).all()
        assert len(remaining) == 1
        assert remaining[0].name == "mercadopago_fee"

    def test_refetch_with_zero_charges_deletes_every_previous_charge(self, db) -> None:
        upsert_payment(db, _dto())
        db.commit()
        assert db.query(MlPaymentCharge).count() == 1

        upsert_payment(db, _dto(charges=[]))
        db.commit()

        assert db.query(MlPaymentCharge).count() == 0


class TestDuplicateChargeNameTypeInSamePayload:
    """REQ-6: two lines sharing `(name, type)` in ONE `charges_details[]`
    must never crash the write -- this class of Postgres-only failure is
    invisible on SQLite (`@pytest.mark.postgres`, same discipline as
    `TestCampoCheckConstraintPostgres` in `tests/tickets/`)."""

    @pytest.mark.postgres
    def test_duplicate_name_type_does_not_crash_the_transaction(self, pg_payments_db) -> None:
        dto = _dto(
            payment_id=999001,
            charges=[
                ChargeDTO(name="mercadopago_fee", type="fee", amount=Decimal("10.00"), refunded=Decimal("0")),
                ChargeDTO(name="mercadopago_fee", type="fee", amount=Decimal("20.00"), refunded=Decimal("0")),
            ],
        )

        upsert_payment(pg_payments_db, dto)
        pg_payments_db.commit()  # must not raise

        charges = pg_payments_db.query(MlPaymentCharge).filter_by(payment_id=999001).all()
        assert len(charges) == 1
