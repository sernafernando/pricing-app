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

from decimal import Decimal

from sqlalchemy import func

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import BillingChargeDTO


def _pack_dto() -> BillingChargeDTO:
    return BillingChargeDTO(
        detail_id="SHIP-1",
        period_key="2026-09-01",
        detail_type="CHARGE",
        detail_sub_type="CSSTEC",
        amount=Decimal("15190.00"),
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

    def test_the_naive_join_sum_would_triple_the_shipping_charge(self, db) -> None:
        """Hace ejecutable la trampa que el lector del corte 6 tiene que
        esquivar.

        El envío de un pack es UN cargo que la tabla puente enlaza a las
        tres órdenes. Sumar `amount` sobre ese join lo carga una vez por
        orden: es el doble conteo que ya mordió en las métricas de TP-Link.
        La forma correcta suma sobre cargos DISTINTOS.

        No protege código que exista todavía. Protege contra escribirlo
        mal: acá está el número equivocado, con nombre, antes de que
        alguien lo descubra en producción.
        """
        upsert_billing_charge(db, _pack_dto())
        db.commit()

        naive = (
            db.query(func.sum(MlBillingCharge.amount))
            .join(MlBillingChargeOrder, MlBillingChargeOrder.detail_id == MlBillingCharge.detail_id)
            .scalar()
        )
        correcto = (
            db.query(func.sum(MlBillingCharge.amount))
            .filter(MlBillingCharge.detail_id.in_(db.query(MlBillingChargeOrder.detail_id).distinct()))
            .scalar()
        )

        assert float(naive) == 45570.0, "el join ingenuo triplica: 15.190 x 3"
        assert float(correcto) == 15190.0

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
