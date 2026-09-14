"""Cron entry point for the ML activity drain (slice 4 of
ml-activity-receiver).

Runs `activity_receiver_service.drain_activity()`, the same function the
`POST /api/ml-ventas-ops/activity/ping` endpoint schedules. It is a
complete no-op (zero HTTP calls, zero DB writes) while
`ML_ORDERS_OPS_ENABLED` is False -- this script adds no logic on top of
that gate, so it stays a no-op too.

WHY A CRON AT ALL, when the whole point of this feature was to stop
depending on them: the ping is the alarm clock, not the transport. The
stored cursor guarantees no event is ever LOST, but it cannot guarantee
one arrives on TIME -- "a lost ping is recovered by the next one" only
holds if there IS a next one. A ping dropped on a quiet Saturday night is
not recovered until somebody buys something, which may be hours. This
pass is the floor under that: it costs one HTTP call when the feed is
empty, and it is the only thing standing between a broken ping and a
sales view that silently stops updating.

It also carries the first-run catch-up. The bridge holds a backlog
measured in thousands of events, and one pass resolves at most
`MAX_ACTIVITY_ORDER_FETCHES_PER_PASS` orders, so the initial drain needs
several passes. Waiting for enough pings to arrive to work through that
backlog would leave the view stale for as long as the backlog lasts.

Concurrency with the ping is already handled and needs nothing here:
`drain_activity` takes the run lock for its own `CURSOR_NAME`, so a pass
that starts while another is in flight sees the lock and returns without
running. Two overlapping runs cannot corrupt the cursor.

Run:
    python -m app.scripts.drain_ml_activity
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from app.services.ml_orders_ingestion.activity_receiver_service import drain_activity  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = drain_activity()
    if not result.ran:
        # Three different facts hide behind `ran=False`: the flag is off,
        # another pass holds the lock, or something was misconfigured.
        # Collapsing them sends whoever reads this log looking at the
        # wrong thing.
        reason = result.error or "flag off, or another pass holds the run lock"
        logger.info("drain_ml_activity: drain did not run (%s)", reason)
        return
    if result.error:
        logger.error("drain_ml_activity: drain failed: %s", result.error)
        return
    # A pass that ran out of order-fetch budget walked only part of the
    # feed; calling that "complete" is how a partial drain passes for a
    # finished one.
    outcome = "drain stopped early (order fetch budget)" if result.budget_exhausted else "drain complete"
    logger.info(
        "drain_ml_activity: %s — pages=%s advanced=%s events=%s without_order_id=%s "
        "resolved=%s unresolved=%s not_attempted=%s | upserted=%s stale=%s "
        "mapping_error=%s out_of_window=%s write_error=%s | quarantine_recovered=%s "
        "quarantine_still_failed=%s",
        outcome,
        result.pages_walked,
        result.pages_advanced,
        result.events_seen,
        result.events_without_order_id,
        result.orders_resolved,
        result.orders_unresolved,
        result.orders_not_attempted,
        result.orders_upserted,
        result.orders_skipped_stale,
        result.orders_mapping_error,
        result.orders_out_of_window,
        result.orders_write_error,
        result.orders_quarantine_recovered,
        result.orders_quarantine_still_failed,
    )
    if result.orders_write_error:
        # A quarantined order does not vanish quietly -- it must GRIT its
        # order_id, not just sum into a counter nobody reads. The order
        # itself carries the error on `ml_orders_ops_cuarentena.error` and
        # on the `ingest_failed` divergence dashboard row.
        logger.error(
            "drain_ml_activity: %s order(s) failed to WRITE this pass and were quarantined for "
            "automatic retry — see ml_orders_ops_cuarentena / GET /ml-ventas-ops/divergences?kind=ingest_failed",
            result.orders_write_error,
        )
    # `resolved` only means ML answered. A pass that resolved orders and
    # wrote none of them is a broken pass wearing a healthy log line --
    # exactly how a field-name mismatch went unnoticed for a week.
    #
    # But two outcomes explain a write that never happened WITHOUT
    # anything being wrong: an order we already have at that version
    # (stale) and one the rolling window excludes by design. Alarming on
    # those turns a real signal into routine noise, and routine noise is
    # how the next real signal gets ignored. So the alarm is what NOTHING
    # accounts for -- today that is mapping errors, and by construction it
    # also catches whatever silently drops orders next.
    # `orders_write_error` counts as ACCOUNTED FOR. A write error is not a
    # silent disappearance: the order sits in quarantine, it has a row in
    # the divergences board, it logged its own error above, and the next
    # pass retries it. Leaving it out of this subtraction made every
    # quarantined order ALSO fire "written NOWHERE and no outcome accounts
    # for them" -- which is false, and is precisely the routine noise the
    # comment above warns turns a real signal into one nobody reads.
    unaccounted = result.orders_resolved - (
        result.orders_upserted + result.orders_skipped_stale + result.orders_out_of_window + result.orders_write_error
    )
    if unaccounted > 0:
        logger.error(
            "drain_ml_activity: %s of %s order(s) fetched from ML were written NOWHERE and no "
            "outcome accounts for them (upserted=%s stale=%s out_of_window=%s write_error=%s "
            "mapping_error=%s) — "
            "the drain is running but not ingesting",
            unaccounted,
            result.orders_resolved,
            result.orders_upserted,
            result.orders_skipped_stale,
            result.orders_out_of_window,
            result.orders_write_error,
            result.orders_mapping_error,
        )


if __name__ == "__main__":
    main()
