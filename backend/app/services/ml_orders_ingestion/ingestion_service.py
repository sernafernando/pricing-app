"""ML orders/items/shipments ingestion write path (slice 3 of
ml-ventas-fuente-de-verdad).

`upsert_order` is the SINGLE writer entry point used by
BOTH the reconciliation sweep (`sweep_service.py`) and any future webhook
accelerator (design D5) -- this is what makes "sweep and webhook updates do
not double-write" structurally true: both paths converge on the same
idempotent `ON CONFLICT` upsert, keyed on the ML natural id, guarded by
`ml_last_updated`/`last_updated` so an older or identical payload is a
no-op, never a corrupting partial overwrite.

Fail-closed contract (design D7, hard-won the slice-2 way -- obs #1843):
`upsert_order` NEVER raises for a malformed payload. Every
outcome is a `UpsertOutcome` value the caller can act on without a
try/except around this call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_orders_ops import (
    INGEST_FAILED_KIND,
    MlOpsDivergence,
    MlOrderItemOps,
    MlOrdersOps,
    MlOrdersOpsCuarentena,
    MlShipmentOps,
)
from app.services.ml_orders_ingestion.costeo_service import congelar
from app.services.ml_orders_ingestion.mapper import (
    MappingError,
    OrderItemOpsDTO,
    OrderOpsDTO,
    ShipmentOpsDTO,
    map_order,
    map_shipment,
)
from app.services.ml_orders_ingestion.mode_resolution import has_no_shipping_tag

logger = logging.getLogger(__name__)

# Cap on how many quarantined orders `retry_quarantined_orders` re-attempts
# in a single pass. The retry is deliberately UNBOUNDED in how long it may
# take to drain the whole backlog (it runs again every pass), but bounded
# per pass so a large backlog cannot turn the retry into the main job and
# starve fresh ingestion of its own budget.
MAX_QUARANTINE_RETRIES_PER_PASS = 50


class UpsertOutcome(str, Enum):
    """Every outcome `upsert_order` can return. Nothing
    outside this enum is ever raised for a bad payload -- see module
    docstring."""

    OK = "ok"
    SKIPPED_STALE = "skipped_stale"
    MAPPING_ERROR = "mapping_error"
    # Distinct from MAPPING_ERROR on purpose: mapping_error means the
    # payload could not be UNDERSTOOD; write_error means it WAS understood
    # and the database rejected the write anyway (2026-09-14 incident: a
    # `status_detail` payload shaped as a dict, not a string). Readers of
    # these counters route them to different places -- a mapping error is
    # a resolved per-row outcome the window checkpoint may advance past
    # (design D7 row 2), while a write error is quarantined AND raised as
    # a visible `ingest_failed` divergence so it is never silently lost.
    WRITE_ERROR = "write_error"
    DISABLED = "disabled"


def _insert_stmt(db: Session, table):
    """Picks the dialect-appropriate `INSERT ... ON CONFLICT` construct.
    Both PostgreSQL (production) and SQLite (`tests/conftest.py`'s
    in-memory test DB) support `on_conflict_do_update(..., where=...)`
    with the same call shape, so this is the only dialect branch needed."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(table)
    return postgresql.insert(table)


def _upsert_order_row(db: Session, dto: OrderOpsDTO) -> bool:
    """Returns True if the row was inserted or updated, False if the
    write was a structural no-op (an equal-or-older `ml_last_updated`).

    `has_no_shipping_tag` (design D1 of ml-ventas-modo-logistico) is
    derived here from `dto.tags` rather than queried at read time with a
    Postgres JSONB containment predicate: the test suite runs on SQLite,
    which cannot exercise that predicate, so a read-time rule would ship
    proven by a test running a different query than production.

    The resolved mode itself is NOT stored. It is recomputed live by the
    API from the joined shipment row, because the shipment upsert runs
    separately and may land after this one -- a stored mode would be a
    snapshot that is wrong for exactly as long as that gap lasts.
    """
    no_shipping_tag = has_no_shipping_tag(dto.tags)
    values: Dict[str, Any] = {
        "order_id": dto.order_id,
        "pack_id": dto.pack_id,
        "status": dto.status,
        "status_detail": dto.status_detail,
        "date_created": dto.date_created,
        "date_closed": dto.date_closed,
        "ml_last_updated": dto.ml_last_updated,
        "buyer_id": dto.buyer_id,
        "buyer_nickname": dto.buyer_nickname,
        "seller_id": dto.seller_id,
        "total_amount": dto.total_amount,
        "paid_amount": dto.paid_amount,
        "currency_id": dto.currency_id,
        "shipping_id": dto.shipping_id,
        "payment_status": dto.payment_status,
        "covered_by_marketplace": dto.covered_by_marketplace,
        "tags": dto.tags,
        "raw_order": dto.raw_order,
        "has_no_shipping_tag": no_shipping_tag,
        "ingest_error": None,
        "last_synced_at": func.now(),
    }
    stmt = _insert_stmt(db, MlOrdersOps.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "order_id"}
    stmt = stmt.on_conflict_do_update(
        index_elements=["order_id"],
        set_=update_cols,
        where=(MlOrdersOps.__table__.c.ml_last_updated < stmt.excluded.ml_last_updated),
    )
    result = db.execute(stmt)
    return bool(result.rowcount and result.rowcount > 0)


