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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import Text, and_, cast, func, not_, nullsfirst, or_, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_orders_ops import (
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

# LISTEN channel of the `ml_orders.quarantine_retry` worker handler.
# `_quarantine_order` notifies it inside the quarantining transaction, so the
# worker wakes once the row is committed (never for a rolled-back one).
QUARANTINE_CHANNEL = "ml_orders_quarantine"

# Failure classes, stored as a prefix of `ml_orders_ops_cuarentena.error` (no
# column of its own: the tag rides on the text the row already keeps).
# TRANSIENT -- pool exhaustion, a dropped connection, a timeout, a lock
# timeout, a deadlock or a serialization failure -- says nothing about the
# order, so it is retried on the backoff with no attempt cap. Anything else
# (a value the database rejects, a payload that no longer maps) is a bug of
# ours that replaying cannot fix: PERMANENT, retried at most
# `MAX_PERMANENT_ATTEMPTS` times, then left alone with one error log.
# Only a row TAGGED permanent is capped: a row quarantined before the tags
# existed gets one more attempt whatever its count, and that attempt tags it.
TRANSIENT_TAG = "[transient] "
PERMANENT_TAG = "[permanent] "
MAX_PERMANENT_ATTEMPTS = 5

# Retry backoff on the LAST attempt: 1 minute * 2^min(intentos, 9), capped at
# 6 hours. No attempt cap for transient failures.
_BACKOFF_BASE = timedelta(minutes=1)
_BACKOFF_MAX_EXPONENT = 9
_BACKOFF_CAP = timedelta(hours=6)


def _backoff(intentos: int) -> timedelta:
    return min(_BACKOFF_BASE * (2 ** min(max(intentos, 0), _BACKOFF_MAX_EXPONENT)), _BACKOFF_CAP)


def _is_transient_write_error(exc: SQLAlchemyError) -> bool:
    """psycopg2 raises `QueryCanceled` (statement/lock timeout),
    `LockNotAvailable`, `DeadlockDetected` and `SerializationFailure` as
    subclasses of its `OperationalError`, which SQLAlchemy wraps in its own
    `OperationalError` -- so that one check covers them."""
    return isinstance(exc, (OperationalError, DisconnectionError, PoolTimeoutError))


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
    # (design D7 row 2), while a write error is quarantined and retried
    # automatically from there so it is never silently lost.
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
        "seller_sku_vendido": item.seller_sku,
        "title": item.title,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "full_unit_price": item.full_unit_price,
        "sale_fee": item.sale_fee,
        "listing_type_id": item.listing_type_id,
        "raw_item": item.raw_item,
    }
    stmt = _insert_stmt(db, MlOrderItemOps.__table__).values(**values)
    update_cols = {
        k: stmt.excluded[k] for k in values if k not in ("order_id", "item_id", "variation_id", "seller_sku_vendido")
    }
    # `seller_sku` follows MercadoLibre (current SKU), but the SKU the item was
    # sold with is kept: the first known value wins. In the SET clause the bare
    # column is the row's OLD value, so a row that predates the column (or was
    # ingested without SKU) adopts its previous current SKU, then the incoming.
    table = MlOrderItemOps.__table__
    update_cols["seller_sku_vendido"] = func.coalesce(
        table.c.seller_sku_vendido, table.c.seller_sku, stmt.excluded["seller_sku"]
    )
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


