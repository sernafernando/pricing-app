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
could drift (obs #1965/#1966 lesson).

AMBIGUOUS STORED ROWS: a stored
`raw_order` with no `payments` key at all is not guaranteed fresh from
ML -- it may be an older, incomplete ingestion write -- so
`sync_payments_for_order` refuses to seal it on that alone (see its own
docstring). The first version of this fix stopped there, which created a
WORSE bug than the one it closed: this backfill never re-asks ML for
anything, so the exact same ambiguous rows kept being reselected by
`_orders_needing_payments`, forever, in the same order -- `--limit`
never-progressing candidates blocking every order genuinely behind them.
The fix has two parts:
  1. Any candidate whose stored `raw_order` lacks the `payments` key is
     refetched fresh via `get_order` BEFORE the write session opens
     (same HTTP-before-write discipline as the payment fetch itself). A
     fresh payload is now a trustworthy source, so it is passed to
     `sync_payments_for_order` with `missing_key_is_empty=True` -- if ML
     STILL omits the key, that omission is now ML's own answer and
     sealing is correct.
  2. A refetch that itself fails (network/proxy error, no live
     `raw_order` returned) leaves that order out of this run entirely --
     genuinely unresolved, retried again next run, same fail-open
     discipline as everything else on this path.

SHIPMENT COSTS -- the same stuck-candidate risk, plus wasted network
`_sync_shipment_costs` never seals a
shipment on a partial `get_shipment_costs` payload (design decision,
`sweep_service.py`), so a shipment ML never fully settles would sit at
the head of `shipment_id DESC` forever, spending one real HTTP fetch on
it every single run while blocking every shipment behind it. Attempts
are counted in `ml_ops_divergence` (`kind='unknown'`,
`field='cost_sync:<shipment_id>'`, `order_id=0` sentinel, same pattern
`sweep_service.record_unenumerable_window` already uses for a leaf that
cannot be enumerated); once `MAX_COST_SYNC_ATTEMPTS` is reached, that
shipment is excluded from future candidate queries -- visible in the
existing divergence dashboard, never silently dropped, never spending
budget on it again.

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
These flags are computed from ACTUAL
resolution counts (resolved < needed AND the budget list hit zero), not
from `budget[0] <= 0` alone -- exactly hitting the budget with every
single candidate resolved is a complete pass, not a truncated one, and
the old check reported it as truncated.

`release_lock_as_idle`'s `complete` flag
mirrors the sweep's own reasoning (`complete=not result.budget_exhausted`)
-- a run that stopped early on either budget is NOT stamped as a
completed pass, so a staleness alert on "no success in N minutes" still
fires while this backfill keeps truncating.

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
from app.models.ml_orders_ops import (
    COST_SYNC_FIELD_PREFIX,
    COST_SYNC_KIND,
    COST_SYNC_SENTINEL_ORDER_ID,
    MlOpsDivergence,
    MlOrdersOps,
    MlShipmentOps,
)
from app.services.ml_orders_ingestion.sweep_service import (
    CURSOR_NAME as SWEEP_CURSOR_NAME,
    MAX_COST_FETCHES_PER_PASS,
    MAX_PAYMENT_FETCHES_PER_PASS,
    _extract_payment_ids,
    _fetch_payments,
    _record_payments_key_missing,
    _sync_shipment_costs,
    release_lock_as_error,
    release_lock_as_idle,
    sync_payments_for_order,
    try_acquire_run_lock,
)
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

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

# A shipment whose cost sync never fully resolves (ML never settles it,
# or its payload is always partial) after this many BACKFILL attempts is
# excluded from future candidate queries -- see module docstring.
MAX_COST_SYNC_ATTEMPTS = 5

_COST_SYNC_DIVERGENCE_KIND = COST_SYNC_KIND
_COST_SYNC_FIELD_PREFIX = COST_SYNC_FIELD_PREFIX
# Sentinel `order_id`, same convention as
# `sweep_service.record_unenumerable_window`: there is no single ML
# order this divergence is "about", it is about a shipment.
_COST_SYNC_SENTINEL_ORDER_ID = COST_SYNC_SENTINEL_ORDER_ID


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
    shipments_gave_up: int = 0
    error: Optional[str] = None


def _cost_sync_field(shipment_id: int) -> str:
    return f"{_COST_SYNC_FIELD_PREFIX}{shipment_id}"


def _gave_up_shipment_ids(db) -> set:
    """Shipment ids whose cost sync has already been attempted
    `MAX_COST_SYNC_ATTEMPTS` times without resolving -- excluded from
    future candidate queries (module docstring).

    The give-up test lives in the
    WHERE clause, not in Python. `_record_cost_sync_attempt` clamps the
    counter at `MAX_COST_SYNC_ATTEMPTS`, so "gave up" is one exact
    stored value and this reads only the rows it actually needs --
    previously it pulled every `cost_sync:%` row, in-progress ones
    included, and filtered them in the process.

    # ponytail: the returned set still has no ceiling of its own, and it
    # goes on to feed a `NOT IN (...)`. Bounded by the number of
    # shipments ML never settles, which we expect to stay small; if it
    # ever does not, this belongs in a column on `ml_shipments_ops`
    # rather than in the divergence table.
    """
    rows = (
        db.query(MlOpsDivergence.field)
        .filter(
            MlOpsDivergence.order_id == _COST_SYNC_SENTINEL_ORDER_ID,
            MlOpsDivergence.kind == _COST_SYNC_DIVERGENCE_KIND,
            MlOpsDivergence.field.like(f"{_COST_SYNC_FIELD_PREFIX}%"),
            MlOpsDivergence.ml_value == str(MAX_COST_SYNC_ATTEMPTS),
        )
        .all()
    )
    given_up = set()
    for (field,) in rows:
        try:
            given_up.add(int(field[len(_COST_SYNC_FIELD_PREFIX) :]))
        except ValueError:
            continue
    return given_up


def _clear_cost_sync_attempts(db, shipment_ids) -> None:
    """Drops the give-up counters of shipments that resolved. The counter
    stands for a streak of runs that ended without a cost, so a single
    success ends the streak -- keeping it would spend a later stall's
    attempts before that stall ever began."""
    if not shipment_ids:
        return
    fields = [_cost_sync_field(shipment_id) for shipment_id in shipment_ids]
    db.query(MlOpsDivergence).filter(
        MlOpsDivergence.order_id == _COST_SYNC_SENTINEL_ORDER_ID,
        MlOpsDivergence.kind == _COST_SYNC_DIVERGENCE_KIND,
        MlOpsDivergence.field.in_(fields),
    ).delete(synchronize_session=False)


def _record_cost_sync_attempt(db, shipment_id: int) -> int:
    """Increments (creating if needed) the attempt counter for a shipment
    whose cost sync did not fully resolve this run. Returns the new
    count, CLAMPED at `MAX_COST_SYNC_ATTEMPTS` so that "gave up" is a
    single exact stored value `_gave_up_shipment_ids` can filter on in
    SQL. Dedup via the `(order_id, kind, field)` unique constraint, same
    as `record_unenumerable_window`."""
    field = _cost_sync_field(shipment_id)
    existing = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == _COST_SYNC_SENTINEL_ORDER_ID,
            MlOpsDivergence.kind == _COST_SYNC_DIVERGENCE_KIND,
            MlOpsDivergence.field == field,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        try:
            attempts = min(int(existing.ml_value or "0") + 1, MAX_COST_SYNC_ATTEMPTS)
        except ValueError:
            attempts = 1
        existing.ml_value = str(attempts)
        existing.detected_at = now
        return attempts
    db.add(
        MlOpsDivergence(
            order_id=_COST_SYNC_SENTINEL_ORDER_ID,
            kind=_COST_SYNC_DIVERGENCE_KIND,
            field=field,
            ml_value="1",
            detected_at=now,
        )
    )
    return 1


def _orders_newest_first():
    """The candidate ordering, defined once for the real query and its
    `--dry-run` counterpart so the two can never drift.

    `NULLS LAST` is not decoration: Postgres defaults `ORDER BY x DESC`
    to NULLS FIRST, so a row whose `date_created` was never persisted --
    plausible in exactly the legacy population this backfill exists to
    repair -- would head every single run instead of the newest sale.
    SQLite (the test database) orders NULLs last either way, so this is
    asserted against the compiled SQL rather than by behaviour.
    """
    return MlOrdersOps.date_created.desc().nullslast()


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
            .order_by(_orders_newest_first())
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
            .order_by(_orders_newest_first())
            .limit(limit)
            .count()
        )