def _delete_stale_items(db: Session, order_id: int, keep_keys: "set[tuple[str, Optional[int]]]") -> None:
    """Deletes item rows for `order_id` that are no longer present in the
    latest payload (partial cancellation, variation change). A source of
    truth that only ever inserts/updates items accumulates phantom rows
    forever -- this closes that gap. Runs in the SAME transaction as the
    order/items upsert (no separate commit), so a rollback undoes both.

    Compared in Python rather than a SQL `NOT IN`: `variation_id` can be
    NULL, and `NOT IN` with a NULL in the excluded set is a classic SQL
    footgun (the whole comparison silently evaluates to unknown/false for
    every row). Order item counts are small, so the extra SELECT is cheap.
    """
    existing = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id == order_id).all()
    for row in existing:
        if (row.item_id, row.variation_id) not in keep_keys:
            db.delete(row)


def _upsert_item_row(db: Session, order_id: int, item: OrderItemOpsDTO) -> None:
    values: Dict[str, Any] = {
        "order_id": order_id,
        "item_id": item.item_id,
        "variation_id": item.variation_id,
        "seller_sku": item.seller_sku,
        "title": item.title,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "full_unit_price": item.full_unit_price,
        "sale_fee": item.sale_fee,
        "listing_type_id": item.listing_type_id,
        "raw_item": item.raw_item,
    }
    stmt = _insert_stmt(db, MlOrderItemOps.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k not in ("order_id", "item_id", "variation_id")}
    stmt = stmt.on_conflict_do_update(
        index_elements=["order_id", "item_id", "variation_id"],
        set_=update_cols,
    )
    db.execute(stmt)


def _upsert_shipment_row(db: Session, dto: ShipmentOpsDTO) -> bool:
    """Same idempotent ON CONFLICT pattern as `_upsert_order_row`. Guarded
    by `last_updated` rather than `ml_last_updated` (shipments carry no
    field of that name); a shipment payload with no `last_updated` (some
    do not) always overwrites, since there is nothing to compare against."""
    values: Dict[str, Any] = {
        "shipment_id": dto.shipment_id,
        "order_id": dto.order_id,
        "status": dto.status,
        "substatus": dto.substatus,
        "logistic_type": dto.logistic_type,
        "tracking_number": dto.tracking_number,
        "tracking_method": dto.tracking_method,
        "date_created": dto.date_created,
        "last_updated": dto.last_updated,
        "receiver_address": dto.receiver_address,
        "raw_shipment": dto.raw_shipment,
        "last_synced_at": func.now(),
    }
    stmt = _insert_stmt(db, MlShipmentOps.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "shipment_id"}
    stmt = stmt.on_conflict_do_update(
        index_elements=["shipment_id"],
        set_=update_cols,
        where=(
            MlShipmentOps.__table__.c.last_updated.is_(None)
            | (stmt.excluded.last_updated.is_(None))
            | (MlShipmentOps.__table__.c.last_updated < stmt.excluded.last_updated)
        ),
    )
    result = db.execute(stmt)
    return bool(result.rowcount and result.rowcount > 0)


