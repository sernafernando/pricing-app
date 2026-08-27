"""ML orders/items/shipments ingestion write path (slice 3 of
ml-ventas-fuente-de-verdad).

`upsert_order`/`upsert_shipment` are the SINGLE writer entry point used by
BOTH the reconciliation sweep (`sweep_service.py`) and any future webhook
accelerator (design D5) -- this is what makes "sweep and webhook updates do
not double-write" structurally true: both paths converge on the same
idempotent `ON CONFLICT` upsert, keyed on the ML natural id, guarded by
`ml_last_updated`/`last_updated` so an older or identical payload is a
no-op, never a corrupting partial overwrite.

Fail-closed contract (design D7, hard-won the slice-2 way -- obs #1843):
`upsert_order`/`upsert_shipment` NEVER raise for a malformed payload. Every
outcome is a `UpsertOutcome` value the caller can act on without a
try/except around this call.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.services.ml_orders_ingestion.mapper import (
    MappingError,
    OrderItemOpsDTO,
    OrderOpsDTO,
    ShipmentOpsDTO,
    map_order,
    map_shipment,
)

logger = logging.getLogger(__name__)


class UpsertOutcome(str, Enum):
    """Every outcome `upsert_order`/`upsert_shipment` can return. Nothing
    outside this enum is ever raised for a bad payload -- see module
    docstring."""

    OK = "ok"
    SKIPPED_STALE = "skipped_stale"
    MAPPING_ERROR = "mapping_error"
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
    write was a structural no-op (an equal-or-older `ml_last_updated`)."""
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
        "tags": dto.tags,
        "raw_order": dto.raw_order,
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


def upsert_order(db: Session, payload: Dict[str, Any]) -> UpsertOutcome:
    """Upserts one ML order + its items, keyed on `order_id`.

    Returns:
        DISABLED       -- `ML_ORDERS_OPS_ENABLED` is False; zero writes.
        MAPPING_ERROR   -- the payload could not be mapped; zero writes.
            This is a RESOLVED per-row failure (design D7 row 2 / hard
            constraint): the caller (sweep) does NOT need to treat this as
            an unresolved window failure -- it is explicitly identified,
            just like `SKIPPED_STALE`, so the window checkpoint may still
            advance as long as every row got one of these four outcomes.
        SKIPPED_STALE   -- the payload's `ml_last_updated` is not newer
            than the stored value (identical re-ingest or an out-of-order
            older update); the stored row is left completely unchanged.
        OK              -- the row (and its items) were inserted/updated.

    NEVER raises for a malformed payload -- see module docstring.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return UpsertOutcome.DISABLED

    result = map_order(payload)
    if isinstance(result, MappingError):
        raw_id = payload.get("id") if isinstance(payload, dict) else None
        logger.warning("ml_orders_ops: mapping error for order_id=%r: %s", raw_id, result.reason)
        return UpsertOutcome.MAPPING_ERROR

    dto = result
    applied = _upsert_order_row(db, dto)
    if not applied:
        return UpsertOutcome.SKIPPED_STALE

    for item in dto.items:
        _upsert_item_row(db, dto.order_id, item)

    db.flush()
    return UpsertOutcome.OK


def upsert_shipment(db: Session, payload: Dict[str, Any]) -> UpsertOutcome:
    """Upserts one ML shipment, keyed on `shipment_id`. Same fail-closed /
    idempotent-guard contract as `upsert_order` (see its docstring)."""
    if not settings.ML_ORDERS_OPS_ENABLED:
        return UpsertOutcome.DISABLED

    result = map_shipment(payload)
    if isinstance(result, MappingError):
        raw_id = payload.get("id") if isinstance(payload, dict) else None
        logger.warning("ml_shipments_ops: mapping error for shipment_id=%r: %s", raw_id, result.reason)
        return UpsertOutcome.MAPPING_ERROR

    dto: ShipmentOpsDTO = result
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
    # `last_updated` can be NULL on a shipment payload (ML does not always
    # send it) -- guard with COALESCE so a NULL never blocks a legitimate
    # refresh nor gets treated as "always newer".
    stmt = stmt.on_conflict_do_update(
        index_elements=["shipment_id"],
        set_=update_cols,
        where=(
            (MlShipmentOps.__table__.c.last_updated.is_(None))
            | (stmt.excluded.last_updated.is_(None))
            | (MlShipmentOps.__table__.c.last_updated < stmt.excluded.last_updated)
        ),
    )
    result_proxy = db.execute(stmt)
    applied = bool(result_proxy.rowcount and result_proxy.rowcount > 0)
    if not applied:
        return UpsertOutcome.SKIPPED_STALE

    db.flush()
    return UpsertOutcome.OK


def sync_order(order_id: int) -> UpsertOutcome:
    """Fetches and upserts a single order (and its shipment, if any) from
    the live ML API. Used by any single-order caller (manual re-sync,
    future webhook accelerator) -- NOT by the bulk sweep, which already
    has the raw payloads from `search_orders` and calls `upsert_order`
    directly to avoid one HTTP round-trip per order.

    Each DB write happens in its OWN short-lived `get_background_db()`
    session, opened AFTER the HTTP fetch completes -- no session is ever
    held across an HTTP call (design D8 / the 2026-06 pool-exhaustion
    incident).
    """
    # Imported lazily to avoid a module-level HTTP-client dependency for
    # every caller of `upsert_order`/`upsert_shipment` (most callers, e.g.
    # the sweep's batch path, never call `sync_order`).
    from app.core.database import get_background_db
    from app.services.ml_webhook_client import ml_webhook_client
    from app.utils.async_bridge import resolve_maybe_async

    if not settings.ML_ORDERS_OPS_ENABLED:
        return UpsertOutcome.DISABLED

    raw_order = resolve_maybe_async(ml_webhook_client.get_order(order_id))
    if raw_order is None:
        logger.warning("sync_order: could not fetch order_id=%s from ML", order_id)
        return UpsertOutcome.MAPPING_ERROR

    with get_background_db() as db:
        outcome = upsert_order(db, raw_order)
        shipping_id: Optional[int] = raw_order.get("shipping", {}).get("id") if outcome == UpsertOutcome.OK else None

    if shipping_id is not None:
        raw_shipment = resolve_maybe_async(ml_webhook_client.get_shipment(shipping_id))
        if raw_shipment is not None:
            with get_background_db() as db:
                upsert_shipment(db, raw_shipment)

    return outcome
