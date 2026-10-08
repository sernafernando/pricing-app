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

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder, MlBillingDocument
from app.services.ml_billing_ingestion.ingestion_service import (
    upsert_billing_charge,
    upsert_billing_document,
)
from app.services.ml_billing_ingestion.mapper import BillingChargeDTO, map_billing_document


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
            amount=Decimal("99999.00"),
            document_id="DOC1",
            order_ids=[2000018265495500, 2000018265495501, 2000018265495502],
            raw_detail={"charge_info": {"detail_id": "SHIP-1"}},
        )
        upsert_billing_charge(db, updated_dto)
        db.commit()

        charge = db.query(MlBillingCharge).filter(MlBillingCharge.detail_id == "SHIP-1").one()
        assert charge.amount == 99999.0


# --- ml-billing-balance PR 2b: documents (BD-1, BD-3) -----------------------

_DOCUMENTS = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing" / "documents_2026_09_01.json").read_text()
)


def _document_dto(document_type: str, document_id: int, **overrides):
    raw = next(d for d in _DOCUMENTS[document_type] if d["id"] == document_id)
    raw = {**raw, **overrides}
    return map_billing_document(raw, "2026-09-01", "ML")


class TestDocumentUpsert:
    def test_bill_is_stored_with_ml_values_and_parsed_reference(self, db) -> None:
        upsert_billing_document(db, _document_dto("BILL", 5140824542))
        db.commit()

        doc = db.query(MlBillingDocument).one()
        assert doc.document_id == "5140824542"
        assert doc.amount == Decimal("534258231.37")
        assert doc.count_details == 26056
        assert (doc.reference_number, doc.legal_point_of_sale, doc.legal_letter, doc.legal_number) == (
            "0058A00975220",
            58,
            "A",
            975220,
        )
        assert doc.raw["id"] == 5140824542

    def test_credit_note_is_stored_though_the_referenced_invoice_is_absent(self, db) -> None:
        upsert_billing_document(db, _document_dto("CREDIT_NOTE", 5144645696))
        db.commit()

        doc = db.query(MlBillingDocument).one()
        assert doc.document_type == "CREDIT_NOTE"
        assert doc.associated_document_id == "5032752366"
        assert db.query(MlBillingDocument).filter_by(document_id="5032752366").count() == 0

    def test_refetch_updates_mutable_fields_without_duplicating(self, db) -> None:
        upsert_billing_document(db, _document_dto("BILL", 5140824542, unpaid_amount=1500.5, document_status="OPEN"))
        db.commit()
        upsert_billing_document(db, _document_dto("BILL", 5140824542))
        db.commit()

        assert db.query(MlBillingDocument).count() == 1
        doc = db.query(MlBillingDocument).one()
        assert doc.document_status == "BILLED"
        assert doc.unpaid_amount == Decimal("0")


class TestChargeStoresDocumentAndLegalFields:
    def test_the_new_columns_are_written_and_updated(self, db) -> None:
        dto = BillingChargeDTO(
            detail_id="70000000001",
            period_key="2026-09-01",
            detail_type="CHARGE",
            detail_sub_type="CVFV",
            amount=Decimal("100.00"),
            document_id="5140824542",
            raw_detail={},
            document_type="BILL",
            legal_document_number=None,
            legal_document_status="PROCESSING",
        )
        upsert_billing_charge(db, dto)
        db.commit()
        later = BillingChargeDTO(
            **{**dto.__dict__, "legal_document_number": "0058A00975220", "legal_document_status": "PROCESSED"}
        )
        upsert_billing_charge(db, later)
        db.commit()

        charge = db.query(MlBillingCharge).one()
        assert charge.document_type == "BILL"
        assert charge.billing_source == "general"
        assert (charge.legal_document_number, charge.legal_document_status) == ("0058A00975220", "PROCESSED")