def upsert_shipment(db: Session, payload: Dict[str, Any], mapped: Optional[ShipmentOpsDTO] = None) -> UpsertOutcome:
    """Upserts one ML shipment, keyed on `shipment_id`. Same outcome
    contract as `upsert_order` -- see that function's docstring.

    Called by the sweep (`sweep_service.py`) for every order that carries
    a `shipping_id`; the shipment payload is fetched OUTSIDE any DB
    session (HTTP-before-write, same as the order fetch) and handed in
    here already fetched. NEVER raises for a malformed payload.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return UpsertOutcome.DISABLED

    result = mapped if mapped is not None else map_shipment(payload)
    if isinstance(result, MappingError):
        raw_id = payload.get("id") if isinstance(payload, dict) else None
        logger.warning("ml_shipments_ops: mapping error for shipment_id=%r: %s", raw_id, result.reason)
        return UpsertOutcome.MAPPING_ERROR

    dto = result
    applied = _upsert_shipment_row(db, dto)
    if not applied:
        return UpsertOutcome.SKIPPED_STALE

    db.flush()
    return UpsertOutcome.OK


def _quarantine_order(db: Session, order_id: int, raw_order: Dict[str, Any], error_message: str) -> None:
    """Records a per-order write failure (`UpsertOutcome.WRITE_ERROR`) so
    it is never silently lost. Runs in its OWN SAVEPOINT: recording the
    failure must not be able to take the batch down a second time.

    `raw_order` is stored untouched (persist ALL the data, never trim it)
    so `retry_quarantined_orders` can replay the exact same write with
    zero HTTP calls once the underlying bug is fixed. Upserted, not just
    inserted, on `order_id`: a repeat failure of the same order (from a
    later pass, or from `retry_quarantined_orders` itself) updates the
    existing row's `error`/`intentos` instead of erroring on the
    duplicate primary key.
    """
    try:
        with db.begin_nested():
            stmt = _insert_stmt(db, MlOrdersOpsCuarentena.__table__).values(
                order_id=order_id,
                raw_order=raw_order,
                error=error_message,
                intentos=1,
                primera_falla_at=func.now(),
                ultimo_intento_at=func.now(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["order_id"],
                set_={
                    "raw_order": stmt.excluded.raw_order,
                    "error": stmt.excluded.error,
                    "intentos": MlOrdersOpsCuarentena.__table__.c.intentos + 1,
                    "ultimo_intento_at": func.now(),
                },
            )
            db.execute(stmt)
    except (SQLAlchemyError, DBAPIError):
        logger.exception("ml_orders_ops: failed to quarantine order_id=%r after a write error", order_id)


def _open_ingest_failed_divergence(db: Session, order_id: int, error_message: str) -> None:
    """Surfaces a quarantined order on the existing divergences dashboard
    (`GET /ml-ventas-ops/divergences`) instead of leaving it visible only
    in a log line nobody watches (explicit user requirement). Own
    SAVEPOINT for the same reason as `_quarantine_order`."""
    try:
        with db.begin_nested():
            existing = (
                db.query(MlOpsDivergence)
                .filter(
                    MlOpsDivergence.order_id == order_id,
                    MlOpsDivergence.kind == INGEST_FAILED_KIND,
                    MlOpsDivergence.field.is_(None),
                )
                .first()
            )
            if existing is not None:
                existing.ml_value = error_message
                existing.state = "open"
            else:
                db.add(
                    MlOpsDivergence(
                        order_id=order_id,
                        kind=INGEST_FAILED_KIND,
                        field=None,
                        ml_value=error_message,
                        state="open",
                    )
                )
    except (SQLAlchemyError, DBAPIError):
        logger.exception("ml_orders_ops: failed to open an ingest_failed divergence for order_id=%r", order_id)


def _resolve_ingest_failed_divergence(db: Session, order_id: int) -> None:
    """Closes the alarm once a quarantined order is recovered. Marked
    `resolved`, not deleted: deleting would erase the audit trail of what
    failed and for how long (persist-everything principle)."""
    (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == order_id,
            MlOpsDivergence.kind == INGEST_FAILED_KIND,
            MlOpsDivergence.state != "resolved",
        )
        .update({"state": "resolved"}, synchronize_session=False)
    )


def upsert_order(db: Session, payload: Dict[str, Any], mapped: Optional[OrderOpsDTO] = None) -> UpsertOutcome:
    """Upserts one ML order + its items, keyed on `order_id`.

    Returns:
        DISABLED       -- `ML_ORDERS_OPS_ENABLED` is False; zero writes.
        MAPPING_ERROR   -- the payload could not be mapped; zero writes.
            This is a RESOLVED per-row failure (design D7 row 2 / hard
            constraint): the caller (sweep) does NOT need to treat this as
            an unresolved window failure -- it is explicitly identified,
            just like `SKIPPED_STALE`, so the window checkpoint may still
            advance as long as every row got one of these five outcomes.
        WRITE_ERROR     -- the payload WAS mapped, but the database
            rejected the write (2026-09-14 incident: a `status_detail`
            payload shaped as a dict, not a string). The write runs
            inside its own SAVEPOINT so it cannot poison the rest of the
            caller's batch, the failing order is quarantined with its raw
            payload (`ml_orders_ops_cuarentena`) for automatic retry, and
            an `ingest_failed` divergence is opened so it is visible on
            the dashboard -- never a silent drop.
        SKIPPED_STALE   -- the payload's `ml_last_updated` is not newer
            than the stored value (identical re-ingest or an out-of-order
            older update); the stored row is left completely unchanged.
        OK              -- the row (and its items) were inserted/updated.

    `mapped` lets a caller that already mapped the payload (the sweep,
    which needs the DTO to apply the window bound) hand it over instead of
    paying for a second identical mapping per row.

    NEVER raises for a malformed payload OR a rejected write -- see module
    docstring.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return UpsertOutcome.DISABLED

    result = mapped if mapped is not None else map_order(payload)
    if isinstance(result, MappingError):
        raw_id = payload.get("id") if isinstance(payload, dict) else None
        logger.warning("ml_orders_ops: mapping error for order_id=%r: %s", raw_id, result.reason)
        return UpsertOutcome.MAPPING_ERROR

    dto = result

    try:
        with db.begin_nested():
            applied = _upsert_order_row(db, dto)
            if not applied:
                return UpsertOutcome.SKIPPED_STALE

            for item in dto.items:
                _upsert_item_row(db, dto.order_id, item)

            # Cost snapshot (ml-ventas-modo-logistico, design D4/D13):
            # freezes each item's ERP cost/IVA/exchange rate the FIRST
            # time it is ever seen. INSERT-only -- a re-ingestion of an
            # already-costed item never rewrites its snapshot. Runs after
            # the item rows themselves, and never reads or writes
            # `MlOrderItemOps` -- keeps the cost seam that model
            # documents.
            congelar(db, dto.order_id, dto.items)

            keep_keys = {(item.item_id, item.variation_id) for item in dto.items}
            _delete_stale_items(db, dto.order_id, keep_keys)

            db.flush()
    except (SQLAlchemyError, DBAPIError) as exc:
        # A single failed statement poisons the ENTIRE surrounding
        # PostgreSQL transaction, not just this order's writes -- without
        # the SAVEPOINT above, this except block would be reached only
        # after every sibling order in the same batch was already
        # unrecoverably rolled back too. The `begin_nested()` context
        # manager already rolled back to the savepoint on this exception,
        # so the surrounding transaction is healthy again here.
        error_message = str(exc)[:2000]
        logger.error("ml_orders_ops: write error for order_id=%r: %s", dto.order_id, error_message)
        _quarantine_order(db, dto.order_id, payload, error_message)
        _open_ingest_failed_divergence(db, dto.order_id, error_message)
        return UpsertOutcome.WRITE_ERROR

    return UpsertOutcome.OK


