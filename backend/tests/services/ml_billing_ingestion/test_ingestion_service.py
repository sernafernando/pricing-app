"""
RED/GREEN — `upsert_billing_charge` (ml-ventas-desglose-costos, corte 2).

Spec coverage:
  REQ-1 — a single billing charge (one `detail_id`) whose `order_ids` lists
          3 orders of the same pack persists as ONE `MlBillingCharge` row
          and THREE `MlBillingChargeOrder` rows — never triplicated.
  REQ-2 — idempotent: calling it twice with the same DTO does not
          duplicate rows (upsert on `detail_id`, `ON CONFLICT DO NOTHING`
          on the `(detail_id, order_id)` bridge rows).
  REQ-3 — pure/testable in isolation: takes a `Session` and a DTO, no
          sweep, no cron, no client call inside it (corte 3 wires that).
"""

from __future__ import annotations

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import BillingChargeDTO


def _pack_dto() -> BillingChargeDTO:
    return BillingChargeDTO(
        detail_id="SHIP-1",
        period_key="2026-09-01",
        detail_type="CHARGE",
        detail_sub_type="CSSTEC",
        amount=15190.0,
        document_id="DOC1",
        order_ids=[2000018265495500, 2000018265495501, 2000018265495502],
        raw_detail={"charge_info": {"detail_id": "SHIP-1"}},
    )


class TestPackDedup:
    def test_one_charge_row_three_order_rows(self, db) -> None:
        upsert_billing_charge(db, _pack_dto())
        db.commit()

        charges = db.query(MlBillingCharge).all()
        links = db.query(MlBillingChargeOrder).all()

        assert len(charges) == 1
        assert charges[0].detail_id == "SHIP-1"
        assert charges[0].amount == 15190.0
        assert len(links) == 3
        assert {link.order_id for link in links} == {
            2000018265495500,
            2000018265495501,
            2000018265495502,
        }

    def test_sum_of_shipping_charge_counts_once_not_times_three(self, db) -> None:
        upsert_billing_charge(db, _pack_dto())
        db.commit()

        total = db.query(MlBillingCharge).filter(MlBillingCharge.detail_id == "SHIP-1").one().amount
        assert total == 15190.0  # not 15190 * 3


class TestIdempotent:
    def test_calling_twice_does_not_duplicate(self, db) -> None:
        upsert_billing_charge(db, _pack_dto())
        db.commit()
        upsert_billing_charge(db, _pack_dto())
        db.commit()

        assert db.query(MlBillingCharge).count() == 1
        assert db.query(MlBillingChargeOrder).count() == 3

    def test_calling_twice_updates_the_charge_row(self, db) -> None:
        upsert_billing_charge(db, _pack_dto())
        db.commit()

        updated_dto = BillingChargeDTO(
            detail_id="SHIP-1",
            period_key="2026-09-01",
            detail_type="CHARGE",
            detail_sub_type="CSSTEC",
            amount=99999.0,
            document_id="DOC1",
            order_ids=[2000018265495500, 2000018265495501, 2000018265495502],
            raw_detail={"charge_info": {"detail_id": "SHIP-1"}},
        )
        upsert_billing_charge(db, updated_dto)
        db.commit()

        charge = db.query(MlBillingCharge).filter(MlBillingCharge.detail_id == "SHIP-1").one()
        assert charge.amount == 99999.0
