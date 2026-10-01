"""Per-order resync (ODD `ventas-ml-ui-pendiente` T7, spec `ml-order-resync`
R22-R24): re-fetch ONE order and its payments/shipment from Mercado Libre
through the same ingestion building blocks the sweep and the activity drain
use, then enqueue its metrics for recompute.

Why it composes the blocks instead of calling `process_batch`: `process_batch`
is gated for the sweep's cost model (an order whose `ml_last_updated` did not
move is skipped, its payments are only re-read when stale/unsynced). A resync
exists precisely for "I do not trust what is stored", so it always re-reads
the order, its payments and its shipment, and writes them through the same
`upsert_order` / `sync_payments_for_order` / `upsert_shipment` functions --
the staleness guard inside `upsert_order` still stops an OLDER payload from
overwriting a newer stored row.

Failure discipline (R24, scenario 3): EVERY HTTP call happens before the
first write. If any of the order, one of its payments or its shipment cannot
be fetched, nothing is written and the caller gets an error naming what
failed -- never a half-applied resync and never a silent success.

Metrics (R23): the capture triggers ignore a no-op write, so a resync whose
data is identical to what is stored would never recompute anything. The order
is therefore enqueued EXPLICITLY (`enqueue_order_metrics`), in the same
transaction as the writes; the worker's drain recomputes the order and its
group.

Connection discipline: no pooled connection is held while waiting on ML. The
existence check's transaction is ended before the first HTTP call; the write
transaction begins only after the last one.

Repeat protection (scenario 4): one resync per order at a time, and a short
cooldown after one finishes. In-process on purpose -- the writes are
idempotent upserts guarded by `ml_last_updated`, so a second API process
racing this one cannot corrupt data; the guard exists so an operator
double-clicking does not spend ML requests twice.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_orders_ingestion.ingestion_service import UpsertOutcome, upsert_order, upsert_shipment
from app.services.ml_orders_ingestion.mapper import MappingError, map_order
from app.services.ml_orders_ingestion.sweep_service import (
    _fetch_payments,
    _fetch_shipments,
    _extract_payment_ids,
    sync_payments_for_order,
)
from app.services.ml_payments_ingestion.mapper import MappingError as PaymentMappingError, map_payment
from app.services.ml_webhook_client import ml_webhook_client
from app.services.order_metrics.queue import enqueue_order_metrics
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

# Seconds an order is protected from another resync after one finished.
COOLDOWN_SECONDS = 10.0
RESYNC_REASON = "resync"


class OrderNotFound(Exception):
    """The order is not in our database: there is nothing to resync."""


class ResyncInProgress(Exception):
    """Another resync of this order is running, or just finished."""


class ResyncFailed(Exception):
    """The resync did not complete; the message is safe to show the operator
    and the stored data is exactly what it was before."""


@dataclass(frozen=True)
class ResyncResult:
    order_id: int
    order_changed: bool


_guard_lock = threading.Lock()
_in_flight: set = set()
_finished_at: Dict[int, float] = {}


def _reset_guard_for_tests() -> None:
    with _guard_lock:
        _in_flight.clear()
        _finished_at.clear()


def _prune_expired(now: float) -> None:
    """Drop entries whose cooldown is over, so `_finished_at` is bounded by
    the resyncs of the last `COOLDOWN_SECONDS`, not by every order ever
    resynced. Caller holds `_guard_lock`."""
    for order_id in [oid for oid, at in _finished_at.items() if now - at >= COOLDOWN_SECONDS]:
        del _finished_at[order_id]


def _try_begin(order_id: int, monotonic: Callable[[], float] = time.monotonic) -> bool:
    with _guard_lock:
        now = monotonic()
        _prune_expired(now)
        if order_id in _in_flight:
            return False
        finished = _finished_at.get(order_id)
        if finished is not None and now - finished < COOLDOWN_SECONDS:
            return False
        _in_flight.add(order_id)
        return True


def _end(order_id: int, *, completed: bool, monotonic: Callable[[], float] = time.monotonic) -> None:
    with _guard_lock:
        _in_flight.discard(order_id)
        now = monotonic()
        _prune_expired(now)
        # A failed attempt does not start a cooldown: the operator should be
        # able to retry at once.
        if completed:
            _finished_at[order_id] = now


def resync_order(db: Session, order_id: int, monotonic: Callable[[], float] = time.monotonic) -> ResyncResult:
    if db.query(MlOrdersOps.order_id).filter(MlOrdersOps.order_id == order_id).first() is None:
        raise OrderNotFound(order_id)
    # End the read transaction NOW: `_resync` makes up to three rounds of HTTP
    # to Mercado Libre, and a session left in a transaction pins a pooled
    # connection for all of it (QueuePool incident, PR #811). The session
    # re-acquires one lazily for the write transaction. ROLLBACK, not commit:
    # the existence check only read, and a commit here would persist whatever
    # unrelated writes the caller's session holds pending (even if the guard
    # then refuses).
    db.rollback()
    if not _try_begin(order_id, monotonic):
        raise ResyncInProgress(order_id)
    completed = False
    try:
        result = _resync(db, order_id)
        completed = True
        return result
    finally:
        _end(order_id, completed=completed, monotonic=monotonic)


def _resync(db: Session, order_id: int) -> ResyncResult:
    # 1. Every HTTP call first.
    try:
        raw_order: Optional[Any] = resolve_maybe_async(ml_webhook_client.get_order(order_id))
    except Exception:  # noqa: BLE001
        logger.warning("resync: order_id=%s fetch raised", order_id, exc_info=True)
        raw_order = None
    if not isinstance(raw_order, dict):
        raise ResyncFailed("No se pudo traer la venta desde Mercado Libre. Los datos guardados no cambiaron.")

    mapped = map_order(raw_order)
    if isinstance(mapped, MappingError):
        raise ResyncFailed(
            "Mercado Libre devolvió la venta en un formato que no se pudo interpretar. "
            "Los datos guardados no cambiaron."
        )

    shipments = _fetch_shipments([raw_order])
    if mapped.shipping_id is not None and mapped.shipping_id not in shipments:
        raise ResyncFailed("No se pudo traer el envío desde Mercado Libre. Los datos guardados no cambiaron.")

    payments = _fetch_payments([raw_order])
    if any(payment_id not in payments for payment_id in _extract_payment_ids(raw_order)):
        raise ResyncFailed(
            "No se pudieron traer todos los pagos desde Mercado Libre. Los datos guardados no cambiaron."
        )

    # A payment that fetched fine but cannot be mapped would be skipped by
    # `sync_payments_for_order` AFTER the order was already written: a
    # partial resync. Catch it here, before the first write.
    if any(isinstance(map_payment(payload), PaymentMappingError) for payload in payments.values()):
        raise ResyncFailed(
            "Mercado Libre devolvió un pago que no se pudo interpretar. Los datos guardados no cambiaron."
        )

    # 2. Then one write transaction.
    try:
        outcome = upsert_order(db, raw_order, mapped=mapped)
        if outcome not in (UpsertOutcome.OK, UpsertOutcome.SKIPPED_STALE):
            db.rollback()
            raise ResyncFailed("No se pudo guardar la venta. Los datos guardados no cambiaron.")
        sync_payments_for_order(db, order_id, raw_order, payments, missing_key_is_empty=True)
        if mapped.shipping_id is not None:
            upsert_shipment(db, shipments[mapped.shipping_id])
        enqueue_order_metrics(db, [order_id], RESYNC_REASON)
        db.commit()
    except ResyncFailed:
        raise
    except Exception:
        db.rollback()
        logger.exception("resync: write failed for order_id=%s", order_id)
        raise ResyncFailed("No se pudo guardar la venta. Los datos guardados no cambiaron.") from None
    return ResyncResult(order_id=order_id, order_changed=outcome == UpsertOutcome.OK)