@dataclass
class QuarantineRetryResult:
    """Outcome of one `retry_quarantined_orders` pass."""

    attempted: int = 0
    recovered: int = 0
    still_failed: int = 0


def retry_quarantined_orders(db: Session, limit: int = MAX_QUARANTINE_RETRIES_PER_PASS) -> QuarantineRetryResult:
    """Automatically re-attempts quarantined orders from their STORED raw
    payload -- zero HTTP calls, since the payload is already in hand.

    This is the recovery half of the 2026-09-14 fix: isolating a bad order
    (`WRITE_ERROR`) only stops it from taking down the batch; without this,
    it would still be lost forever, because the sweep and the drain both
    converge on the same `upsert_order` that failed on it the first time,
    so a plain re-ingest fails identically. The day a fix ships, this is
    what makes the data heal WITHOUT anyone running anything by hand.

    Bounded by `limit` per pass (see `MAX_QUARANTINE_RETRIES_PER_PASS`) so
    a large backlog cannot turn the retry into the main job.
    """
    result = QuarantineRetryResult()
    rows = db.query(MlOrdersOpsCuarentena).order_by(MlOrdersOpsCuarentena.primera_falla_at.asc()).limit(limit).all()
    for row in rows:
        result.attempted += 1
        outcome = upsert_order(db, row.raw_order)
        if outcome in (UpsertOutcome.OK, UpsertOutcome.SKIPPED_STALE):
            db.query(MlOrdersOpsCuarentena).filter(MlOrdersOpsCuarentena.order_id == row.order_id).delete()
            _resolve_ingest_failed_divergence(db, row.order_id)
            result.recovered += 1
        else:
            result.still_failed += 1

    if rows:
        logger.warning(
            "ml_orders_ops: quarantine retry — attempted=%s recovered=%s still_failed=%s (limit=%s)",
            result.attempted,
            result.recovered,
            result.still_failed,
            limit,
        )
    return result
