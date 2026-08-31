"""ML-vs-GBP divergence detection (slice 6 of ml-ventas-fuente-de-verdad).

Compares `ml_orders_ops` (ML API) against the GBP-fed
`tb_mercadolibre_orders_header` and writes `ml_ops_divergence` rows with
`kind` in `missing_in_gbp`, `missing_in_ml`, `field_mismatch`. The other
two kinds the table's CHECK constraint allows, `out_of_window_update` and
`window_not_enumerable`, are owned by `sweep_service.py` -- this module
imports `UNENUMERABLE_KIND` from `app.models.ml_orders_ops` (it describes
a value of that table's `kind` column, so that is where it is defined)
rather than duplicating the literal, so a rename cannot silently stop the
purge below.

Join key: `ml_orders_ops.order_id` CAST to text vs
`TRIM(tb_mercadolibre_orders_header.mlorder_id)`. Only the ML side is
cast to a numeric type -- `mlorder_id` is free text on the GBP side, and
casting IT to a number would raise on a malformed value and abort the
whole pass; string equality just never matches instead. The GBP side is
TRIMmed: an untrimmed padded value would otherwise fail the join for an
order that genuinely exists in `ml_orders_ops`. `mlo_id` is the
GBP-internal surrogate key, NEVER the ML order id -- never used for the
join or as a compared field.

Field comparability: `status`/`mlo_status` and
`paid_amount`/`mlo_total_paid_amount` are COMPARABLE (same ML vocabulary /
both `Numeric`, see `ml_cancelacion_reconciliacion_service.py`).
`order_id`/`mlo_id` are NOT (different id spaces by design).
`date_created`/`shipping_id`/`buyer_*` are out of this slice's comparison
set -- adding one is a one-line `_FIELD_MISMATCH_SPECS` entry. Mismatch
DETECTION compares the raw `Numeric` columns (`ml_col != gbp_col`), never
text, so a scale difference between `Numeric(14,2)` and `Numeric(18,2)`
cannot produce a false positive there.

Cap and progress guarantee: each detection kind is ONE set-based JOIN
query, scoped to `ML_ORDERS_OPS_WINDOW_DAYS` and capped at
`MAX_CANDIDATES_PER_KIND` so a cold start (flag flipped on, `ml_orders_ops`
empty, the full window of GBP orders already there) cannot turn one pass
into tens of thousands of writes. The query excludes rows that do not
need re-processing (see "Reopening contract" below) directly in its
WHERE clause, so an unordered `LIMIT` cannot return the SAME rows every
pass -- a `truncated=True` pass is guaranteed to make progress on the
next one, never a permanent wedge. `ORDER BY` is added for determinism
(repeatable pagination across passes), not as the correctness fix.

`missing_in_ml`'s candidate `order_id` is derived from GBP's free-text
`mlorder_id`: `_valid_numeric_gbp_order_id` filters, in SQL, for a
non-empty, all-digit value no longer than `_MAX_GBP_ORDER_ID_DIGITS`
(the column is `String(50)`; an all-digit value can still be longer than
`BigInteger` can hold, and casting an out-of-range value raises and would
abort the pass). The same filtered, length-bounded expression is reused
for the candidate value, the exclusion, and the ordering, so there is no
separate Python conversion step that could disagree with what SQL
already decided, and no invalid or oversized value is ever a candidate.

Reopening contract: for a kind that carries values (`field_mismatch`),
the exclusion depends on the VALUES, not on the row's state. A candidate
is skipped only while its stored `ml_value`/`gbp_value` still match what
the comparison finds; re-selecting an unchanged divergence every pass
would spend a cap slot forever for no new information. When the values
change the row is re-selected and updated, whatever its state -- an open
row an operator is reading must not show a pair the table knows is stale,
and a closed one reopens because the facts moved again.

For the two kinds with no values (`missing_in_gbp`, `missing_in_ml`)
there is nothing that could change, so an active row is skipped and a
closed one always reopens on rediscovery. Structurally that can only
follow a genuine gap: the JOIN excludes an order while it IS present in
GBP, so regaining candidacy is new information by construction.

`detected_at` means "first detected, or first detected since the last
reopen". Refreshing values on an already-open row does not move it: it is
the same divergence with newer facts, not a new one. (`out_of_window_update`
and `window_not_enumerable` come from `sweep_service.py` on a different
write path and genuinely mean "last seen".)

Value persistence for `field_mismatch`: the stored `ml_value`/`gbp_value`
and the "unchanged" comparison both use the EXACT SAME SQL expression --
`cast(ml_col, String)` / `cast(gbp_col, String)`, computed once per query
and reused for both the SELECT and the exclusion's comparison. This is
deliberate: Python's `str(Decimal(...))` and SQL's `CAST(numeric AS
text)` are not guaranteed to render identically for every scale/value
(they happened to agree while every amount column shared the same
scale, which is exactly the case that stopped holding and is why this
must never be two separate representations). Comparing the persisted
value is therefore correct by construction, not by coincidence -- there
is only one rule, expressed once, used for both jobs.

Persistence: a candidate can legitimately correspond to an EXISTING
(closed, about to reopen) row, so `_apply_divergence` cannot assume every
candidate is a fresh insert. Each detect function preloads the existing
rows matching ONLY this pass's already-capped candidate order_ids -- one
query per kind, bounded by the cap, never by table size, and never one
query per candidate. `_apply_divergence` mutates a preloaded row in
place or stages a new one; a SECOND candidate in the SAME batch
resolving to the same key (GBP can hold two headers whose `mlorder_id`
differs only by padding, which the trimmed join folds into one id) is
skipped once the first one has been applied -- `_detect_field_mismatches`
orders by `mlo_id DESC` so the first one applied is deterministically the
highest `mlo_id`, never an arbitrary winner based on row-return order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import BigInteger, String, and_, case, cast, false, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.ml_orders_ops import UNENUMERABLE_KIND, MlOpsDivergence, MlOrdersOps

logger = logging.getLogger(__name__)

MISSING_IN_GBP_KIND = "missing_in_gbp"
MISSING_IN_ML_KIND = "missing_in_ml"
FIELD_MISMATCH_KIND = "field_mismatch"

# States that mean "already closed, nothing left to do unless the facts
# changed" (module docstring "Reopening contract").
_CLOSED_STATES = ("resolved", "ignored")

# Per-kind, per-pass cap. Generous enough that a healthy environment
# never hits it, small enough that a cold start cannot turn one
# detection pass into tens of thousands of writes. Safe to keep small:
# the exclusion filter (module docstring) guarantees a truncated pass's
# remainder is picked up next run, not lost.
MAX_CANDIDATES_PER_KIND = 5000

# `mlorder_id` is `String(50)` -- an all-digit value can still overflow a
# BigInteger. This is the same bound used by `_valid_numeric_gbp_order_id`'s
# predicate and its CAST, never a separate check that could drift out of
# sync with it.
_MAX_GBP_ORDER_ID_DIGITS = 18

# (field name, ml_orders_ops column, GBP header column) -- compared on
# their native types (module docstring "Field comparability"), never
# pre-cast to text for the mismatch DETECTION itself.
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
    # `"missing_in_gbp"` / `"missing_in_ml"` for those two kinds;
    # `"field_mismatch:<field_name>"` for field_mismatch, since the cap
    # is per FIELD, not per kind -- collapsing to the bare kind name would
    # tell the operator a pass was truncated without saying which field,
    # the exact "less than it knows" defect this chain keeps re-finding.
    truncated_kinds: List[str] = dataclass_field(default_factory=list)
    error: Optional[str] = None


def _join_condition():
    return cast(MlOrdersOps.order_id, String) == func.trim(MercadoLibreOrderHeader.mlorder_id)


def _valid_numeric_gbp_order_id(db: Session, col):
    """Dialect-aware, all-digits-after-trim check WITH a length bound --
    this MUST run in SQL, not after the fetch, and MUST reject a digit
    run too long for `BigInteger` before anything casts it, or the cast
    itself raises and aborts the whole pass. Mirrors the `_insert_stmt`
    dialect-branch precedent used elsewhere in this package."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    trimmed = func.trim(col)
    length_ok = func.length(trimmed) <= _MAX_GBP_ORDER_ID_DIGITS
    if dialect_name == "sqlite":
        # No `~` regexp operator here. GLOB supports negated character
        # classes and is always a full-string match in SQLite, so "does
        # NOT contain a non-digit anywhere" is the portable equivalent.
        return and_(trimmed != "", length_ok, ~trimmed.op("GLOB")("*[^0-9]*"))
    return and_(trimmed != "", length_ok, trimmed.op("~")("^[0-9]+$"))


