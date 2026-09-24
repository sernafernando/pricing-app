"""Read-only observability aggregates over `ml_order_metrics_dirty`/
`ml_orders_ops`/`ml_order_metrics` (ventas-ml-rediseno PR6, design D9/D10).
Backs `GET /api/ml-ops/order-metrics/health` (`app/routers/ml_order_metrics.py`)
-- never a writer, never a JobHandler. `queue.poisoned_count` (PR3) stays
where it is; the helpers here are new for PR6, kept in their own module so
the queue's claim/fence primitives are not mixed with pure reporting reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import text

from app.services.order_metrics.queue import POISON_THRESHOLD
from app.services.order_metrics.queue import poisoned_count as _queue_poisoned_count

# `worker_alive` (design D9): heartbeat_at younger than this many seconds.
# Matches `app/workers/heartbeat.py`'s own tick cadence (~5s) with generous
# slack for one or two missed ticks. Shared by `GET
# /ml-ops/order-metrics/health` and `GET /ml-ops/sales/kpis` (PR11.T6) so
# both endpoints agree on the same threshold instead of two copies drifting.
WORKER_ALIVE_THRESHOLD_SECONDS = 30


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
    AND already-claimed rows, same `claimed_at IS NULL AND attempts <
    threshold` definition `queue_depth` uses), or `None` when there is none
    -- never a fabricated `0`.

    This intentionally does NOT count a row a worker already holds a lease
    on: the operator watching a backfill (design D10 gate) wants to know how
    stale the still-WAITING queue is, not the age of something already being
    worked -- a claimed-but-old row is progress in flight, not backlog."""
    row = db.execute(
        text(
            "SELECT EXTRACT(EPOCH FROM (now() - min(enqueued_at))) FROM ml_order_metrics_dirty "
            "WHERE claimed_at IS NULL AND attempts < :threshold"
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


def poisoned_count(db) -> int:
    """TRUE total of parked orders (`attempts >= POISON_THRESHOLD`), the
    figure the health endpoint reports as `poisoned_count` (design D9/D10
    production gate). Delegates to `queue.poisoned_count` (PR3), which is
    unlimited -- NEVER derive this from `len(poisoned_orders(...))`, whose
    `limit` caps the sample list at 50 regardless of how many orders are
    actually parked (PR6 review fix J1: a 300-order backlog silently read
    as 50)."""
    return _queue_poisoned_count(db)


def worker_alive(db) -> bool:
    """`True` when the worker's own heartbeat row (`worker_job_state`,
    name='worker') was written less than `WORKER_ALIVE_THRESHOLD_SECONDS`
    ago -- `False` on no row at all (worker never started) or a stale one
    (design D9: "Worker down => queue grows ... visible in the endpoint and
    the KPI strip banner"). Shared by the health endpoint and the KPI
    endpoint (PR11.T6) -- one implementation, not two copies of the same
    threshold check."""
    # Local import: `WorkerJobState` lives in `app.models`, and importing it
    # at module scope here would make this low-level health module depend
    # on the ORM model layer for every OTHER function in it too -- keep the
    # coupling scoped to the one function that actually needs it.
    from app.models.worker_job_state import WorkerJobState

    row = db.query(WorkerJobState.heartbeat_at).filter(WorkerJobState.name == "worker").first()
    if row is None or row.heartbeat_at is None:
        return False
    heartbeat_at = row.heartbeat_at
    now = datetime.now(timezone.utc)
    hb = heartbeat_at if heartbeat_at.tzinfo is not None else heartbeat_at.replace(tzinfo=timezone.utc)
    return (now - hb).total_seconds() < WORKER_ALIVE_THRESHOLD_SECONDS


def poisoned_orders(db, *, limit: int = 50) -> List[PoisonedOrder]:
    """A SAMPLE of parked orders (`attempts >= POISON_THRESHOLD`), oldest
    first, with their `last_error`, capped at `limit` -- the list the D10
    gate requires the user to explicitly review before accepting it. This
    is NEVER exhaustive and must NEVER be used to derive `poisoned_count`
    (PR6 review fix J1): use `poisoned_count` for the count."""
    rows = db.execute(
        text(
            "SELECT order_id, last_error FROM ml_order_metrics_dirty "
            "WHERE attempts >= :threshold ORDER BY enqueued_at LIMIT :limit"
        ),
        {"threshold": POISON_THRESHOLD, "limit": limit},
    ).fetchall()
    return [PoisonedOrder(order_id=row[0], last_error=row[1]) for row in rows]
