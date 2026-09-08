"""Historical backfill for payments and shipment costs
(ml-backfill-pagos-y-costos).

The sweep (`sweep_service.run_sweep`) only ever looks at orders/shipments
it fetched during THIS pass -- windowed by `date_last_updated`. An order
(or shipment) whose ML side has not been touched since before that
window's floor never re-enters a sweep pass, so `payments_synced_at` /
`costs_synced_at` stay NULL forever and the listing shows Neto `--` for
that sale permanently. Slices 5/6 (obs #1966) are already in production
against the STEADY STATE going forward; this backfill is what makes the
pre-existing history stop showing `--`.

This walks the BASE tables directly for whatever still has
`payments_synced_at IS NULL` / `costs_synced_at IS NULL` -- the exact
same retry gates the sweep already uses -- instead of being limited to
one sweep pass's window. Fetch, mapping, and sealing are the SAME
functions the sweep calls (`sweep_service.sync_payments_for_order`,
`sweep_service._sync_shipment_costs`); this module only supplies a
different SOURCE of candidates, so the sealing rule that decides whether
a sale's money is trustworthy lives in exactly one place, never two that
could drift (obs #1965/#1966 lesson). `sync_payments_for_order` itself
now refuses to seal an order whose `raw_order` never even has the
`payments` key (post-review BLOCKING fix): unlike the sweep's raw order
(fresh off the ML API, where the key's absence is a real fact), this
backfill's `raw_order` comes back out of storage -- written by whatever
ingestion version was running at the time -- so an absent key here can
just as easily mean "an older, incomplete write" as "no payments". A
false seal on that ambiguity would be permanent: `payments_synced_at IS
NULL` is the ONLY retry gate, so the order would never become a
candidate again, and the `--` this script exists to remove would become
one it wrote itself.

Ordering: NEWEST candidates first (`date_created DESC` /
`shipment_id DESC`, the closest available proxy for shipment recency).
An operator watching the listing cares about recent sales; oldest-first
would spend the entire backlog on months-old history before ever
touching what is currently on screen.

Own run lock, own cursor: `ml_ops_sync_cursor.name='backfill_payments_costs'`,
separate from both the sweep's (`'sweep'`) and the orders backfill's
(`'backfill'`, `backfill_service.py`). Reusing the SWEEP's own lock would
serialize this backfill behind the sweep's 10-minute cadence for no
reason -- the sweep's write to these two columns IS the same sealing
function this backfill also calls, so overlap between the two is a
structural no-op via the shared `costs_synced_at`/`payments_synced_at IS
NULL` gate, exactly like the orders backfill's overlap with the sweep
(see `try_acquire_run_lock`'s docstring). A distinct lock only prevents
two COPIES of this exact backfill from racing each other and double-
fetching the same candidates.

Network budget: reuses the sweep's own `MAX_PAYMENT_FETCHES_PER_PASS` /
`MAX_COST_FETCHES_PER_PASS` constants unchanged (no new budget invented).
The payments endpoint has no measured rate limit (514 fetched back-to-
back, zero 429s -- obs #1966); the constant exists for pass-shape
symmetry, not because ML throttles it. `--limit` bounds how many DB
candidates a single invocation pulls, which is the resumability knob: a
run resolves and seals a bounded slice, and the NEXT run finds a smaller
NULL-set because sealed rows drop out of the query -- no cursor/offset
bookkeeping needed for that part. `--limit` set well above either fetch
budget silently truncates a pass mid-way (one candidate order can carry
several payment ids): `BackfillPaymentsCostsResult.payments_budget_exhausted`
/ `.costs_budget_exhausted` surface that instead of leaving an operator
staring at `order_candidates=1000 orders_sealed=380` with no explanation.

`--dry-run` performs two bounded COUNT queries ONLY -- neither reads
`raw_order` (which can be several KB of JSONB per row) -- and nothing
else: zero HTTP calls, zero writes, no lock taken.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.services.ml_orders_ingestion.sweep_service import (
    CURSOR_NAME as SWEEP_CURSOR_NAME,
    MAX_COST_FETCHES_PER_PASS,
    MAX_PAYMENT_FETCHES_PER_PASS,
    _fetch_payments,
    _sync_shipment_costs,
    release_lock_as_error,
    release_lock_as_idle,
    sync_payments_for_order,
    try_acquire_run_lock,
)

logger = logging.getLogger(__name__)

CURSOR_NAME = "backfill_payments_costs"

# Never reused by anything else: guards against a future refactor
# accidentally pointing this backfill at the sweep's own row (same
# discipline as `backfill_service.py`'s own guard). A plain `assert` is
# stripped under `python -O`; fail loudly and unconditionally instead.
if CURSOR_NAME == SWEEP_CURSOR_NAME:
    raise RuntimeError("backfill_payments_costs_service.CURSOR_NAME must not collide with the sweep's own cursor name")

# An operator-invoked, network-bound run, bounded by `--limit` -- expected
# to take at most a few minutes even at the default limit, since neither
# endpoint touched here is rate-limited. Well above that so a genuinely
# dead process is reclaimed within a business day, mirroring the orders
# backfill's own (12h) reasoning at a smaller scale appropriate to this
# job's much shorter expected runtime.
STALE_LOCK_TIMEOUT = timedelta(hours=2)

DEFAULT_LIMIT = 500

# The reason a run did not happen at all, distinguished so the CLI can
# tell a genuine no-op (the flag is off -- exit 0, same discipline as
# `backfill_ml_orders_ops.py`/`backfill_service.py`) apart from a real
# failure (another run is in flight -- exit 1).
FLAG_OFF_REASON = "ML_ORDERS_OPS_ENABLED is False"


@dataclass
class BackfillPaymentsCostsResult:
    ran: bool
    dry_run: bool = False
    order_candidates: int = 0
    payments_synced: int = 0
    orders_sealed: int = 0
    payments_budget_exhausted: bool = False
    shipment_candidates: int = 0
    shipment_costs_synced: int = 0
    costs_budget_exhausted: bool = False
    error: Optional[str] = None


def _orders_needing_payments(limit: int) -> List[Tuple[int, Optional[Dict[str, Any]]]]:
    """Orders with `payments_synced_at IS NULL`, NEWEST `date_created`
    first (see module docstring) so a bounded run reaches what an
    operator is actually looking at before it reaches six-month-old
    history. Reads `raw_order` (the exact payload `order.payments[].id`
    is extracted from) and detaches before the session closes."""
    with get_background_db() as db:
        rows = (
            db.query(MlOrdersOps.order_id, MlOrdersOps.raw_order)
            .filter(MlOrdersOps.payments_synced_at.is_(None))
            .order_by(MlOrdersOps.date_created.desc())
            .limit(limit)
            .all()
        )
        return [(order_id, raw_order) for order_id, raw_order in rows]


def _count_orders_needing_payments(limit: int) -> int:
    """The `--dry-run` counterpart of `_orders_needing_payments`: same
    filter and cap, but selects only `order_id` (never `raw_order`) so a
    preview never materializes JSONB it will only throw away."""
    with get_background_db() as db:
        return (
            db.query(MlOrdersOps.order_id)
            .filter(MlOrdersOps.payments_synced_at.is_(None))
            .order_by(MlOrdersOps.date_created.desc())
            .limit(limit)
            .count()
        )


def _shipments_needing_costs(limit: int) -> List[int]:
    """Shipments with `costs_synced_at IS NULL`, NEWEST `shipment_id`
    first (the closest available proxy for recency: `MlShipmentOps` has
    no reliably-populated `date_created` across every ingestion path),
    for the same reason as `_orders_needing_payments`."""
    with get_background_db() as db:
        rows = (
            db.query(MlShipmentOps.shipment_id)
            .filter(MlShipmentOps.costs_synced_at.is_(None))
            .order_by(MlShipmentOps.shipment_id.desc())
            .limit(limit)
            .all()
        )
        return [shipment_id for (shipment_id,) in rows]


def _count_shipments_needing_costs(limit: int) -> int:
    """The `--dry-run` counterpart of `_shipments_needing_costs`."""
    with get_background_db() as db:
        return (
            db.query(MlShipmentOps.shipment_id)
            .filter(MlShipmentOps.costs_synced_at.is_(None))
            .order_by(MlShipmentOps.shipment_id.desc())
            .limit(limit)
            .count()
        )


def run_backfill(limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> BackfillPaymentsCostsResult:
    """Entry point for `app/scripts/backfill_ml_payments_costs.py`.

    Flag-gated exactly like the sweep and the orders backfill: a complete
    no-op (zero HTTP calls, zero DB writes) while `ML_ORDERS_OPS_ENABLED`
    is False -- and `error` stays `None` in that case (post-review fix):
    the flag being off is a genuine, expected outcome, not a failure a
    chained/scripted invocation should read as one.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        logger.info("backfill_ml_payments_costs: did not run (%s)", FLAG_OFF_REASON)
        return BackfillPaymentsCostsResult(ran=False, dry_run=dry_run)

    if dry_run:
        # No lock, no HTTP, no writes, no `raw_order` materialization --
        # see module docstring.
        order_count = _count_orders_needing_payments(limit)
        shipment_count = _count_shipments_needing_costs(limit)
        logger.info(
            "backfill_ml_payments_costs(dry-run): %d order(s) missing payments, %d shipment(s) missing costs "
            "(limit=%d) -- no writes performed",
            order_count,
            shipment_count,
            limit,
        )
        return BackfillPaymentsCostsResult(
            ran=True,
            dry_run=True,
            order_candidates=order_count,
            shipment_candidates=shipment_count,
        )

    now = datetime.now(timezone.utc)
    with get_background_db() as db:
        acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME, stale_timeout=STALE_LOCK_TIMEOUT)
    if not acquired:
        logger.info("backfill_ml_payments_costs: another run is already in flight, skipping this pass")
        return BackfillPaymentsCostsResult(ran=False, error="already running")

    order_candidates = _orders_needing_payments(limit)
    shipment_ids = _shipments_needing_costs(limit)

    result = BackfillPaymentsCostsResult(
        ran=True, order_candidates=len(order_candidates), shipment_candidates=len(shipment_ids)
    )
    failure: Optional[BaseException] = None
    try:
        # HTTP-before-write discipline (design D8, same as the sweep):
        # every payment this run will need is fetched BEFORE any DB
        # session opens for the write below. Orders with no stored
        # `raw_order` (should not happen once ingestion is the writer of
        # record, but a defensive default) contribute no payment ids and
        # are left unsealed by `sync_payments_for_order` itself -- never
        # sealed on missing information (see module docstring).
        raw_orders = [raw for _, raw in order_candidates if isinstance(raw, dict)]
        # An explicit budget list (rather than the functions' own
        # `None`-default) so its remaining value after the call tells us
        # whether `--limit` outran the fetch budget (finding 3): a
        # candidate count alone can't distinguish "every candidate
        # resolved" from "the budget ran out first".
        payment_budget = [MAX_PAYMENT_FETCHES_PER_PASS]
        payments_payload = _fetch_payments(raw_orders, payment_budget)
        result.payments_budget_exhausted = payment_budget[0] <= 0

        with get_background_db() as db:
            for order_id, raw_order in order_candidates:
                if not isinstance(raw_order, dict):
                    logger.warning(
                        "backfill_ml_payments_costs: order_id=%s has no stored raw_order payload; "
                        "cannot resolve its payments",
                        order_id,
                    )
                    continue
                synced, sealed = sync_payments_for_order(db, order_id, raw_order, payments_payload)
                result.payments_synced += synced
                if sealed:
                    result.orders_sealed += 1

        cost_budget = [MAX_COST_FETCHES_PER_PASS]
        result.shipment_costs_synced = _sync_shipment_costs(shipment_ids, cost_budget)
        result.costs_budget_exhausted = cost_budget[0] <= 0
    except Exception as e:  # noqa: BLE001
        # Same structural guarantee as the sweep/orders-backfill (obs
        # #1852 lesson 1): whatever happens above, the lock release below
        # always runs.
        logger.exception("backfill_ml_payments_costs: failed unexpectedly, releasing the run lock")
        failure = e
        result.error = f"{type(e).__name__}: {e}"
    finally:
        if failure is not None:
            release_lock_as_error(failure, cursor_name=CURSOR_NAME)
        else:
            release_lock_as_idle(now, complete=True, cursor_name=CURSOR_NAME)

    if result.payments_budget_exhausted:
        logger.warning(
            "backfill_ml_payments_costs: payment fetch budget (%d) exhausted before every candidate resolved; "
            "the next run picks up the rest",
            MAX_PAYMENT_FETCHES_PER_PASS,
        )
    if result.costs_budget_exhausted:
        logger.warning(
            "backfill_ml_payments_costs: cost fetch budget (%d) exhausted before every candidate resolved; "
            "the next run picks up the rest",
            MAX_COST_FETCHES_PER_PASS,
        )

    return result
