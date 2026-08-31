"""ML-vs-GBP divergence detection (slice 6 of ml-ventas-fuente-de-verdad).

Compares `ml_orders_ops` (ML API, slice 3) against the GBP-fed
`tb_mercadolibre_orders_header` and writes/refreshes `ml_ops_divergence`
rows with `kind` in `missing_in_gbp`, `missing_in_ml`, `field_mismatch`
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

Cost (precedent D3, `link_resolver_service.py`): each detection kind is
ONE set-based JOIN query, never a per-row Python loop over either source
table, both scoped to `ML_ORDERS_OPS_WINDOW_DAYS` so a years-deep GBP
backlog predating this ops layer is never flagged `missing_in_ml`. Each
query is also capped at `MAX_CANDIDATES_PER_KIND` (pre-push review
finding 2): a cold start -- flag flipped on with `ml_orders_ops` still
empty and the full window of GBP orders already there -- would otherwise
attempt one write per GBP order in a single pass. A capped pass is
recorded as `truncated=True` in the result AND logged explicitly (this
chain's most repeated defect is a job under-reporting what it knows; a
silently-capped pass would be the sixth instance) -- the NEXT pass picks
up whatever the cap left out, since nothing here advances a cursor.

Persistence (pre-push review finding 1): writing one `SELECT ... LIMIT 1`
per candidate is an N+1 that would fire tens of thousands of queries on
the cold start above -- the project has a production pool-exhaustion
incident on record from exactly this shape. Instead, the existing
divergences for a `kind` are preloaded into a dict with ONE query before
the loop; the loop itself only mutates already-loaded ORM objects
in-memory or stages new ones with `db.add`, flushed once at the end.

Dedup: re-detection updates `detected_at` (unique `(order_id, kind,
field)`, NULLS NOT DISTINCT), never duplicates. A divergence no longer
reproduced is NOT auto-resolved -- state changes are an explicit
`ml_ops.gestionar` action, never a silent side effect of detection.
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

# Per-kind, per-pass cap (pre-push review finding 2). Generous enough that a
# healthy environment never hits it, small enough that a cold start cannot
# turn one detection pass into tens of thousands of writes.
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
    2): asks for `cap + 1` and checks the extra row, so truncation is known
    without a separate COUNT query. `cap` defaults to the MODULE-LEVEL
    `MAX_CANDIDATES_PER_KIND` resolved at CALL time (not bound as a default
    argument), so tests can monkeypatch it."""
    resolved_cap = cap if cap is not None else MAX_CANDIDATES_PER_KIND
    rows = query.limit(resolved_cap + 1).all()
    if len(rows) > resolved_cap:
        return rows[:resolved_cap], True
    return rows, False


def _preload_existing(db: Session, kind: str) -> Dict[Tuple[int, Optional[str]], MlOpsDivergence]:
    """ONE query per kind (finding 1), never one per candidate. Bounded by
    how many divergences of this `kind` already exist, not by the
    (possibly much larger) candidate list a cold start produces."""
    rows = db.query(MlOpsDivergence).filter(MlOpsDivergence.kind == kind).all()
    return {(row.order_id, row.field): row for row in rows}


def _apply_divergence(
    db: Session,
    existing: Dict[Tuple[int, Optional[str]], MlOpsDivergence],
    order_id: int,
    kind: str,
    field: Optional[str],
    ml_value: Optional[str],
    gbp_value: Optional[str],
    now: datetime,
) -> bool:
    """Mutates an already-loaded ORM object or stages a new one -- no
    query. Returns True if a NEW row was staged."""
    row = existing.get((order_id, field))
    if row is not None:
        row.detected_at = now
        row.ml_value = ml_value
        row.gbp_value = gbp_value
        return False
    row = MlOpsDivergence(
        order_id=order_id,
        kind=kind,
        field=field,
        ml_value=ml_value,
        gbp_value=gbp_value,
        detected_at=now,
    )
    db.add(row)
    # Registered immediately: the preload runs once, so without this a
    # second candidate resolving to the same key in the SAME pass stages a
    # duplicate and the flush dies on the unique constraint, losing the
    # whole pass. GBP can hold two headers whose `mlorder_id` differs only
    # by padding, which the trimmed join now folds into one id.
    existing[(order_id, field)] = row
    return True


def _detect_missing_in_gbp(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    """ml_orders_ops rows in-window with no matching GBP header."""
    query = (
        db.query(MlOrdersOps.order_id)
        .outerjoin(MercadoLibreOrderHeader, _join_condition())
        .filter(
            MercadoLibreOrderHeader.mlo_id.is_(None),
            MlOrdersOps.date_created.isnot(None),
            MlOrdersOps.date_created >= floor,
        )
    )
    rows, truncated = _fetch_capped(query)
    existing = _preload_existing(db, MISSING_IN_GBP_KIND)
    count = 0
    for (order_id,) in rows:
        if _apply_divergence(db, existing, order_id, MISSING_IN_GBP_KIND, None, None, None, now):
            count += 1
    return count, truncated


def _detect_missing_in_ml(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    """GBP header rows in-window with no matching ml_orders_ops row.
    `mlorder_id` is validated as a plain integer on the already-bounded
    result set -- a malformed value is skipped, never crashes the pass."""
    floor_naive = floor.astimezone(timezone.utc).replace(tzinfo=None)
    query = (
        db.query(MercadoLibreOrderHeader.mlorder_id)
        .outerjoin(MlOrdersOps, _join_condition())
        .filter(
            MlOrdersOps.order_id.is_(None),
            MercadoLibreOrderHeader.mlorder_id.isnot(None),
            MercadoLibreOrderHeader.ml_date_created.isnot(None),
            MercadoLibreOrderHeader.ml_date_created >= floor_naive,
        )
    )
    rows, truncated = _fetch_capped(query)
    existing = _preload_existing(db, MISSING_IN_ML_KIND)
    count = 0
    for (mlorder_id_str,) in rows:
        if not mlorder_id_str or not mlorder_id_str.strip().isdigit():
            continue
        order_id = int(mlorder_id_str.strip())
        if _apply_divergence(db, existing, order_id, MISSING_IN_ML_KIND, None, None, None, now):
            count += 1
    return count, truncated


def _detect_field_mismatches(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    count = 0
    truncated = False
    existing = _preload_existing(db, FIELD_MISMATCH_KIND)
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
            )
        )
        rows, field_truncated = _fetch_capped(query)
        truncated = truncated or field_truncated
        for order_id, ml_value, gbp_value in rows:
            if _apply_divergence(
                db, existing, order_id, FIELD_MISMATCH_KIND, field_name, str(ml_value), str(gbp_value), now
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
        # instances): the next pass covers whatever this cap left out.
        logger.warning(
            "detect_ml_divergences: pass truncated at MAX_CANDIDATES_PER_KIND=%s for kind(s)=%s -- "
            "not every divergence in-window was recorded this pass",
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