def _window_floor(now: datetime, window_days: Optional[int] = None) -> datetime:
    days = window_days if window_days is not None else settings.ML_ORDERS_OPS_WINDOW_DAYS
    return now - timedelta(days=days)


def _fetch_capped(query, cap: Optional[int] = None) -> Tuple[list, bool]:
    """Fetches at most `cap` rows and reports whether MORE existed: asks
    for `cap + 1` and checks the extra row, so truncation is known
    without a separate COUNT query. `cap` defaults to the MODULE-LEVEL
    `MAX_CANDIDATES_PER_KIND` resolved at CALL time (not bound as a
    default argument), so tests can monkeypatch it."""
    resolved_cap = cap if cap is not None else MAX_CANDIDATES_PER_KIND
    rows = query.limit(resolved_cap + 1).all()
    if len(rows) > resolved_cap:
        return rows[:resolved_cap], True
    return rows, False


def _preload_batch(
    db: Session, kind: str, field: Optional[str], order_ids
) -> Dict[Tuple[int, Optional[str]], MlOpsDivergence]:
    """ONE query per kind, scoped to THIS pass's already-capped candidate
    order_ids -- bounded by `MAX_CANDIDATES_PER_KIND`, never by table
    size, and never one query per candidate. Needed because a candidate
    can correspond to an existing, about-to-reopen row (module docstring
    "Reopening contract")."""
    order_ids = list(order_ids)
    if not order_ids:
        return {}
    field_match = MlOpsDivergence.field == field if field is not None else MlOpsDivergence.field.is_(None)
    rows = (
        db.query(MlOpsDivergence)
        .filter(MlOpsDivergence.kind == kind, field_match, MlOpsDivergence.order_id.in_(order_ids))
        .all()
    )
    return {(row.order_id, row.field): row for row in rows}


