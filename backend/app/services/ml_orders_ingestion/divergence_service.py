"""ML-vs-GBP divergence detection (slice 6 of ml-ventas-fuente-de-verdad).

Compares `ml_orders_ops` (ML API, slice 3) against the GBP-fed
`tb_mercadolibre_orders_header` and writes `ml_ops_divergence` rows with
`kind` in `missing_in_gbp`, `missing_in_ml`, `field_mismatch`. The other
two kinds the table's CHECK constraint allows, `out_of_window_update` and
`window_not_enumerable`, stay owned by `sweep_service.py` (obs #1828
cross-slice contract) -- this module imports `UNENUMERABLE_KIND` from
there rather than re-typing the literal (round 5 minor finding: a
duplicated string is a contract with no enforcement; if the other side
renames it, this module's purge silently stops working).

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

Cost / cap / progress guarantee (round 2 blocking finding 1): each
detection kind is ONE set-based JOIN query, scoped to
`ML_ORDERS_OPS_WINDOW_DAYS` and capped at `MAX_CANDIDATES_PER_KIND` so a
cold start (flag flipped on, `ml_orders_ops` empty, the full window of GBP
orders already there) cannot turn one pass into tens of thousands of
writes. The query ALSO excludes rows that do not need re-processing (see
"Reopening contract" below), so an unordered `LIMIT` cannot return the
SAME rows every pass and truncate some candidates FOREVER instead of
"eventually" -- a `truncated=True` pass really is a "come back next run"
pass. `ORDER BY` is added too, for determinism (repeatable pagination),
not as the correctness fix itself.

Numeric validity/normalisation for `missing_in_ml` (round 4 blocking
finding, extended round 5): `_valid_numeric_gbp_order_id` filters IN SQL
-- never in Python, post-fetch -- so a malformed `mlorder_id` never
consumes a cap slot in the first place (round 4: a value dropped only
AFTER the fetch could occupy every slot forever with a deterministic
`ORDER BY`). It also bounds the LENGTH of the digit run (round 5 blocking
finding): `mlorder_id` is `String(50)`, so an all-digit value can still
be far longer than a `BigInteger` can hold -- `CAST('9'*40 AS BIGINT)`
raises "bigint out of range" on PostgreSQL, which aborted the ENTIRE
pass (including the other two kinds and the purge, already completed)
for a row that then repeats identically every run: the same permanent
wedge the exclusion exists to close, reached through digits that are
valid but too long. The length bound is part of the SAME predicate used
for the exclusion and the cast, not a separate check that could drift
from it.

Reopening contract (round 5 blocking findings 2 and 3 -- decided
together, this is an operational dashboard someone works from daily, per
the change's own scope, not a one-off trust exercise, so a divergence
that recurs must become visible again): the exclusion is VALUE-aware, not
merely EXISTENCE-aware. A candidate is skipped only when a matching row
already exists AND is either still actively tracked (`state` in `open`,
`acknowledged` -- no need to re-process something already on someone's
plate) OR closed (`resolved`/`ignored`) with UNCHANGED values (the
operator's call stands; re-selecting an identical, already-resolved
divergence every pass would consume a cap slot forever for no new
information). A closed row IS re-selected -- and reopened to `open`,
values and `detected_at` refreshed -- when its values changed.
`field_mismatch` has real values, so "changed" is a real comparison
(`ml_value`/`gbp_value` cast to text, same persistence-time
stringification as before). `missing_in_gbp`/`missing_in_ml` carry no
value (`ml_value`/`gbp_value` are always NULL) -- there is nothing that
could "change" to compare, so treating them the same way would mean a
closed row of these kinds is excluded FOREVER once resolved, which is
exactly finding 2's bug ("GBP loses the order again" -- and, structurally,
it can only become a candidate again after having left the candidate set
entirely, since the JOIN itself excludes an order that IS present in GBP;
regaining candidacy after that gap is inherently new information, not a
repeat of the original report). So for these two kinds the "unchanged"
branch is hardcoded false: a closed row is ALWAYS reopened on
rediscovery, an open/acknowledged one is never re-touched (same
progress-guarantee cost as before). `detected_at` therefore means
"first detected, or first detected since the last reopen" -- not "last
seen" (`out_of_window_update`/`window_not_enumerable` are unaffected,
different write path, `sweep_service.py`, genuinely "last seen").

Persistence (pre-push review finding 1, round 1 -- revised round 5): a
candidate can now legitimately correspond to an EXISTING (closed, about
to reopen) row, so `_apply_divergence` can no longer assume every
candidate is a fresh insert. Each detect function preloads the existing
rows matching ONLY this pass's (already-capped, already bounded by
`MAX_CANDIDATES_PER_KIND`) candidate order_ids -- one query per kind,
bounded by the cap, never by table size, and never one query per
candidate (the N+1 this whole chain started from). `_apply_divergence`
then mutates a preloaded row in place or stages a new one; a SECOND
candidate in the SAME batch resolving to the same key (GBP can hold two
headers whose `mlorder_id` differs only by padding, which the trimmed
join folds into one id) is skipped once the first one has been applied --
`_detect_field_mismatches` orders by `mlo_id DESC` so the first one
applied is deterministically the highest `mlo_id`, never an arbitrary
winner based on whatever order the database happens to return.
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
from app.models.ml_orders_ops import MlOpsDivergence, MlOrdersOps
from app.services.ml_orders_ingestion.sweep_service import UNENUMERABLE_KIND

logger = logging.getLogger(__name__)

MISSING_IN_GBP_KIND = "missing_in_gbp"
MISSING_IN_ML_KIND = "missing_in_ml"
FIELD_MISMATCH_KIND = "field_mismatch"

# States that mean "already closed, nothing left to do unless the facts
# changed" (round 5 reopening contract, module docstring).
_CLOSED_STATES = ("resolved", "ignored")

# Per-kind, per-pass cap (pre-push review finding 2, round 1). Generous
# enough that a healthy environment never hits it, small enough that a
# cold start cannot turn one detection pass into tens of thousands of
# writes. Safe to keep small: the exclusion filter (module docstring)
# guarantees a truncated pass's remainder is picked up next run, not lost.
MAX_CANDIDATES_PER_KIND = 5000

# `mlorder_id` is `String(50)` -- an all-digit value can still overflow a
# BigInteger (round 5 blocking finding 1). This is the same bound used by
# `_valid_numeric_gbp_order_id`'s predicate and its CAST, never a separate
# check that could drift out of sync with it.
_MAX_GBP_ORDER_ID_DIGITS = 18

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


def _valid_numeric_gbp_order_id(db: Session, col):
    """Dialect-aware, all-digits-after-trim check, WITH a length bound
    (round 5 blocking finding 1) -- this MUST run in SQL, not after the
    fetch, and MUST reject a digit run too long for `BigInteger` before
    anything casts it, or the cast itself raises and aborts the whole
    pass. Mirrors the `_insert_stmt` dialect-branch precedent used
    elsewhere in this package."""
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


def _preload_batch(
    db: Session, kind: str, field: Optional[str], order_ids
) -> Dict[Tuple[int, Optional[str]], MlOpsDivergence]:
    """ONE query per kind, scoped to THIS pass's already-capped candidate
    order_ids -- bounded by `MAX_CANDIDATES_PER_KIND`, never by table
    size, and never one query per candidate (module docstring
    "Persistence"). Needed because a candidate can now correspond to an
    existing, about-to-reopen row (round 5 reopening contract)."""
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
    doubles as the same-batch duplicate guard (round 2 finding 3): once a
    key has been applied (inserted OR updated), it is marked `True` in
    `existing`, so a second candidate in the SAME batch resolving to the
    same key (padded GBP `mlorder_id` duplicates) is silently skipped --
    the FIRST one applied wins, and callers that care about which one
    that is order their query accordingly. Returns True if a row was
    written (inserted or updated) -- used for the pass's reported
    counters."""
    key = (order_id, field)
    row = existing.get(key)
    if row is True:
        return False
    if isinstance(row, MlOpsDivergence):
        row.ml_value = ml_value
        row.gbp_value = gbp_value
        row.detected_at = now
        if row.state in _CLOSED_STATES:
            row.state = "open"
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


