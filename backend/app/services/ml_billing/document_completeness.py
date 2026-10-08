"""Per-document completeness of the persisted billing details (BS-3, BD-3).

A document is complete when the detail rows stored for it match ML's own
`count_details` and `amount` for that document. Everything here is a QUERY over
`ml_billing_documents` and `ml_billing_charges`: no stored count, no stored
sum, no complete flag, no checked-at. The only stored numbers are ML's.

It never compares against the details `total`, which is the rows REMAINING
after the cursor (BS-1), and it is not scoped to an open or closed period: the
caller decides which period and document type to ask about.

Sign: detail amounts are stored the way the mapper writes them (BONUS
negated). A BILL document's amount equals their sum (sign +1; verified on the
2026-09-01 capture: 534,258,231.37 / 56,674,709.86). A CREDIT_NOTE document is
counted with sign -1, per the design. PR 4b verifies that against the captured
credit-note rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ml_billing import MlBillingCharge, MlBillingDocument

DOCUMENT_SIGNS = {"BILL": 1, "CREDIT_NOTE": -1}
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class DocumentCompleteness:
    document_id: str
    document_type: str
    expected_count: int
    expected_amount: Decimal
    stored_count: int
    # The stored rows' sum multiplied by the document type's sign, so it is
    # directly comparable with `expected_amount`.
    stored_amount: Decimal
    complete: bool


def _cents(value) -> Decimal:
    # Via `str`: SQLite sums `Numeric` as float, Postgres returns Decimal.
    return Decimal(str(value if value is not None else 0)).quantize(_CENT)


def document_completeness(db: Session, period_key: str, document_type: str) -> list[DocumentCompleteness]:
    """One entry per persisted document of `period_key` and `document_type`,
    ordered by document id. Read-only."""
    if document_type not in DOCUMENT_SIGNS:
        raise ValueError(f"document_type inválido: {document_type!r} (esperado BILL o CREDIT_NOTE)")
    sign = DOCUMENT_SIGNS[document_type]

    stmt = (
        select(
            MlBillingDocument.document_id,
            MlBillingDocument.count_details,
            MlBillingDocument.amount,
            func.count(MlBillingCharge.detail_id),
            func.coalesce(func.sum(MlBillingCharge.amount), 0),
        )
        .select_from(MlBillingDocument)
        .outerjoin(MlBillingCharge, MlBillingCharge.document_id == MlBillingDocument.document_id)
        .where(MlBillingDocument.period_key == period_key, MlBillingDocument.document_type == document_type)
        .group_by(MlBillingDocument.document_id, MlBillingDocument.count_details, MlBillingDocument.amount)
        .order_by(MlBillingDocument.document_id)
    )

    results: list[DocumentCompleteness] = []
    for document_id, count_details, amount, stored_count, stored_sum in db.execute(stmt):
        expected_count = int(count_details or 0)
        expected_amount = _cents(amount)
        stored_amount = _cents(stored_sum) * sign
        results.append(
            DocumentCompleteness(
                document_id=document_id,
                document_type=document_type,
                expected_count=expected_count,
                expected_amount=expected_amount,
                stored_count=int(stored_count),
                stored_amount=stored_amount,
                # ML's figures are nullable: a missing one is unknown, never 0.
                complete=count_details is not None
                and amount is not None
                and stored_count == expected_count
                and stored_amount == expected_amount,
            )
        )
    return results