def _shipments_needing_costs(limit: int) -> List[int]:
    """Shipments with `costs_synced_at IS NULL`, NEWEST `shipment_id`
    first (the closest available proxy for recency: `MlShipmentOps` has
    no reliably-populated `date_created` across every ingestion path),
    excluding any shipment that already gave up (module docstring), for
    the same reason as `_orders_needing_payments`."""
    with get_background_db() as db:
        given_up = _gave_up_shipment_ids(db)
        query = db.query(MlShipmentOps.shipment_id).filter(MlShipmentOps.costs_synced_at.is_(None))
        if given_up:
            query = query.filter(~MlShipmentOps.shipment_id.in_(given_up))
        rows = query.order_by(MlShipmentOps.shipment_id.desc()).limit(limit).all()
        return [shipment_id for (shipment_id,) in rows]


def _count_shipments_needing_costs(limit: int) -> int:
    """The `--dry-run` counterpart of `_shipments_needing_costs`."""
    with get_background_db() as db:
        given_up = _gave_up_shipment_ids(db)
        query = db.query(MlShipmentOps.shipment_id).filter(MlShipmentOps.costs_synced_at.is_(None))
        if given_up:
            query = query.filter(~MlShipmentOps.shipment_id.in_(given_up))
        return query.order_by(MlShipmentOps.shipment_id.desc()).limit(limit).count()