def _not_already_recorded(db: Session, kind: str, field: Optional[str], order_id_match, unchanged_match):
    """SQL exclusion (round 2 blocking finding 1, value-aware since round
    5 -- module docstring "Reopening contract"). A candidate is excluded
    only when a matching row exists that is either still actively
    tracked (`state` in `open`/`acknowledged`) or closed with UNCHANGED
    values (`unchanged_match`). `unchanged_match` is `false()` for the
    two value-less kinds, so a closed row of theirs is never treated as
    "unchanged" and is always reopened on rediscovery. `order_id_match`
    is the FULL boolean condition correlating `MlOpsDivergence.order_id`
    to the outer query's order id (callers differ on whether that needs a
    cast, e.g. `missing_in_ml` compares against GBP's text `mlorder_id`)
    -- passed as-is, never re-wrapped in another equality."""
    field_match = MlOpsDivergence.field == field if field is not None else MlOpsDivergence.field.is_(None)
    still_active = MlOpsDivergence.state.notin_(_CLOSED_STATES)
    return ~(
        db.query(MlOpsDivergence.id)
        .filter(
            MlOpsDivergence.kind == kind,
            field_match,
            order_id_match,
            (still_active | unchanged_match),
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
                db, MISSING_IN_GBP_KIND, None, MlOpsDivergence.order_id == MlOrdersOps.order_id, false()
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
    step left that could disagree with what SQL already decided (round 4
    blocking finding, extended round 5 for the length bound -- see
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
            _not_already_recorded(db, MISSING_IN_ML_KIND, None, MlOpsDivergence.order_id == numeric_order_id, false()),
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


def _detect_field_mismatches(db: Session, now: datetime, floor: datetime) -> Tuple[int, bool]:
    count = 0
    truncated = False
    for field_name, ml_col, gbp_col in _FIELD_MISMATCH_SPECS:
        # A closed row is "unchanged" (stays closed, module docstring
        # "Reopening contract") only if BOTH stored values still match
        # what this pass would write -- same stringification as
        # persistence itself, never a separate comparison rule.
        unchanged = and_(
            MlOpsDivergence.ml_value == cast(ml_col, String),
            MlOpsDivergence.gbp_value == cast(gbp_col, String),
        )
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
                    db,
                    FIELD_MISMATCH_KIND,
                    field_name,
                    MlOpsDivergence.order_id == MlOrdersOps.order_id,
                    unchanged,
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
        order_ids = [order_id for order_id, _ml, _gbp in rows]
        existing = _preload_batch(db, FIELD_MISMATCH_KIND, field_name, order_ids)
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
    instrumentation that already stopped being actionable. `UNENUMERABLE_KIND`
    is imported from `sweep_service.py` (round 5 minor finding), not
    re-typed -- that kind belongs to the sweep, this module only cleans
    up after it."""
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
