"""`order_metrics.drain` (design D5, D6, PR3.T6/T7): claims batches of
`ml_order_metrics_dirty` rows, recomputes them in bulk (COMPUTE phase, no
row locks), then stores each order in its OWN short transaction (STORE
phase, design D5 rev 6) until the queue has no more claimable rows or
`ctx.deadline` is reached. Registered with `channels=("order_metrics_dirty",)`
so `WorkerRuntime.drain_once` runs it on every LISTEN wake AND every safety
poll (design D4 step 2), never on a fixed schedule.

`order_metrics.reconcile` and `order_metrics.divergence` (PR6) are siblings
of this module, not shipped here.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_background_db
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.queue import Claim, claim_dirty, fenced_store, mark_failed, release_uncharged
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

# design D10: reconcile enqueues in batches of 5000, set-based, via the
# SYSTEM enqueue (never the input-write one -- must not un-park anything).
RECONCILE_BATCH_SIZE = 5000

_RECONCILE_CANDIDATES_SQL = """
SELECT o.order_id
FROM ml_orders_ops o
LEFT JOIN ml_order_metrics m ON m.order_id = o.order_id
LEFT JOIN ml_order_metrics_dirty d ON d.order_id = o.order_id
WHERE d.order_id IS NULL
  AND (m.order_id IS NULL OR m.formula_version < :current_version)
