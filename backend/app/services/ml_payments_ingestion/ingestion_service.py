"""ML/MP payments write path (ml-ventas-desglose-costos, corte 5).

`upsert_payment` is a pure, session-scoped writer: it takes an
already-open `Session` and a `PaymentDTO`, and does nothing else -- no
HTTP, no sweep loop. Wired into the existing `ml_orders_ingestion` sweep
(`sweep_service.py`), which owns the pacing/refetch decision.

`MlPaymentOps` is upserted keyed on `payment_id` (the MP natural key).

Charges are a REPLACE-SET, not an upsert (post-review fix, pre-push
finding 2): every existing `MlPaymentCharge` row for this `payment_id` is
deleted and the current payload's charges are reinserted in the same
transaction. A purely-additive upsert left a "ghost" row whenever a
refetch reported FEWER charges than before (ML reclassifying/annulling
one) -- the seller-vs-buyer exclusion rule sums charges at READ time
(`app/models/ml_payments.py`), so a ghost row silently kept being counted
forever, breaking the identity that rule exists to preserve.

Charges are also DEDUPED on `(name, type)` before the reinsert (pre-push
finding 3): a single `charges_details[]` payload with two lines sharing
the same `(name, type)` fed straight into a bulk `INSERT ... ON CONFLICT
DO UPDATE` makes PostgreSQL raise `cannot affect row a second time` and
roll back the WHOLE batch transaction -- not just this one payment.
SQLite's upsert emulation does NOT reproduce this (same class of gap the
`payment_id` `BigInteger` choice documents elsewhere in this change), so
that failure mode is proven against real PostgreSQL, never SQLite (see
`tests/services/ml_payments_ingestion/test_ingestion_service.py`).
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_payments_ingestion.mapper import ChargeDTO, PaymentDTO


def _insert_stmt(db: Session, table):
    """Same dialect pick as `ml_billing_ingestion/ingestion_service.py`:
    PostgreSQL (production) and SQLite (tests) both support
    `on_conflict_do_update`/`on_conflict_do_nothing` with the same shape."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(table)
    return postgresql.insert(table)


def _upsert_payment_row(db: Session, dto: PaymentDTO) -> None:
    values: Dict[str, Any] = {
        "payment_id": dto.payment_id,
        "order_id": dto.order_id,
        "status": dto.status,
        "transaction_amount": dto.transaction_amount,
        "shipping_amount": dto.shipping_amount,
        "coupon_amount": dto.coupon_amount,
        "total_paid_amount": dto.total_paid_amount,
        "net_received_amount": dto.net_received_amount,
        "transaction_amount_refunded": dto.transaction_amount_refunded,
        "taxes_amount": dto.taxes_amount,
        "currency_id": dto.currency_id,
        "date_approved": dto.date_approved,
        "raw_payload": dto.raw_payload,
        # Pre-push finding 4: previously never written, so this column was
        # permanently NULL -- a value that always lies to whoever reads it.
        "synced_at": func.now(),
    }
    stmt = _insert_stmt(db, MlPaymentOps.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "payment_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["payment_id"], set_=update_cols)
    db.execute(stmt)


def _dedup_charges(charges: List[ChargeDTO]) -> List[ChargeDTO]:
    """Order-preserving dedup on `(name, type)` -- last occurrence wins.
    See module docstring, finding 3: without this, two lines sharing a key
    in the SAME payload crash the whole batch's transaction on Postgres."""
    deduped: Dict[tuple, ChargeDTO] = {}
    for charge in charges:
        deduped[(charge.name, charge.type)] = charge
    return list(deduped.values())


def _replace_charge_rows(db: Session, dto: PaymentDTO) -> None:
    """Deletes every existing charge row for `dto.payment_id` and
    reinserts the current payload's (deduped) charges, all in the same
    transaction -- see module docstring, finding 2. A plain `INSERT`
    suffices after the delete: there is nothing left to conflict with."""
    db.execute(delete(MlPaymentCharge.__table__).where(MlPaymentCharge.__table__.c.payment_id == dto.payment_id))
    if not dto.charges:
        return
    rows: List[Dict[str, Any]] = [
        {
            "payment_id": dto.payment_id,
            "name": charge.name,
            "type": charge.type,
            "amount": charge.amount,
            "refunded": charge.refunded,
        }
        for charge in _dedup_charges(dto.charges)
    ]
    db.execute(MlPaymentCharge.__table__.insert(), rows)


def upsert_payment(db: Session, dto: PaymentDTO) -> None:
    """Persists one mapped payment: upserts the `MlPaymentOps` row keyed
    on `payment_id`, then REPLACES every charge row for that payment with
    `dto.charges` (deduped on `(name, type)`). Does NOT commit -- the
    caller owns the transaction boundary.

    Args:
        db: An already-open `Session`.
        dto: A `PaymentDTO` from `map_payment` -- callers must have
            already filtered out `MappingError` results.
    """
    _upsert_payment_row(db, dto)
    _replace_charge_rows(db, dto)
