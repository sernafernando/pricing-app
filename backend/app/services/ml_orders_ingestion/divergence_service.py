"""ML-vs-GBP divergence detection (slice 6 of ml-ventas-fuente-de-verdad).

Compares `ml_orders_ops` (ML API, slice 3) against the GBP-fed
`tb_mercadolibre_orders_header` and writes `ml_ops_divergence` rows with
`kind` in `missing_in_gbp`, `missing_in_ml`, `field_mismatch`
(`out_of_window_update`/`window_not_enumerable` stay owned by
`sweep_service.py`, obs #1828 cross-slice contract).

Join key: `ml_orders_ops.order_id` CAST to text vs
`TRIM(tb_mercadolibre_orders_header.mlorder_id)`. Only the ML side is cast
-- casting the free-text GBP side to a numeric type would raise on a
malformed value and abort the whole pass; string equality just never
matches instead. The GBP side is TRIMmed (pre-push review finding 4): a
padded value (`" 101"`) would otherwise silently fail to join and get
reported `missing_in_ml` for an order that genuinely exists in
`ml_orders_ops` -- a false positive in the exact table meant to build
trust. `mlo_id` is the GBP-internal surrogate key, NEVER the ML order id
-- it is never used for the join or as a compared field.

Field comparability, honest inventory: `status`/`mlo_status` and
`paid_amount`/`mlo_total_paid_amount` are COMPARABLE (same ML vocabulary /
both `Numeric`, see `ml_cancelacion_reconciliacion_service.py`).
`order_id`/`mlo_id` are NOT (different id spaces by design).
`date_created`/`shipping_id`/`buyer_*` are left out of this slice's set on
purpose -- adding one is a one-line `_FIELD_MISMATCH_SPECS` entry. Amount
comparison is done on the raw `Numeric` columns, never cast to text
first (pre-push review finding 3): `Numeric(14,2)` vs `Numeric(18,2)`
happen to share a scale today, but a text compare would falsely flag
every order the day either scale changes. Values are only stringified
once, at persistence time, for the `Text` `ml_value`/`gbp_value` columns.

Cost / cap / progress guarantee (round 2 review, blocking finding 1): each
detection kind is ONE set-based JOIN query, scoped to
`ML_ORDERS_OPS_WINDOW_DAYS` and capped at `MAX_CANDIDATES_PER_KIND` so a
cold start (flag flipped on, `ml_orders_ops` empty, the full window of GBP
orders already there) cannot turn one pass into tens of thousands of
writes. The query ALSO excludes any `(order_id, kind[, field])` that
already has an `ml_ops_divergence` row -- a plain `LIMIT` with no
exclusion would let an unordered query return the SAME rows every pass
(Postgres, same plan, same pages), truncating some candidates FOREVER
instead of "eventually". With the exclusion, every candidate a pass
records is new, so the NEXT pass's query genuinely no longer sees it and
advances into what is not yet recorded -- a `truncated=True` pass really
is a "come back next run" pass, not a wedge. `ORDER BY` is added too, for
determinism (repeatable pagination) rather than as the correctness fix
itself.

Consequence of the exclusion (spec if the dashboard ever surfaces this):
`detected_at` on `missing_in_gbp`/`missing_in_ml`/`field_mismatch` rows
now means FIRST detected, not last seen -- a divergence that keeps
reproducing is never re-selected by the query, so nothing refreshes its
timestamp. `out_of_window_update`/`window_not_enumerable` are unaffected
(different write path, `sweep_service.py`, genuinely "last seen").

Persistence (pre-push review finding 1, round 1): writing one
`SELECT ... LIMIT 1` per candidate was an N+1 that could fire tens of
thousands of queries on a cold start -- the project has a production
pool-exhaustion incident on record from exactly this shape. The
exclusion above makes every row the query returns provably new, so there
is no cross-pass preload to bound anymore (round 2 finding 2 resolved as
a side effect): `_apply_divergence` only guards against TWO candidates
in the SAME batch resolving to the same key (GBP can hold two headers
whose `mlorder_id` differs only by padding, which the trimmed join folds
into one id -- round 1 finding, made reachable by the TRIM fix). That
guard is a plain in-memory dict scoped to one call, never a query.
Determinism for that case (round 2 finding 3): `_detect_field_mismatches`
orders by `mlo_id DESC`, so the first row seen for a duplicate key is
always the highest `mlo_id`, and `_apply_divergence` keeps the FIRST
value for a key it sees twice in one batch -- never an arbitrary winner
based on whatever order the database happens to return.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps

logger = logging.getLogger(__name__)

MISSING_IN_GBP_KIND = "missing_in_gbp"
MISSING_IN_ML_KIND = "missing_in_ml"
FIELD_MISMATCH_KIND = "field_mismatch"

# Per-kind, per-pass cap (pre-push review finding 2, round 1). Generous
# enough that a healthy environment never hits it, small enough that a
# cold start cannot turn one detection pass into tens of thousands of
# writes. Safe to keep small: the exclusion filter (module docstring)
# guarantees a truncated pass's remainder is picked up next run, not lost.
MAX_CANDIDATES_PER_KIND = 5000

# (field name, ml_orders_ops column, GBP header column) -- compared on
# their native types (see module docstring "Field comparability"), never
# pre-cast to text.
_FIELD_MISMATCH_SPECS: Tuple[Tuple[str, object, object], ...] = (
    ("status", MlOrdersOps.status, MercadoLibreOrderHeader.mlo_status),
    ("paid_amount", MlOrdersOps.paid_amount, MercadoLibreOrderHeader.mlo_total_paid_amount),
)


@dataclass
class DivergenceDetectionResult:
    ran: bool
    missing_in_gbp: int = 0
    missing_in_ml: int = 0
    field_mismatches: int = 0
    unenumerable_purged: int = 0
    truncated: bool = False
    truncated_kinds: List[str] = dataclass_field(default_factory=list)
    error: Optional[str] = None


def _join_condition():
    return cast(MlOrdersOps.order_id, String) == func.trim(MercadoLibreOrderHeader.mlorder_id)


def _window_floor(now: datetime, window_days: Optional[int] = None) -> datetime:
    days = window_days if window_days is not None else settings.ML_ORDERS_OPS_WINDOW_DAYS
    return now - timedelta(days=days)


def _fetch_capped(query, cap: Optional[int] = None) -> Tuple[list, bool]:
    """Fetches at most `cap` rows and reports whether MORE existed (finding
    2, round 1): asks for `cap + 1` and checks the extra row, so
    truncation is known without a separate COUNT query. `cap` defaults to
    the MODULE-LEVEL `MAX_CANDIDATES_PER_KIND` resolved at CALL time (not
    bound as a default argument), so tests can monkeypatch it."""
    resolved_cap = cap if cap is not None else MAX_CANDIDATES_PER_KIND
    rows = query.limit(resolved_cap + 1).all()
    if len(rows) > resolved_cap:
        return rows[:resolved_cap], True
    return rows, False


def _apply_divergence(
    db: Session,
    seen: Dict[Tuple[int, Optional[str]], None],
    order_id: int,
    kind: str,
    field: Optional[str],
    ml_value: Optional[str],
    gbp_value: Optional[str],
    now: datetime,
) -> bool:
    """Stages a NEW divergence row. Every candidate reaching this function
    was already excluded-if-known by the SQL query (module docstring), so
    there is nothing to update here -- `seen` only guards against two
    candidates in the SAME batch resolving to the same key: the FIRST one
    wins (round 2 finding 3 determinism -- callers that care about which
    one wins order their query so the first row IS the intended winner),
    later ones are silently skipped (they describe the same divergence,
    not a different one). Returns True if a row was staged."""
    key = (order_id, field)
    if key in seen:
        return False
    seen[key] = None
    db.add(
        MlOpsDivergence(
            order_id=order_id,
            kind=kind,
            field=field,
            ml_value=ml_value,
            gbp_value=gbp_value,
            detected_at=now,
        )
    )
    return True


def _not_already_recorded(db: Session, kind: str, field: Optional[str], order_id_match):
    """SQL exclusion (round 2 blocking finding 1): a candidate whose
    `(order_id, kind[, field])` already has an `ml_ops_divergence` row is
    excluded from the result set entirely, so an unordered `LIMIT` cannot
    return the identical page forever -- every pass's candidates are
    provably not-yet-recorded, and the NEXT pass's query genuinely no
    longer sees what THIS pass just wrote. `order_id_match` is the FULL
    boolean condition correlating `MlOpsDivergence.order_id` to the outer
    query's order id (callers differ on whether that needs a cast, e.g.
    `missing_in_ml` compares against GBP's text `mlorder_id`) -- passed
    as-is, never re-wrapped in another equality."""
    field_match = MlOpsDivergence.field == field if field is not None else MlOpsDivergence.field.is_(None)
    return ~(db.query(MlOpsDivergence.id).filter(MlOpsDivergence.kind == kind, field_match, order_id_match).exists())


def _detect_missing_in_gbp(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    """ml_orders_ops rows in-window with no matching GBP header, excluding
    ones already recorded (see module docstring)."""
    query = (
        db.query(MlOrdersOps.order_id)
        .outerjoin(MercadoLibreOrderHeader, _join_condition())
        .filter(
            MercadoLibreOrderHeader.mlo_id.is_(None),
            MlOrdersOps.date_created.isnot(None),
            MlOrdersOps.date_created >= floor,
            _not_already_recorded(db, MISSING_IN_GBP_KIND, None, MlOpsDivergence.order_id == MlOrdersOps.order_id),
        )
        .order_by(MlOrdersOps.order_id)
    )
    rows, truncated = _fetch_capped(query)
    seen: Dict[Tuple[int, Optional[str]], None] = {}
    count = 0
    for (order_id,) in rows:
        if _apply_divergence(db, seen, order_id, MISSING_IN_GBP_KIND, None, None, None, now):
            count += 1
    return count, truncated


def _detect_missing_in_ml(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    """GBP header rows in-window with no matching ml_orders_ops row,
    excluding ones already recorded. `mlorder_id` is validated as a plain
    integer on the already-bounded result set -- a malformed value is
    skipped, never crashes the pass."""
    floor_naive = floor.astimezone(timezone.utc).replace(tzinfo=None)
    order_id_match = cast(MlOpsDivergence.order_id, String) == func.trim(MercadoLibreOrderHeader.mlorder_id)
    query = (
        db.query(MercadoLibreOrderHeader.mlorder_id)
        .outerjoin(MlOrdersOps, _join_condition())
        .filter(
            MlOrdersOps.order_id.is_(None),
            MercadoLibreOrderHeader.mlorder_id.isnot(None),
            MercadoLibreOrderHeader.ml_date_created.isnot(None),
            MercadoLibreOrderHeader.ml_date_created >= floor_naive,
            _not_already_recorded(db, MISSING_IN_ML_KIND, None, order_id_match),
        )
        .order_by(MercadoLibreOrderHeader.mlorder_id)
    )
    rows, truncated = _fetch_capped(query)
    seen: Dict[Tuple[int, Optional[str]], None] = {}
    count = 0
    for (mlorder_id_str,) in rows:
        if not mlorder_id_str or not mlorder_id_str.strip().isdigit():
            continue
        order_id = int(mlorder_id_str.strip())
        if _apply_divergence(db, seen, order_id, MISSING_IN_ML_KIND, None, None, None, now):
            count += 1
    return count, truncated


def _detect_field_mismatches(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    count = 0
    truncated = False
    for field_name, ml_col, gbp_col in _FIELD_MISMATCH_SPECS:
        query = (
            db.query(MlOrdersOps.order_id, ml_col, gbp_col)
            .join(MercadoLibreOrderHeader, _join_condition())
            .filter(
                ml_col.isnot(None),
                gbp_col.isnot(None),
                ml_col != gbp_col,
                MlOrdersOps.date_created.isnot(None),
                MlOrdersOps.date_created >= floor,
                _not_already_recorded(
                    db, FIELD_MISMATCH_KIND, field_name, MlOpsDivergence.order_id == MlOrdersOps.order_id
                ),
            )
            # Round 2 finding 3: two GBP headers differing only by padding
            # can resolve to the same order_id with different values --
            # ordering by the GBP-internal id (never a compared field
            # itself, see module docstring "Join key") makes which one
            # wins deterministic instead of "whatever the DB returns".
            .order_by(MlOrdersOps.order_id, MercadoLibreOrderHeader.mlo_id.desc())
        )
        rows, field_truncated = _fetch_capped(query)
        truncated = truncated or field_truncated
        seen: Dict[Tuple[int, Optional[str]], None] = {}
        for order_id, ml_value, gbp_value in rows:
            if _apply_divergence(
                db, seen, order_id, FIELD_MISMATCH_KIND, field_name, str(ml_value), str(gbp_value), now
            ):
                count += 1
    return count, truncated


def purge_stale_unenumerable(db: Session, now: datetime, retention: Optional[timedelta] = None) -> int:
    """Retention policy (mandatory debt from slice 3, `sweep_service.
    record_unenumerable_window` docstring): `window_not_enumerable` rows
    use `order_id=0` as a sentinel and grow unbounded (one row per leaf,
    fresh bounds each pass, nothing collapses them on its own). Deletion
    here (a background job, not `downgrade()`) is safe: the unenumerable
    leaf is re-attempted by the very next sweep pass regardless of
    whether this row still exists, so purging an OLD one only loses
    instrumentation that already stopped being actionable."""
    retention_delta = (
        retention if retention is not None else timedelta(days=settings.ML_ORDERS_OPS_UNENUMERABLE_RETENTION_DAYS)
    )
    cutoff = now - retention_delta
    deleted = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == 0,
            MlOpsDivergence.kind == "window_not_enumerable",
            MlOpsDivergence.detected_at < cutoff,
        )
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def detect_divergences(db: Session, now: Optional[datetime] = None) -> DivergenceDetectionResult:
    """Entry point for the cron job (`app/scripts/detect_ml_divergences.py`).

    Flag-gated: a complete no-op (zero reads/writes) while
    `ML_ORDERS_OPS_ENABLED` is False, same precedent as `resolve_links`.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return DivergenceDetectionResult(ran=False)

    resolved_now = now if now is not None else datetime.now(timezone.utc)
    floor = _window_floor(resolved_now)

    try:
        missing_in_gbp, gbp_truncated = _detect_missing_in_gbp(db, resolved_now, floor)
        missing_in_ml, ml_truncated = _detect_missing_in_ml(db, resolved_now, floor)
        field_mismatches, mismatch_truncated = _detect_field_mismatches(db, resolved_now, floor)
        purged = purge_stale_unenumerable(db, resolved_now)
        db.flush()
    except Exception as e:  # noqa: BLE001
        logger.exception("detect_ml_divergences: detection pass failed")
        # `get_background_db` commits on exit, so a session left in a failed
        # state turns this reported error into PendingRollbackError and a
        # traceback -- the error handling would be decorative.
        db.rollback()
        return DivergenceDetectionResult(ran=True, error=f"{type(e).__name__}: {e}")

    truncated_kinds = []
    if gbp_truncated:
        truncated_kinds.append(MISSING_IN_GBP_KIND)
    if ml_truncated:
        truncated_kinds.append(MISSING_IN_ML_KIND)
    if mismatch_truncated:
        truncated_kinds.append(FIELD_MISMATCH_KIND)
    if truncated_kinds:
        # Never silent (this chain's most repeated defect, five prior
        # instances): the exclusion filter (module docstring) guarantees
        # the next pass covers whatever this cap left out.
        logger.warning(
            "detect_ml_divergences: pass truncated at MAX_CANDIDATES_PER_KIND=%s for kind(s)=%s -- "
            "the remainder will be recorded on the next pass",
            MAX_CANDIDATES_PER_KIND,
            truncated_kinds,
        )

    return DivergenceDetectionResult(
        ran=True,
        missing_in_gbp=missing_in_gbp,
        missing_in_ml=missing_in_ml,
        field_mismatches=field_mismatches,
        unenumerable_purged=purged,
        truncated=bool(truncated_kinds),
        truncated_kinds=truncated_kinds,
    )