def _apply_divergence(
    db: Session,
    existing: Dict[Tuple[int, Optional[str]], object],
    order_id: int,
    kind: str,
    field: Optional[str],
    ml_value: Optional[str],
    gbp_value: Optional[str],
    now: datetime,
) -> bool:
    """Mutates a preloaded row in place, or stages a new one. `existing`
    doubles as the same-batch duplicate guard: once a key has been
    applied (inserted OR updated), it is marked `True` in `existing`, so
    a second candidate in the SAME batch resolving to the same key
    (padded GBP `mlorder_id` duplicates) is silently skipped -- the FIRST
    one applied wins, and callers that care about which one that is order
    their query accordingly. Returns True if a row was written (inserted
    or updated) -- used for the pass's reported counters."""
    key = (order_id, field)
    row = existing.get(key)
    if row is True:
        return False
    if isinstance(row, MlOpsDivergence):
        row.ml_value = ml_value
        row.gbp_value = gbp_value
        if row.state in _CLOSED_STATES:
            # A closed row coming back is a recurrence, so it reopens and
            # `detected_at` marks that recurrence. An already-open row is
            # the same divergence with fresher values, so its timestamp
            # keeps meaning when it was first seen.
            row.state = "open"
            row.detected_at = now
        existing[key] = True
        return True
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
    existing[key] = True
    return True


