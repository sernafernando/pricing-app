"""Daily billing sweep (ml-ventas-desglose-costos, corte 3).

Downloads the ML billing period once a day and upserts every charge via
`upsert_billing_charge` (corte 2). Flag-gated (`ML_BILLING_ENABLED`,
default OFF): with the flag off this is a complete no-op, same
`PROMOS_WRITE_ENABLED` precedent as the rest of the app.

Hard constraint (investigation §3): ML's billing API enforces a rate limit
of 5 requests/minute PER ACCOUNT, shared with promos/PxQ/everything else --
NOT per endpoint. Consulting billing per-order would starve the account's
whole billing budget. The only safe pattern is downloading the full period
once a day, paginated, spaced >=15s apart (well under 4 requests/minute),
and reconciling by `order_id` afterwards (later cuts).

Lock reuse: this sweep is a SEPARATE cursor (`cursor_name='billing'`) on
the SAME lock/cursor machinery as `ml_orders_ingestion/sweep_service.py`
(`try_acquire_run_lock`/`load_cursor`/`ensure_cursor_row`/
`release_lock_as_*`), imported rather than re-implemented -- an
overlapping cron invocation of the ORDERS sweep and this billing sweep
never contend, because each holds its own row.

ASSUMPTION -- NOT YET CONFIRMED BY THE USER: temporal scope is ONLY the
currently OPEN billing period (computed locally from the 17th-to-16th
period boundary, investigation §3 -- no extra request to
`get_billing_periods` needed), re-swept ENTIRELY every day. There is no
backfill of closed periods and no separate lag window: idempotent upsert
on `detail_id` makes a full daily re-sweep of the open period free, and
that subsumes the measured billing lag (median 1h, 99.5% within 24h, 100%
within 48h) without a dedicated overlap window.

`documents.count_details` (investigation §3 open discrepancy: 18,414 vs
18,743, a 329 difference with no known explanation) is persisted as an
OBSERVATION on `MlBillingPeriodStat` and is NEVER treated as an alarm or
raised as an exception -- doing so would produce a false alarm every
single day.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects import postgresql, sqlite

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_billing import MlBillingCharge, MlBillingPeriodStat
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import MappingError, map_billing_detail
from app.services.ml_orders_ingestion.sweep_service import (
    ensure_cursor_row,
    release_lock_as_error,
    release_lock_as_idle,
    try_acquire_run_lock,
)
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

CURSOR_NAME = "billing"
BILLING_GROUP = "ML"
PAGE_LIMIT = 1000
# The proxy itself throttles to 1 call/15s and returns 429 without going to
# ML (investigation §3). Spacing our own requests at the same floor keeps
# us under the account's 5/minute ceiling with margin, instead of relying
# on the proxy to reject us.
REQUEST_SPACING_SECONDS = 15.0


@dataclass
class BillingSweepResult:
    ran: bool
    period_key: Optional[str] = None
    charges_seen: int = 0
    charges_upserted: int = 0
    charges_mapping_error: int = 0
    stopped_early: bool = False
    error: Optional[str] = None


def _current_open_period_key(now: datetime) -> str:
    """ML billing periods run from the 17th of a month to the 16th of the
    next, named by the period's END month (investigation §3: the period
    covering 17/08-16/09 is keyed `"2026-09-01"`). Computed locally instead
    of calling `get_billing_periods` -- one fewer request against the
    5/minute account-wide billing budget every single day."""
    if now.day <= 16:
        year, month = now.year, now.month
    else:
        year, month = now.year, now.month + 1
        if month > 12:
            year += 1
            month = 1
    return f"{year:04d}-{month:02d}-01"


def _insert_stmt(db, table):
    """Same dialect pick as `ml_billing_ingestion/ingestion_service.py`."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(table)
    return postgresql.insert(table)


def _upsert_period_stat(
    db,
    period_key: str,
    reported_total: Optional[int],
    stored_total: int,
    documents_count_details: Optional[int],
    swept_at: datetime,
) -> None:
    """Upserts on `period_key` -- requires the unique constraint added by
    this cut's migration (corte 1 left `ml_billing_period_stats` without
    one, deliberately, since it had no writer yet)."""
    values = {
        "period_key": period_key,
        "reported_total": reported_total,
        "stored_total": stored_total,
        "documents_count_details": documents_count_details,
        "swept_at": swept_at,
    }
    stmt = _insert_stmt(db, MlBillingPeriodStat.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "period_key"}
    stmt = stmt.on_conflict_do_update(index_elements=["period_key"], set_=update_cols)
    db.execute(stmt)


