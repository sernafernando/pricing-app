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

from app.core.config import settings
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.queue import Claim, claim_dirty, fenced_store, mark_failed, release_uncharged
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)


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
    Runs `compute_order_metrics` for the whole batch in one call; the
    wall-clock budget is enforced by the caller checking `batch_deadline`
    immediately before starting this call -- a batch already past its
    budget never starts computing (nothing to charge, nothing was
    started)."""
    if datetime.now(timezone.utc) >= batch_deadline:
        raise BatchTimeout("batch_timeout exceeded before compute started")
    from app.core.database import get_background_db

    from sqlalchemy import text

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
        if _is_singleton_retry(claims):
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