def _not_already_recorded(
    db: Session,
    kind: str,
    field: Optional[str],
    order_id_match,
    unchanged_match,
    has_values: bool = True,
):
    """SQL exclusion, value-aware (module docstring "Reopening contract").
    A candidate is excluded only when a matching row exists that is
    either still actively tracked (`state` in `open`/`acknowledged`) or
    closed with UNCHANGED values (`unchanged_match`). `unchanged_match`
    is `false()` for the two value-less kinds, so a closed row of theirs
    is never treated as "unchanged" and is always reopened on
    rediscovery. `order_id_match` is the FULL boolean condition
    correlating `MlOpsDivergence.order_id` to the outer query's order id
    (callers differ on whether that needs a cast, e.g. `missing_in_ml`
    compares against GBP's text `mlorder_id`) -- passed as-is, never
    re-wrapped in another equality."""
    field_match = MlOpsDivergence.field == field if field is not None else MlOpsDivergence.field.is_(None)
    still_active = MlOpsDivergence.state.notin_(_CLOSED_STATES)
    return ~(
        db.query(MlOpsDivergence.id)
        .filter(
            MlOpsDivergence.kind == kind,
            field_match,
            order_id_match,
            # For a kind that carries values, staying out of the result set
            # depends only on the values being unchanged -- regardless of
            # state. Excluding every active row froze `ml_value`/`gbp_value`
            # on exactly the rows an operator reads, so the dashboard showed
            # a pair the table already knew was stale. Kinds without values
            # have nothing that could change, so an active row of theirs is
            # still the same fact and is excluded.
            (still_active if not has_values else unchanged_match),
        )
        .exists()
    )


