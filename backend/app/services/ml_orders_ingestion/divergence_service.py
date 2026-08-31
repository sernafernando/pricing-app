"""ML-vs-GBP divergence detection (slice 6 of ml-ventas-fuente-de-verdad).

Compares `ml_orders_ops` (ML API, slice 3) against the GBP-fed
`tb_mercadolibre_orders_header` and writes/refreshes `ml_ops_divergence`
rows with `kind` in `missing_in_gbp`, `missing_in_ml`, `field_mismatch`
(`out_of_window_update`/`window_not_enumerable` stay owned by
`sweep_service.py`, obs #1828 cross-slice contract).

Join key: `ml_orders_ops.order_id` CAST to text vs
`tb_mercadolibre_orders_header.mlorder_id` (already a String). Only the ML
side is cast -- casting the free-text GBP side to a numeric type would
raise on a malformed value and abort the whole pass; string equality just
never matches instead. `mlo_id` is the GBP-internal surrogate key, NEVER
the ML order id -- it is never used for the join or as a compared field.

Field comparability, honest inventory: `status`/`mlo_status` and
`paid_amount`/`mlo_total_paid_amount` are COMPARABLE (same ML vocabulary /
same fixed-scale Numeric, see `ml_cancelacion_reconciliacion_service.py`).
`order_id`/`mlo_id` are NOT (different id spaces by design).
`date_created`/`shipping_id`/`buyer_*` are left out of this slice's set on
purpose -- adding one is a one-line `_FIELD_MISMATCH_SPECS` entry.

Cost (precedent D3, `link_resolver_service.py`): each detection kind is
ONE set-based JOIN query, never a per-row Python loop over either source
table, both scoped to `ML_ORDERS_OPS_WINDOW_DAYS` so a years-deep GBP
backlog predating this ops layer is never flagged `missing_in_ml`. Only
the query RESULT (the bounded divergence candidates) is iterated in
Python to persist -- same idiom as `sweep_service._record_out_of_window`.

Dedup: re-detection updates `detected_at` (unique `(order_id, kind,
field)`, NULLS NOT DISTINCT), never duplicates. A divergence no longer
reproduced is NOT auto-resolved -- state changes are an explicit
`ml_ops.gestionar` action, never a silent side effect of detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps

logger = logging.getLogger(__name__)

MISSING_IN_GBP_KIND = "missing_in_gbp"
MISSING_IN_ML_KIND = "missing_in_ml"
FIELD_MISMATCH_KIND = "field_mismatch"

# (field name, ml_orders_ops column expression, GBP header column
# expression) -- both sides cast to text so the comparison and the
# eventual `ml_value`/`gbp_value` (Text columns) storage are uniform.
_FIELD_MISMATCH_SPECS: Tuple[Tuple[str, object, object], ...] = (
    ("status", MlOrdersOps.status, MercadoLibreOrderHeader.mlo_status),
    (
        "paid_amount",
        cast(MlOrdersOps.paid_amount, String),
        cast(MercadoLibreOrderHeader.mlo_total_paid_amount, String),
    ),
)


@dataclass
class DivergenceDetectionResult:
    ran: bool
    missing_in_gbp: int = 0
    missing_in_ml: int = 0
    field_mismatches: int = 0
    unenumerable_purged: int = 0
    error: Optional[str] = None


def _join_condition():
    return cast(MlOrdersOps.order_id, String) == MercadoLibreOrderHeader.mlorder_id


def _window_floor(now: datetime, window_days: Optional[int] = None) -> datetime:
    days = window_days if window_days is not None else settings.ML_ORDERS_OPS_WINDOW_DAYS
    return now - timedelta(days=days)


def _record_divergence(
    db: Session,
    order_id: int,
    kind: str,
    field: Optional[str],
    ml_value: Optional[str],
    gbp_value: Optional[str],
    now: datetime,
) -> bool:
    """Insert-or-refresh one divergence row. Returns True if a NEW row was
    created (used for the counters the cron script logs), False if an
    existing open/acknowledged/resolved/ignored row was simply refreshed.
    Iterates over an already-bounded candidate list -- see module
    docstring "Cost" section -- never the source tables themselves."""
    existing = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == order_id,
            MlOpsDivergence.kind == kind,
            MlOpsDivergence.field == field if field is not None else MlOpsDivergence.field.is_(None),
        )
        .first()
    )
    if existing is not None:
        existing.detected_at = now
        existing.ml_value = ml_value
        existing.gbp_value = gbp_value
        return False
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


def _detect_missing_in_gbp(db: Session, now: datetime, floor: datetime) -> int:
    """ml_orders_ops rows in-window with no matching GBP header."""
    rows = (
        db.query(MlOrdersOps.order_id)
        .outerjoin(MercadoLibreOrderHeader, _join_condition())
        .filter(
            MercadoLibreOrderHeader.mlo_id.is_(None),
            MlOrdersOps.date_created.isnot(None),
            MlOrdersOps.date_created >= floor,
        )
        .all()
    )
    count = 0
    for (order_id,) in rows:
        if _record_divergence(db, order_id, MISSING_IN_GBP_KIND, None, None, None, now):
            count += 1
    return count


def _detect_missing_in_ml(db: Session, now: datetime, floor: datetime) -> int:
    """GBP header rows in-window with no matching ml_orders_ops row.
    `mlorder_id` is validated as a plain integer on the already-bounded
    result set -- a malformed value is skipped, never crashes the pass."""
    floor_naive = floor.astimezone(timezone.utc).replace(tzinfo=None)
    rows = (
        db.query(MercadoLibreOrderHeader.mlorder_id)
        .outerjoin(MlOrdersOps, _join_condition())
        .filter(
            MlOrdersOps.order_id.is_(None),
            MercadoLibreOrderHeader.mlorder_id.isnot(None),
            MercadoLibreOrderHeader.ml_date_created.isnot(None),
            MercadoLibreOrderHeader.ml_date_created >= floor_naive,
        )
        .all()
    )
    count = 0
    for (mlorder_id_str,) in rows:
        if not mlorder_id_str or not mlorder_id_str.strip().isdigit():
            continue
        order_id = int(mlorder_id_str.strip())
        if _record_divergence(db, order_id, MISSING_IN_ML_KIND, None, None, None, now):
            count += 1
    return count


def _detect_field_mismatches(db: Session, now: datetime, floor: datetime) -> int:
    count = 0
    for field, ml_col, gbp_col in _FIELD_MISMATCH_SPECS:
        rows = (
            db.query(MlOrdersOps.order_id, ml_col, gbp_col)
            .join(MercadoLibreOrderHeader, _join_condition())
            .filter(
                ml_col.isnot(None),
                gbp_col.isnot(None),
                ml_col != gbp_col,
                MlOrdersOps.date_created.isnot(None),
                MlOrdersOps.date_created >= floor,
            )
            .all()
        )
        for order_id, ml_value, gbp_value in rows:
            if _record_divergence(db, order_id, FIELD_MISMATCH_KIND, field, str(ml_value), str(gbp_value), now):
                count += 1
    return count


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
        missing_in_gbp = _detect_missing_in_gbp(db, resolved_now, floor)
        missing_in_ml = _detect_missing_in_ml(db, resolved_now, floor)
        field_mismatches = _detect_field_mismatches(db, resolved_now, floor)
        purged = purge_stale_unenumerable(db, resolved_now)
        db.flush()
    except Exception as e:  # noqa: BLE001
        logger.exception("detect_ml_divergences: detection pass failed")
        return DivergenceDetectionResult(ran=True, error=f"{type(e).__name__}: {e}")

    return DivergenceDetectionResult(
        ran=True,
        missing_in_gbp=missing_in_gbp,
        missing_in_ml=missing_in_ml,
        field_mismatches=field_mismatches,
        unenumerable_purged=purged,
    )