ORDER BY o.order_id
LIMIT :limit
"""


class BatchTimeout(Exception):
    """Raised when a batch's COMPUTE phase exceeds `batch_timeout` wall
    time (design D5 "Batch wall-time bound"). Nobody in the batch is
    charged -- the batch is released uncharged and marked `suspect` so it
    is retried one order at a time, durably across a worker restart."""


def _is_singleton_retry(claims: List[Claim]) -> bool:
    """A batch of exactly one claim whose `attempts > 0` (or that was
    claimed via the singleton pass because it was `suspect`) is a
    process-killing-order isolation retry: its own failure is charged to
    it alone, never diffused across a batch (design D5 "Attempts rule")."""
    return len(claims) == 1


def _register_held_tokens(ctx: WorkerContext, claims: List[Claim]) -> None:
    if ctx.held_tokens is not None:
        for claim in claims:
            ctx.held_tokens.add(str(claim.claim_token))


def _unregister_held_tokens(ctx: WorkerContext, claims: List[Claim]) -> None:
    if ctx.held_tokens is not None:
        for claim in claims:
            ctx.held_tokens.discard(str(claim.claim_token))


def _compute_batch(claims: List[Claim], batch_deadline: datetime):
    """COMPUTE phase (design D5 rev 6): read-only, bulk, no row locks.
    Runs `compute_order_metrics` for the whole batch in one call.

    LIMITATION, stated plainly: `batch_deadline` is only checked BEFORE
    the call. Once the bulk compute starts, nothing interrupts it -- its
    only bound is the 30s `statement_timeout` PER STATEMENT, and the
    heartbeat keeps renewing the lease throughout. So design D5's batch
    WALL-TIME bound is NOT enforced during the compute; PR3.T6d is open,
    not done. What this guard does cover is a batch that is already past
    its budget when it gets here: it never starts (nothing was started,
    so there is nothing to charge)."""
    if datetime.now(timezone.utc) >= batch_deadline:
        raise BatchTimeout("batch_timeout exceeded before compute started")
    order_ids = [claim.order_id for claim in claims]
    with get_background_db() as db:
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
        metrics = compute_order_metrics(db, order_ids)
    return metrics


def _store_batch(claims: List[Claim], metrics, ctx: WorkerContext) -> int:
    """STORE phase (design D5 rev 6): one short transaction PER order.
    `ctx.deadline` reached mid-batch stops starting new stores; already
    stored orders stay committed, and only the UNSTORED ones are released
    uncharged and NOT suspect (their compute succeeded -- design D5 rev 6).
    An exception attributable to exactly one order (raised inside its own
    fenced store) charges only that order via `mark_failed`, never the
    rest of the batch."""
    stored = 0
    unstored: List[Claim] = []
    for claim in claims:
        if datetime.now(timezone.utc) >= ctx.deadline:
            unstored.append(claim)
            continue
        order_metrics = metrics.get(claim.order_id)
        if order_metrics is None:
            # The bulk compute returned nothing for this order (no
            # `ml_orders_ops` row is the reachable case, design D7's own
            # tolerance). This is CHARGED, not released uncharged: an
            # uncharged release puts the row back at `attempts = 0` and
            # not suspect, so the next `claim_dirty` of this same pass
            # claims it again immediately -- it never fails, never parks,
            # and the pass spins claim/compute/release against the
            # database until its deadline. Charging it lets the normal
            # attempts rule park it like any other order that cannot make
            # progress. A lost race is different and stays uncharged:
            # there, the recompute DID happen and another write simply won.
            logger.warning(
                "order_metrics.drain: compute returned no metrics for order_id=%s -- charging the attempt",
                claim.order_id,
            )
            mark_failed(claim, "no_metrics")
            _unregister_held_tokens(ctx, [claim])
            continue
        try:
            result = fenced_store([claim], {claim.order_id: order_metrics})
        except Exception as exc:  # noqa: BLE001 -- isolate to this order only
            logger.exception("order_metrics.drain: store failed for order_id=%s", claim.order_id)
            mark_failed(claim, str(exc)[:500])
            _unregister_held_tokens(ctx, [claim])
            continue
        _unregister_held_tokens(ctx, [claim])
        if result.stored_order_ids or result.unclaimed_order_ids:
            stored += 1
        elif result.not_owner_order_ids:
            pass  # lease already reclaimed elsewhere -- nothing to release
    if unstored:
        release_uncharged(unstored, suspect=False)
        _unregister_held_tokens(ctx, unstored)
    return stored


def _process_batch(claims: List[Claim], ctx: WorkerContext) -> int:
    batch_deadline = min(
        ctx.deadline, datetime.now(timezone.utc) + timedelta(seconds=settings.WORKER_BATCH_TIMEOUT_SECONDS)
    )
    try:
        metrics = _compute_batch(claims, batch_deadline)
    except BatchTimeout:
        # WHOSE clock ran out decides what this costs. The handler's own
        # `ctx.deadline` expiring between the claim and the compute says
        # nothing about these orders: the compute never started, so they
        # are released uncharged and NOT suspect -- marking them would
        # condemn healthy orders to the singleton pass, and charging a
        # lone one `timeout` would blame it for a deadline that was not
        # its fault. Only the batch's own wall-clock budget running out
        # is evidence about the batch itself.
        if datetime.now(timezone.utc) >= ctx.deadline:
            logger.info(
                "order_metrics.drain: handler deadline reached before compute -- releasing %d claim(s) uncharged",
                len(claims),
            )
            release_uncharged(claims, suspect=False)
        elif _is_singleton_retry(claims):
            mark_failed(claims[0], "timeout")
        else:
            release_uncharged(claims, suspect=True)
        _unregister_held_tokens(ctx, claims)
        return 0
    except Exception as exc:  # noqa: BLE001 -- bulk compute failure not attributable to one order
        logger.exception("order_metrics.drain: bulk compute failed for a batch of %d", len(claims))
        if _is_singleton_retry(claims):
            mark_failed(claims[0], str(exc)[:500])
        else:
            release_uncharged(claims, suspect=True)
        _unregister_held_tokens(ctx, claims)
        return 0

    return _store_batch(claims, metrics, ctx)


class OrderMetricsDrainHandler:
    """`JobHandler` (design D6) for `order_metrics.drain`."""

    name = "order_metrics.drain"
    channels: Tuple[str, ...] = ("order_metrics_dirty",)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        total_processed = 0
        batches_run = 0
        while datetime.now(timezone.utc) < ctx.deadline:
            claims = claim_dirty(
                limit=settings.WORKER_BATCH_SIZE,
                lease=timedelta(seconds=settings.WORKER_LEASE_SECONDS),
                worker_id=ctx.worker_name,
            )
            if not claims:
                break
            _register_held_tokens(ctx, claims)
            try:
                total_processed += _process_batch(claims, ctx)
            finally:
                # Unconditional: a token left behind is renewed by the
                # heartbeat for the life of the process, so its row never
                # ages into the lease-expiry charge and never becomes
                # claimable again (`claim_dirty` only takes rows with
                # `claimed_at IS NULL`) -- that order would be stuck for
                # good. The paths inside the batch already unregister what
                # they handle; this only sweeps what an exception skipped,
                # and unregistering twice is a no-op (discard on a set).
                _unregister_held_tokens(ctx, claims)
            batches_run += 1
        return JobResult(success=True, detail={"processed": total_processed, "batches": batches_run})


drain = OrderMetricsDrainHandler()


class OrderMetricsReconcileHandler:
    """`JobHandler` (design D10) for `order_metrics.reconcile`. Schedule-only
    (`channels=()`), every 10 minutes: finds orders with no `ml_order_metrics`
    row, or `formula_version < CURRENT_FORMULA_VERSION`, that have no dirty
    row yet, and enqueues them in batches of `RECONCILE_BATCH_SIZE` via
    `order_metrics_enqueue_system` -- never `order_metrics_enqueue`, so an
    already-dirty row (including a parked one) is left completely
    untouched (ON CONFLICT DO NOTHING, PR4). This IS the backfill: the
    first run after this handler is deployed sweeps the whole pre-existing
    backlog into the queue, throttled by the drain handler's own batch
    pace -- no manual script, no cron (design D10)."""

    name = "order_metrics.reconcile"
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=10)
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        total_enqueued = 0
        batches = 0
        while datetime.now(timezone.utc) < ctx.deadline:
            with get_background_db() as db:
                rows = db.execute(
                    text(_RECONCILE_CANDIDATES_SQL),
                    {"current_version": CURRENT_FORMULA_VERSION, "limit": RECONCILE_BATCH_SIZE},
                ).fetchall()
                order_ids = [row[0] for row in rows]
                if order_ids:
                    db.execute(
                        text("SELECT order_metrics_enqueue_system(CAST(:ids AS bigint[]), 'reconcile')"),
                        {"ids": order_ids},
                    )
            if not order_ids:
                break
            total_enqueued += len(order_ids)
            batches += 1
            if len(order_ids) < RECONCILE_BATCH_SIZE:
                break
        return JobResult(success=True, detail={"enqueued": total_enqueued, "batches": batches})


reconcile = OrderMetricsReconcileHandler()

# design D10: divergence runs in batches of 500, records at most this many
# `ml_ops_divergence` rows per run (the health endpoint only needs enough
# ids to be actionable, not an unbounded write burst against a table that
# can already be large).
DIVERGENCE_BATCH_SIZE = 500
DIVERGENCE_MAX_RECORDED_PER_RUN = 100

_DIVERGENCE_CANDIDATES_SQL = """
SELECT m.order_id, m.neto, m.neto_sin_iva, m.iva_reconcilia, m.costo_mercaderia,
       m.total_gauss, m.markup_pct, m.gauss_status, m.formula_version
