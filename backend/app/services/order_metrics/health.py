"""Read-only observability aggregates over `ml_order_metrics_dirty`/
`ml_orders_ops`/`ml_order_metrics` (ventas-ml-rediseno PR6, design D9/D10).
Backs `GET /api/ml-ops/order-metrics/health` (`app/routers/ml_order_metrics.py`)
-- never a writer, never a JobHandler. `queue.poisoned_count` (PR3) stays
where it is; the helpers here are new for PR6, kept in their own module so
the queue's claim/fence primitives are not mixed with pure reporting reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text

from app.services.order_metrics.queue import POISON_THRESHOLD


@dataclass(frozen=True)
class PoisonedOrder:
    order_id: int
    last_error: Optional[str]


def queue_depth(db) -> int:
    """Claimable rows only (design D9): not yet claimed by any worker, and
    not parked (`attempts >= POISON_THRESHOLD`). A parked row still sits in
    the table but can never be claimed again, so it must never inflate the
    number an operator reads as "work still to do"."""
    row = db.execute(
        text("SELECT count(*) FROM ml_order_metrics_dirty WHERE claimed_at IS NULL AND attempts < :threshold"),
        {"threshold": POISON_THRESHOLD},
    ).fetchone()
    return int(row[0]) if row else 0


def claimed_count(db) -> int:
    """Rows currently held by some worker's lease (`claimed_at IS NOT NULL`)."""
    row = db.execute(text("SELECT count(*) FROM ml_order_metrics_dirty WHERE claimed_at IS NOT NULL")).fetchone()
    return int(row[0]) if row else 0


def oldest_dirty_age_seconds(db) -> Optional[float]:
    """Age in seconds of the oldest CLAIMABLE dirty row (excludes parked
    rows, same rationale as `queue_depth`), or `None` when there is none --
    never a fabricated `0`."""
    row = db.execute(
        text(
            "SELECT EXTRACT(EPOCH FROM (now() - min(enqueued_at))) FROM ml_order_metrics_dirty "
            "WHERE attempts < :threshold"
        ),
        {"threshold": POISON_THRESHOLD},
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def missing_metrics_count(db) -> int:
    """Orders with no `ml_order_metrics` row yet, EXCLUDING parked orders
    (design D10 gate: "missing_count ... EXCLUDES parked ones"). An order
    with no metrics row and no dirty row (never enqueued -- unreachable
    once reconcile runs, but defensive) or a non-parked dirty row still
    counts; a parked order (`attempts >= POISON_THRESHOLD`) is reported
    separately via `poisoned_orders`, never double-counted here."""
    row = db.execute(
        text(
            """
            SELECT count(*) FROM ml_orders_ops o
            LEFT JOIN ml_order_metrics m ON m.order_id = o.order_id
            LEFT JOIN ml_order_metrics_dirty d ON d.order_id = o.order_id
            WHERE m.order_id IS NULL
              AND (d.order_id IS NULL OR d.attempts < :threshold)
            """
        ),
        {"threshold": POISON_THRESHOLD},
    ).fetchone()
    return int(row[0]) if row else 0


def poisoned_orders(db, *, limit: int = 50) -> List[PoisonedOrder]:
    """Parked orders (`attempts >= POISON_THRESHOLD`), oldest first, with
    their `last_error` -- the health endpoint's `poisoned_count` figure AND
    the list the D10 gate requires the user to explicitly review before
    accepting it."""
    rows = db.execute(
        text(
            "SELECT order_id, last_error FROM ml_order_metrics_dirty "
            "WHERE attempts >= :threshold ORDER BY enqueued_at LIMIT :limit"
        ),
        {"threshold": POISON_THRESHOLD, "limit": limit},
    ).fetchall()
    return [PoisonedOrder(order_id=row[0], last_error=row[1]) for row in rows]