def run_billing_sweep(group: str = BILLING_GROUP) -> BillingSweepResult:
    """Entry point for the cron sweep (`app/scripts/sync_ml_billing.py`).

    Flag-gated: a complete no-op (zero HTTP calls, zero DB writes/reads)
    while `ML_BILLING_ENABLED` is False.
    """
    if not settings.ML_BILLING_ENABLED:
        return BillingSweepResult(ran=False)

    now = datetime.now(timezone.utc)
    period_key = _current_open_period_key(now)

    with get_background_db() as db:
        ensure_cursor_row(db, cursor_name=CURSOR_NAME)
        acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME)
        if not acquired:
            logger.info("sync_ml_billing: another billing sweep run is already in flight, skipping this pass")
            return BillingSweepResult(ran=False, error="already running", period_key=period_key)
        db.commit()

    result = BillingSweepResult(ran=True, period_key=period_key)

    try:
        with get_background_db() as db:
            offset = 0
            total: Optional[int] = None
            first_request = True

            while True:
                if not first_request:
                    time.sleep(REQUEST_SPACING_SECONDS)
                first_request = False

                page = resolve_maybe_async(
                    ml_webhook_client.get_billing_details(period_key, group, limit=PAGE_LIMIT, offset=offset)
                )
                if page is None:
                    # A 429 (proxy throttle) and a genuine transport error
                    # both surface as None here -- either way, the correct
                    # move is the SAME: stop this pass, log it, and let
                    # tomorrow's cron try again. NOT an immediate retry:
                    # retrying immediately is exactly the access pattern
                    # that burns the account's shared 5/minute budget.
                    logger.error(
                        "sync_ml_billing: get_billing_details failed (period=%s, group=%s, offset=%s) "
                        "-- stopping this pass, no retry",
                        period_key,
                        group,
                        offset,
                    )
                    result.stopped_early = True
                    result.error = "billing details request failed"
                    break

                paging = page.get("paging") or {}
                page_total = paging.get("total")
                if isinstance(page_total, int):
                    total = page_total

                raw_results = list(page.get("results") or [])
                for raw in raw_results:
                    result.charges_seen += 1
                    mapped = map_billing_detail(raw, period_key)
                    if isinstance(mapped, MappingError):
                        result.charges_mapping_error += 1
                        logger.warning("sync_ml_billing: mapping error (period=%s): %s", period_key, mapped.reason)
                        continue
                    upsert_billing_charge(db, mapped)
                    result.charges_upserted += 1

                db.commit()

                offset += len(raw_results)
                if not raw_results or (total is not None and offset >= total):
                    break

            if not result.stopped_early:
                documents_count_details: Optional[int] = None
                documents = resolve_maybe_async(ml_webhook_client.get_billing_documents(period_key, group))
                if documents is not None:
                    documents_count_details = sum(
                        int(doc.get("count_details") or 0)
                        for doc in (documents.get("documents") or [])
                        if isinstance(doc, dict)
                    )
                    if total is not None and documents_count_details != total:
                        # OBSERVATION only -- see module docstring. Never
                        # raised, never blocks, never marks the pass as an
                        # error.
                        logger.info(
                            "sync_ml_billing: documents.count_details=%s differs from details.paging.total=%s "
                            "(period=%s) -- known open discrepancy, recorded as observation only",
                            documents_count_details,
                            total,
                            period_key,
                        )

                stored_total = db.query(MlBillingCharge).filter_by(period_key=period_key).count()
                _upsert_period_stat(
                    db,
                    period_key=period_key,
                    reported_total=total,
                    stored_total=stored_total,
                    documents_count_details=documents_count_details,
                    swept_at=now,
                )
                db.commit()
    except Exception as e:  # noqa: BLE001 -- fail-closed: release the lock as errored, never leave it stuck
        release_lock_as_error(e, cursor_name=CURSOR_NAME)
        result.error = str(e)
        return result

    release_lock_as_idle(now, complete=not result.stopped_early, cursor_name=CURSOR_NAME)
    return result