FROM ml_order_metrics m
LEFT JOIN ml_order_metrics_dirty d ON d.order_id = m.order_id
WHERE d.order_id IS NULL AND m.order_id > :last_order_id
ORDER BY m.order_id
LIMIT :limit
"""


def _stored_metrics_diverges(stored_row, fresh) -> bool:
    """Compares every stored field + status + formula_version against a
    freshly computed `OrderMetrics` (design D10). Decimal columns come back
    from the driver as `Decimal`; `OrderMetrics` also carries `Decimal` (or
    `None`), so a plain `!=` is exact -- no float tolerance needed, same
    discipline the rest of this module already uses for money."""
    return (
        stored_row.neto != fresh.neto
        or stored_row.neto_sin_iva != fresh.neto_sin_iva
        or bool(stored_row.iva_reconcilia) != bool(fresh.iva_reconcilia)
        or stored_row.costo_mercaderia != fresh.costo_mercaderia
        or stored_row.total_gauss != fresh.total_gauss
        or stored_row.markup_pct != fresh.markup_pct
        or stored_row.gauss_status != fresh.gauss_status.value
        or stored_row.formula_version != fresh.formula_version
    )


def _open_divergence_record(db, order_id: int) -> None:
    """Inserts one `ml_ops_divergence` row (`kind='stored_metrics_mismatch'`,
    design D10, reusing `ml_orders_ops.py:463`'s model) -- idempotent across
    runs via the table's own `uq_ml_ops_divergence_order_kind_field`
    (`order_id`, `kind`, `field`, `field IS NULL`) unique constraint, so a
    still-open divergence found again tomorrow does not duplicate."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.ml_orders_ops import MlOpsDivergence

    stmt = pg_insert(MlOpsDivergence.__table__).values(
        order_id=order_id,
        kind="stored_metrics_mismatch",
        field=None,
        state="open",
    )
    db.execute(stmt.on_conflict_do_nothing(index_elements=["order_id", "kind", "field"]))


def _write_divergence_summary(detail: dict) -> None:
    """Writes the run summary to `worker_job_state.detail` (design D10) --
    NOT via `WorkerRuntime._record_job_run` (which only ever touches
    `last_run_at`/`last_success_at`), a dedicated upsert scoped to this
    handler's own row."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.worker_job_state import WorkerJobState

    with get_background_db() as db:
        stmt = pg_insert(WorkerJobState.__table__).values(name="order_metrics.divergence", detail=detail)
        db.execute(stmt.on_conflict_do_update(index_elements=["name"], set_={"detail": stmt.excluded.detail}))


class OrderMetricsDivergenceHandler:
    """`JobHandler` (design D10) for `order_metrics.divergence`. Daily at
    04:00 America/Argentina/Buenos_Aires, batches of 500: compares every
    stored `ml_order_metrics` field + status + formula_version against a
    fresh `compute_order_metrics`, skipping orders that currently have a
    dirty row (mid-flight -- a mismatch there is expected, not a bug).
    Divergent orders open (or keep open) a `ml_ops_divergence` row and are
    re-enqueued via the system enqueue (self-heal, still visible -- never
    silently patched in place)."""

    name = "order_metrics.divergence"
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = time(4, 0)

    def run(self, ctx: WorkerContext) -> JobResult:
        divergent_count = 0
        missing_count = 0
        checked_count = 0
        recorded = 0
        last_order_id = 0
        started_at = datetime.now(timezone.utc)

        while datetime.now(timezone.utc) < ctx.deadline:
            with get_background_db() as db:
                rows = db.execute(
                    text(_DIVERGENCE_CANDIDATES_SQL),
                    {"last_order_id": last_order_id, "limit": DIVERGENCE_BATCH_SIZE},
                ).fetchall()
                if not rows:
                    break

                order_ids = [row.order_id for row in rows]
                fresh_by_order = compute_order_metrics(db, order_ids)

                divergent_ids: List[int] = []
                for row in rows:
                    fresh = fresh_by_order.get(row.order_id)
                    if fresh is None:
                        missing_count += 1
                        continue
                    if _stored_metrics_diverges(row, fresh):
                        divergent_ids.append(row.order_id)

                if divergent_ids:
                    remaining_slots = max(0, DIVERGENCE_MAX_RECORDED_PER_RUN - recorded)
                    for order_id in divergent_ids[:remaining_slots]:
                        _open_divergence_record(db, order_id)
                    recorded += min(len(divergent_ids), remaining_slots)
                    db.execute(
                        text("SELECT order_metrics_enqueue_system(CAST(:ids AS bigint[]), 'divergence')"),
                        {"ids": divergent_ids},
                    )

                divergent_count += len(divergent_ids)
                checked_count += len(order_ids)
                last_order_id = order_ids[-1]

            if len(rows) < DIVERGENCE_BATCH_SIZE:
                break

        summary = {
            "run_at": started_at.isoformat(),
            "divergent_count": divergent_count,
            "missing_count": missing_count,
            "checked_count": checked_count,
        }
        _write_divergence_summary(summary)
        return JobResult(success=True, detail=summary)


divergence = OrderMetricsDivergenceHandler()