def _detect_missing_in_gbp(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    """ml_orders_ops rows in-window with no matching GBP header, excluding
    ones that do not need re-processing (see module docstring)."""
    query = (
        db.query(MlOrdersOps.order_id)
        .outerjoin(MercadoLibreOrderHeader, _join_condition())
        .filter(
            MercadoLibreOrderHeader.mlo_id.is_(None),
            MlOrdersOps.date_created.isnot(None),
            MlOrdersOps.date_created >= floor,
            _not_already_recorded(
                db,
                MISSING_IN_GBP_KIND,
                None,
                MlOpsDivergence.order_id == MlOrdersOps.order_id,
                false(),
                has_values=False,
            ),
        )
        .order_by(MlOrdersOps.order_id)
    )
    rows, truncated = _fetch_capped(query)
    order_ids = [order_id for (order_id,) in rows]
    existing = _preload_batch(db, MISSING_IN_GBP_KIND, None, order_ids)
    count = 0
    for order_id in order_ids:
        if _apply_divergence(db, existing, order_id, MISSING_IN_GBP_KIND, None, None, None, now):
            count += 1
    return count, truncated


def _detect_missing_in_ml(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    """GBP header rows in-window with no matching ml_orders_ops row,
    excluding ones that do not need re-processing. Numeric validity,
    length, AND normalisation (leading zeros) all happen IN SQL, computed
    ONCE as `numeric_order_id` and reused for the candidate value, the
    exclusion, and the ordering -- there is no separate Python conversion
    step that could disagree with what SQL already decided (see
    `_valid_numeric_gbp_order_id`)."""
    floor_naive = floor.astimezone(timezone.utc).replace(tzinfo=None)
    valid = _valid_numeric_gbp_order_id(db, MercadoLibreOrderHeader.mlorder_id)
    numeric_order_id = case(
        (valid, cast(func.trim(MercadoLibreOrderHeader.mlorder_id), BigInteger)),
        else_=None,
    )
    query = (
        db.query(numeric_order_id)
        .select_from(MercadoLibreOrderHeader)
        .outerjoin(MlOrdersOps, _join_condition())
        .filter(
            MlOrdersOps.order_id.is_(None),
            MercadoLibreOrderHeader.mlorder_id.isnot(None),
            MercadoLibreOrderHeader.ml_date_created.isnot(None),
            MercadoLibreOrderHeader.ml_date_created >= floor_naive,
            valid,
            _not_already_recorded(
                db,
                MISSING_IN_ML_KIND,
                None,
                MlOpsDivergence.order_id == numeric_order_id,
                false(),
                has_values=False,
            ),
        )
        .order_by(numeric_order_id)
    )
    rows, truncated = _fetch_capped(query)
    order_ids = [order_id for (order_id,) in rows]
    existing = _preload_batch(db, MISSING_IN_ML_KIND, None, order_ids)
    count = 0
    for order_id in order_ids:
        if _apply_divergence(db, existing, order_id, MISSING_IN_ML_KIND, None, None, None, now):
            count += 1
    return count, truncated


def _detect_field_mismatches(db: Session, now: datetime, floor: datetime) -> Tuple[int, List[str]]:
    """Returns `(count, truncated_field_names)` -- the cap is per FIELD
    (module docstring "Cap and progress guarantee"), so the caller needs
    to know WHICH field was cut, not just that field_mismatch was."""
    count = 0
    truncated_fields: List[str] = []
    for field_name, ml_col, gbp_col in _FIELD_MISMATCH_SPECS:
        # The persisted value and the "unchanged" comparison are the
        # SAME expression (module docstring "Value persistence") -- text
        # equality here is exactly what gets written below, never a
        # separately-computed Python string.
        ml_text = cast(ml_col, String)
        gbp_text = cast(gbp_col, String)
        unchanged = and_(MlOpsDivergence.ml_value == ml_text, MlOpsDivergence.gbp_value == gbp_text)
        query = (
            db.query(MlOrdersOps.order_id, ml_text, gbp_text)
            .join(MercadoLibreOrderHeader, _join_condition())
            .filter(
                ml_col.isnot(None),
                gbp_col.isnot(None),
                ml_col != gbp_col,
                MlOrdersOps.date_created.isnot(None),
                MlOrdersOps.date_created >= floor,
                _not_already_recorded(
                    db,
                    FIELD_MISMATCH_KIND,
                    field_name,
                    MlOpsDivergence.order_id == MlOrdersOps.order_id,
                    unchanged,
                ),
            )
            # Two GBP headers differing only by padding can resolve to
            # the same order_id with different values -- ordering by the
            # GBP-internal id (never a compared field itself, module
            # docstring "Join key") makes which one wins deterministic
            # instead of "whatever the DB returns".
            .order_by(MlOrdersOps.order_id, MercadoLibreOrderHeader.mlo_id.desc())
        )
        rows, field_truncated = _fetch_capped(query)
        if field_truncated:
            truncated_fields.append(field_name)
        order_ids = [order_id for order_id, _ml, _gbp in rows]
        existing = _preload_batch(db, FIELD_MISMATCH_KIND, field_name, order_ids)
        for order_id, ml_value, gbp_value in rows:
            if _apply_divergence(db, existing, order_id, FIELD_MISMATCH_KIND, field_name, ml_value, gbp_value, now):
                count += 1
    return count, truncated_fields


def purge_stale_unenumerable(db: Session, now: datetime, retention: Optional[timedelta] = None) -> int:
    """Retention policy (mandatory debt from slice 3, `sweep_service.
    record_unenumerable_window` docstring): `window_not_enumerable` rows
    use `order_id=0` as a sentinel and grow unbounded (one row per leaf,
    fresh bounds each pass, nothing collapses them on its own). Deletion
    here (a background job, not `downgrade()`) is safe: the unenumerable
    leaf is re-attempted by the very next sweep pass regardless of
    whether this row still exists, so purging an OLD one only loses
    instrumentation that already stopped being actionable.
    `UNENUMERABLE_KIND` is imported from `app.models.ml_orders_ops`, not
    re-typed -- it describes a value of that table's `kind` column, this
    module only cleans up after the sweep that writes it."""
    retention_delta = (
        retention if retention is not None else timedelta(days=settings.ML_ORDERS_OPS_UNENUMERABLE_RETENTION_DAYS)
    )
    cutoff = now - retention_delta
    deleted = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == 0,
            MlOpsDivergence.kind == UNENUMERABLE_KIND,
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
        field_mismatches, mismatch_truncated_fields = _detect_field_mismatches(db, resolved_now, floor)
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
    truncated_kinds.extend(f"{FIELD_MISMATCH_KIND}:{name}" for name in mismatch_truncated_fields)
    if truncated_kinds:
        # Never silent: the exclusion filter (module docstring) guarantees
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