def _quarantine_order(
    db: Session, order_id: int, raw_order: Dict[str, Any], error_message: str, *, transient: bool
) -> None:
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

    `error_message` is stored with its failure class as a prefix
    (`TRANSIENT_TAG`/`PERMANENT_TAG`), which decides whether the retry ever
    gives up. On Postgres the same SAVEPOINT also notifies
    `QUARANTINE_CHANNEL`, delivered only if the surrounding transaction
    commits.
    """
    error_message = (TRANSIENT_TAG if transient else PERMANENT_TAG) + error_message
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
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SELECT pg_notify(:channel, '')"), {"channel": QUARANTINE_CHANNEL})
            intentos = (
                db.query(MlOrdersOpsCuarentena.intentos).filter(MlOrdersOpsCuarentena.order_id == order_id).scalar()
            )
    except SQLAlchemyError:
        logger.exception("ml_orders_ops: failed to quarantine order_id=%r after a write error", order_id)
        return
    if not transient and intentos >= MAX_PERMANENT_ATTEMPTS:
        # Once per given-up order: a row tagged permanent at or past the cap
        # is never selected by the retry again. `>=`, not `==`: a row can
        # pass the cap while transient and only then fail permanently.
        logger.error(
            "ml_orders_ops: stopped retrying order_id=%s after %s attempts -- permanent write error, "
            "needs a code fix (row kept in ml_orders_ops_cuarentena): %s",
            order_id,
            intentos,
            error_message,
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
            payload (`ml_orders_ops_cuarentena`) and retried automatically
            by the `ml_orders.quarantine_retry` worker -- never a silent
            drop.
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

    stale = False
    try:
        with db.begin_nested():
            applied = _upsert_order_row(db, dto)
            if not applied:
                # FLAGGED, not returned from inside the `with`. A `return`
                # leaves the context manager by the no-exception path, so
                # the SAVEPOINT is RELEASED rather than rolled back. The
                # guarded upsert is a genuine no-op here so nothing is
                # corrupted today, but the docstring promises the stored
                # row is left completely unchanged, and releasing a
                # savepoint is not how you keep that promise -- it only
                # happens to look the same.
                stale = True
            else:
                for item in dto.items:
                    _upsert_item_row(db, dto.order_id, item)

                # Cost snapshot (ml-ventas-modo-logistico, design D4/D13):
                # freezes each item's ERP cost/IVA/exchange rate the FIRST
                # time it is ever seen. INSERT-only -- a re-ingestion of an
                # already-costed item never rewrites its snapshot. Runs
                # after the item rows themselves, and never reads or writes
                # `MlOrderItemOps` -- keeps the cost seam that model
                # documents.
                congelar(db, dto.order_id, dto.items)

                keep_keys = {(item.item_id, item.variation_id) for item in dto.items}
                _delete_stale_items(db, dto.order_id, keep_keys)

                db.flush()
    except SQLAlchemyError as exc:
        # A single failed statement poisons the ENTIRE surrounding
        # PostgreSQL transaction, not just this order's writes -- without
        # the SAVEPOINT above, this except block would be reached only
        # after every sibling order in the same batch was already
        # unrecoverably rolled back too. The `begin_nested()` context
        # manager already rolled back to the savepoint on this exception,
        # so the surrounding transaction is healthy again here.
        error_message = str(exc)[:2000]
        logger.error("ml_orders_ops: write error for order_id=%r: %s", dto.order_id, error_message)
        _quarantine_order(db, dto.order_id, payload, error_message, transient=_is_transient_write_error(exc))
        return UpsertOutcome.WRITE_ERROR

    if stale:
        return UpsertOutcome.SKIPPED_STALE
    return UpsertOutcome.OK


def has_no_payload():
    """A quarantine row with nothing to replay: an order ML did not give back to the activity receiver. SQL NULL, or
    the JSON `null` literal, which the replay of a worker still on the code before remove-ml-divergences D2b stores
    when it re-quarantines such a row (its column had no `none_as_null`) during a deploy."""
    raw_order = MlOrdersOpsCuarentena.raw_order
    return or_(raw_order.is_(None), cast(raw_order, Text) == "null")


def past_backoff(now: datetime):
    """Past its backoff. The backoff is spelled out per attempt count (it
    only has ten distinct values) so one portable expression serves Postgres
    and the SQLite tests alike -- no dialect branch proving a different query
    than production."""
    intentos = MlOrdersOpsCuarentena.intentos
    last = MlOrdersOpsCuarentena.ultimo_intento_at
    return or_(
        last.is_(None),
        *(and_(intentos == k, last < now - _backoff(k)) for k in range(_BACKOFF_MAX_EXPONENT)),
        and_(
            or_(intentos >= _BACKOFF_MAX_EXPONENT, intentos.is_(None)),
            last < now - _backoff(_BACKOFF_MAX_EXPONENT),
        ),
    )


def _due_for_retry(now: datetime):
    """Past its backoff and, if tagged permanent, under the attempt cap."""
    intentos = MlOrdersOpsCuarentena.intentos
    capped = MlOrdersOpsCuarentena.error.like(f"{PERMANENT_TAG}%")
    return and_(past_backoff(now), or_(not_(capped), intentos < MAX_PERMANENT_ATTEMPTS))


def _count_attempt(db: Session, order_id: int) -> None:
    """Advances a row's attempt counter and clock when the attempt itself did
    not (a re-quarantine that failed, or an outcome that never re-quarantines).
    Otherwise the row would stay due and be replayed on every poll. Its own
    SAVEPOINT, like `_quarantine_order`."""
    try:
        with db.begin_nested():
            db.query(MlOrdersOpsCuarentena).filter(MlOrdersOpsCuarentena.order_id == order_id).update(
                {"intentos": MlOrdersOpsCuarentena.intentos + 1, "ultimo_intento_at": func.now()},
                synchronize_session=False,
            )
    except SQLAlchemyError:
        logger.exception("ml_orders_ops: failed to count a quarantine retry attempt for order_id=%r", order_id)


@dataclass
class QuarantineRetryResult:
    """Outcome of one `retry_quarantined_orders` pass."""

    attempted: int = 0
    recovered: int = 0
    still_failed: int = 0
    order_ids: List[int] = field(default_factory=list)


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

    Only DUE rows are selected: past their backoff (`_backoff`), and for a
    row tagged permanent, under `MAX_PERMANENT_ATTEMPTS`. A row with no
    `raw_order` (an order ML did not give back to the activity receiver) has
    nothing to replay and is never selected. Every attempted row
    leaves with its attempt counted, whatever the outcome. A row that is not due
    is simply skipped -- every caller (the worker handler, the sweep, the
    activity drain) shares this gate.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return QuarantineRetryResult()
    # DELIBERATELY WITHOUT the sweep's `window_from_floor`, and this is a
    # decision, not an oversight: a quarantined order is NOT an old order
    # discovered late. It arrived through the feed, inside the window, and
    # we failed to write it. The floor exists so the sweep does not drag
    # ancient history back in; applying it here would instead mean that an
    # order we already accepted gets permanently dropped for having spent
    # too long waiting for OUR fix -- punishing the sale for our own bug.
    # Nothing here reaches ML either: the payload is the one already
    # captured, so no window of API data is being reopened.
    result = QuarantineRetryResult()
    # By LAST attempt, not by first failure. Ordering by `primera_falla_at`
    # puts the oldest quarantined order first on EVERY pass -- and the
    # oldest is, by definition, the one that has been failing longest. A
    # permanently poisoned order would therefore be retried first, forever,
    # and with more than `limit` of them the newly quarantined orders would
    # never get a turn at all: the queue would be blocked by exactly the
    # rows that cannot move. Least-recently-attempted first is a natural
    # round robin, so every order gets its turn.
    # TUPLES, taken before the loop, not ORM instances. The loop deletes
    # from this very table and `upsert_order` may re-UPSERT the same row
    # through `_quarantine_order`, so a live ORM object for it would be
    # stale from the second iteration on -- working today only by the
    # accident of the current ordering.
    # SKIP LOCKED (Postgres; ignored by SQLite): the worker handler, the
    # sweep and the activity drain all call this, and two of them must not
    # replay the same order at once.
    rows = (
        db.query(MlOrdersOpsCuarentena.order_id, MlOrdersOpsCuarentena.raw_order, MlOrdersOpsCuarentena.intentos)
        .filter(not_(has_no_payload()), _due_for_retry(datetime.now(timezone.utc)))
        .order_by(nullsfirst(MlOrdersOpsCuarentena.ultimo_intento_at.asc()))
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    for order_id, raw_order, intentos_before in rows:
        result.attempted += 1
        result.order_ids.append(order_id)
        mapped = map_order(raw_order)
        mapping_error = mapped if isinstance(mapped, MappingError) else None
        outcome = upsert_order(db, raw_order, mapped=None if mapping_error else mapped)
        if outcome in (UpsertOutcome.OK, UpsertOutcome.SKIPPED_STALE):
            db.query(MlOrdersOpsCuarentena).filter(MlOrdersOpsCuarentena.order_id == order_id).delete(
                synchronize_session=False
            )
            result.recovered += 1
        else:
            result.still_failed += 1
            if outcome == UpsertOutcome.MAPPING_ERROR:
                # WRITE_ERROR already re-quarantined (and counted) itself. A
                # payload that no longer maps is a permanent failure too, and
                # without this it would stay due -- first in line -- forever.
                _quarantine_order(
                    db,
                    order_id,
                    raw_order,
                    f"mapping error on retry: {mapping_error.reason if mapping_error else 'unknown'}",
                    transient=False,
                )
            intentos_after = (
                db.query(MlOrdersOpsCuarentena.intentos).filter(MlOrdersOpsCuarentena.order_id == order_id).scalar()
            )
            if intentos_after is not None and intentos_after == intentos_before:
                _count_attempt(db, order_id)

    if rows:
        logger.warning(
            "ml_orders_ops: quarantine retry — attempted=%s recovered=%s still_failed=%s (limit=%s)",
            result.attempted,
            result.recovered,
            result.still_failed,
            limit,
        )
    return result
