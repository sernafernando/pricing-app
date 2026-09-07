"""ML billing charges write path (ml-ventas-desglose-costos, corte 2).

`upsert_billing_charge` is a pure, session-scoped writer: it takes an
already-open `Session` and a `BillingChargeDTO`, and does nothing else --
no HTTP, no sweep loop, no lock, no cursor. Corte 3 wires this into a
once-daily sweep with its own lock/cursor, mirroring how
`ml_orders_ingestion/ingestion_service.py::upsert_order` is the single
writer both the sweep and a future webhook accelerator converge on.

Idempotent by construction (design): `MlBillingCharge` is upserted keyed
on `detail_id` (ML's natural key for a billing detail line), and each
`MlBillingChargeOrder` bridge row is inserted `ON CONFLICT DO NOTHING` on
the `(detail_id, order_id)` unique constraint already declared on the
model. A single shipping charge whose `items_info[]` lists every order in
a pack therefore persists as ONE `MlBillingCharge` row and one bridge row
PER order in the pack -- the charge amount is stored once, never summed
or duplicated across the pack's orders.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.services.ml_billing_ingestion.mapper import BillingChargeDTO

logger = logging.getLogger(__name__)


def _insert_stmt(db: Session, table):
    """Same dialect pick as `ml_orders_ingestion/ingestion_service.py`:
    PostgreSQL (production) and SQLite (tests) both support
    `on_conflict_do_update`/`on_conflict_do_nothing` with the same shape."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(table)
    return postgresql.insert(table)


def _upsert_charge_row(db: Session, dto: BillingChargeDTO) -> None:
    values: Dict[str, Any] = {
        "detail_id": dto.detail_id,
        "period_key": dto.period_key,
        "detail_type": dto.detail_type,
        "detail_sub_type": dto.detail_sub_type,
        "amount": dto.amount,
        "document_id": dto.document_id,
        "raw_detail": dto.raw_detail,
    }
    stmt = _insert_stmt(db, MlBillingCharge.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "detail_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["detail_id"], set_=update_cols)
    db.execute(stmt)


def _link_order_rows(db: Session, dto: BillingChargeDTO) -> None:
    """One bridge row per `order_id` in `dto.order_ids` -- ALREADY deduped
    by the mapper (`_dedup_order_ids`). `ON CONFLICT DO NOTHING`: re-
    running the same detail (idempotent re-sweep) must not duplicate or
    error on an existing link."""
    if not dto.order_ids:
        return
    rows = [{"detail_id": dto.detail_id, "order_id": order_id} for order_id in dto.order_ids]
    stmt = _insert_stmt(db, MlBillingChargeOrder.__table__).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["detail_id", "order_id"])
    db.execute(stmt)


def upsert_billing_charge(db: Session, dto: BillingChargeDTO) -> None:
    """Persists one mapped billing charge: upserts the `MlBillingCharge`
    row keyed on `detail_id`, then links every order in `dto.order_ids`
    via `MlBillingChargeOrder`. Does NOT commit -- the caller owns the
    transaction boundary (batch commit, same as `ml_orders_ingestion`).

    Args:
        db: An already-open `Session`.
        dto: A `BillingChargeDTO` from `map_billing_detail` -- callers
            must have already filtered out `MappingError` results.
    """
    _upsert_charge_row(db, dto)
    _link_order_rows(db, dto)