def _resolve_ambiguous_orders(
    order_candidates: List[Tuple[int, Optional[Dict[str, Any]]]],
    budget: List[int],
) -> Tuple[List[Tuple[int, Dict[str, Any]]], int]:
    """Any candidate whose stored `raw_order` has no `payments` key is
    refetched fresh via `get_order` (HTTP-before-write, before any DB
    write session opens -- module docstring). A
    candidate whose refetch fails is DROPPED from this run entirely
    (left NULL, retried next run) rather than passed on to
    `sync_payments_for_order` with stale, ambiguous data.

    Two properties this must hold, both of which the module docstring
    already claims for every network call on this path:

    - Fail-open per order, exactly like `_fetch_payments` /
      `_sync_shipment_costs`: a single `get_order` raising (proxy 5xx,
      timeout) used to abort the whole run through `run_backfill`'s
      `except Exception`, taking the shipment cost sync down with it.
      Now it is logged and skipped, and the order is retried next run.
    - It spends network, so it answers to a budget. It shares the
      caller's payment budget rather than introducing a new one: these
      refetches exist only to resolve payments for this same batch, so
      they are the same spend under the same declared ceiling.

    Returns the resolved orders and HOW MANY candidates the budget never
    reached. That second number is not decoration: a candidate dropped
    for lack of budget leaves no trace in `raw_orders`, so the caller's
    payment-side truncation check cannot see it, and a run truncated
    here would otherwise be stamped complete -- silencing the staleness
    alert while the backlog is still growing.
    """
    resolved: List[Tuple[int, Dict[str, Any]]] = []
    starved = 0
    for order_id, raw_order in order_candidates:
        if isinstance(raw_order, dict) and raw_order.get("payments") is not None:
            resolved.append((order_id, raw_order))
            continue
        if budget[0] <= 0:
            starved += 1
            logger.warning(
                "backfill_ml_payments_costs: refetch budget spent before resolving every ambiguous stored "
                "payload; order_id=%s left unresolved for a later run",
                order_id,
            )
            continue
        budget[0] -= 1
        try:
            fresh = resolve_maybe_async(ml_webhook_client.get_order(order_id))
        except Exception:
            logger.warning(
                "backfill_ml_payments_costs: order_id=%s refetch failed; left unresolved for a later run",
                order_id,
                exc_info=True,
            )
            continue
        if isinstance(fresh, dict):
            resolved.append((order_id, fresh))
        else:
            logger.warning(
                "backfill_ml_payments_costs: order_id=%s could not be refetched to resolve its ambiguous "
                "stored payload (no `payments` key); left unresolved for a later run",
                order_id,
            )
    return resolved, starved


def run_backfill(limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> BackfillPaymentsCostsResult:
    """Entry point for `app/scripts/backfill_ml_payments_costs.py`.

    Flag-gated exactly like the sweep and the orders backfill: a complete
    no-op (zero HTTP calls, zero DB writes) while `ML_ORDERS_OPS_ENABLED`
    is False -- and `error` stays `None` in that case:
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
        # Resolve any ambiguous (no `payments` key)
        # stored row BEFORE fetching any payment -- still entirely HTTP,
        # still entirely before any DB write session opens.
        # An explicit budget list (rather than the functions' own
        # `None`-default) so the call site can inspect it afterward, and
        # so the refetch below and the payment fetch answer to the SAME
        # declared ceiling.
        payment_budget = [MAX_PAYMENT_FETCHES_PER_PASS]
        resolved_orders, refetch_starved = _resolve_ambiguous_orders(order_candidates, payment_budget)

        raw_orders = [raw for _, raw in resolved_orders]
        payments_payload = _fetch_payments(raw_orders, payment_budget)
        # "The budget hit zero" is
        # NOT the same fact as "the budget was the reason something is
        # unresolved" -- exactly using up the budget while resolving
        # EVERY needed payment id is a complete pass, not a truncated
        # one. Compare against how many DISTINCT payment ids this batch
        # actually needed.
        needed_payment_ids = {pid for raw in raw_orders for pid in _extract_payment_ids(raw)}
        # Either end of the shared budget can truncate the pass, and a
        # candidate the refetch never reached is invisible to the payment
        # side (it is not in `raw_orders` at all), so both are checked.
        result.payments_budget_exhausted = refetch_starved > 0 or (
            payment_budget[0] <= 0 and len(payments_payload) < len(needed_payment_ids)
        )

        with get_background_db() as db:
            for order_id, raw_order in resolved_orders:
                # `missing_key_is_empty=True`: `raw_order` here is either
                # the original stored row (which already HAD the
                # `payments` key -- `_resolve_ambiguous_orders` only lets
                # those or freshly-refetched rows through) or a payload
                # fresh off `get_order` -- in both cases a still-missing
                # key is now a trustworthy "ML says none" answer.
                if raw_order.get("payments") is None:
                    # Same discipline as the sweep: sealing on an omitted
                    # key is correct here (this payload is fresh off ML),
                    # but the omission must stay VISIBLE instead of
                    # disappearing into the seal.
                    _record_payments_key_missing(db, order_id)
                synced, sealed = sync_payments_for_order(
                    db, order_id, raw_order, payments_payload, missing_key_is_empty=True
                )
                result.payments_synced += synced
                if sealed:
                    result.orders_sealed += 1

        cost_budget = [MAX_COST_FETCHES_PER_PASS]
        # Only a shipment this run
        # actually spent an HTTP fetch on may be charged a give-up
        # attempt. Without this, a backlog larger than
        # `MAX_COST_FETCHES_PER_PASS` charges the shipments the budget
        # never reached, and after `MAX_COST_SYNC_ATTEMPTS` runs they are
        # abandoned without ML ever having been asked once.
        attempted_shipment_ids: set = set()
        result.shipment_costs_synced = _sync_shipment_costs(
            shipment_ids, cost_budget, attempted_out=attempted_shipment_ids
        )
        # Measured against what the budget NEVER REACHED, not against what
        # failed to resolve. A shipment that WAS fetched and still did not
        # settle is ML being slow, not this pass being truncated --
        # comparing against `shipment_costs_synced` raises the staleness
        # alert on a run that did everything it could.
        result.costs_budget_exhausted = cost_budget[0] <= 0 and len(attempted_shipment_ids) < len(shipment_ids)

        # A shipment in this run's candidate
        # set that is still unresolved counts as one more attempt --
        # once it reaches `MAX_COST_SYNC_ATTEMPTS` it stops being a
        # candidate at all (module docstring), so a shipment ML never
        # settles cannot block the backlog behind it forever, and stops
        # spending one HTTP fetch per run once given up.
        if attempted_shipment_ids:
            with get_background_db() as db:
                unresolved_ids = {
                    shipment_id
                    for (shipment_id,) in db.query(MlShipmentOps.shipment_id).filter(
                        MlShipmentOps.shipment_id.in_(shipment_ids),
                        MlShipmentOps.costs_synced_at.is_(None),
                    )
                } & attempted_shipment_ids
                # A shipment that RESOLVED this run must not carry its
                # old attempt count forward: leaving `cost_sync:<id>` at
                # 3 means a future stall gives up after 2 attempts
                # instead of `MAX_COST_SYNC_ATTEMPTS`. The counter
                # describes an unresolved streak, so success ends it.
                _clear_cost_sync_attempts(db, attempted_shipment_ids - unresolved_ids)
                for shipment_id in unresolved_ids:
                    attempts = _record_cost_sync_attempt(db, shipment_id)
                    if attempts >= MAX_COST_SYNC_ATTEMPTS:
                        result.shipments_gave_up += 1
                        logger.warning(
                            "backfill_ml_payments_costs: shipment_id=%s gave up on cost sync after "
                            "%d attempt(s); excluded from future candidate queries",
                            shipment_id,
                            attempts,
                        )
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
            # Mirrors the sweep's
            # own `complete=not result.budget_exhausted` -- a run
            # truncated by either budget must NOT be stamped as a
            # completed pass, or a staleness alert never fires while this
            # backfill keeps truncating.
            complete = not (result.payments_budget_exhausted or result.costs_budget_exhausted)
            release_lock_as_idle(now, complete=complete, cursor_name=CURSOR_NAME)

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
