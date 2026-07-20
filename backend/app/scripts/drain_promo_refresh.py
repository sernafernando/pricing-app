"""Retry drainer for the promo point-refresh queue
(promo-state-dynamic-refresh, backend slice).

Complements the panel enroll/remove hook's immediate best-effort refresh
(`_maybe_refresh_after_write` in `ml_promotions_write_service.py`) by
reliably retrying a server-side point-refresh of the `ml_item_promotions`
mirror ~60s later, so slower-consistency writes (SMART, ~10-18s) still get
freshened even if the operator closed the panel or a process restarted.

Mechanism (mirrors `sync_promo_prices.py`'s kill-switch-first +
short-lived-session + per-item-isolation shape):
  1. Kill-switch (`settings.PROMOS_WRITE_ENABLED`) checked FIRST, before
     any read/write.
  2. Selects `promo_refresh_pending` rows where `due_at <= now()`,
     oldest-due-first, capped at MAX_ROWS_PER_PASS.
  3. Sessions: ONE dedicated connection holds the advisory lock for the
     whole pass — that is unavoidable, the lock is session-level, so
     releasing the session drops the lock. But the actual per-row refresh
     work runs in SEPARATE short-lived `get_background_db()` sessions, and
     the ml-webhook HTTP call happens OUTSIDE any DB session (this repo had
     a DB-pool-exhaustion incident from holding a session across external
     HTTP). So at most one extra connection (the lock) is held across the
     batch and no session is ever pinned during HTTP. A per-row failure is
     caught, logged, and does not abort the run or affect other rows.
  4. On success: DELETE the row. On failure: attempts += 1, due_at pushed
     back by another `REFRESH_RETRY_DELAY_SECONDS`; once attempts reach
     `MAX_REFRESH_ATTEMPTS` the row is QUARANTINED (DELETE + loud
     `logger.error`) — the 3x/day backfill remains the ultimate fallback.

Run:
    python app/scripts/drain_promo_refresh.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

# Cargar variables de entorno desde .env
from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import get_background_db  # noqa: E402
from app.models.promo_refresh_pending import PromoRefreshPending  # noqa: E402
from app.services.ml_promotions_write_service import REFRESH_RETRY_DELAY_SECONDS  # noqa: E402
from app.services.ml_webhook_client import ml_webhook_client  # noqa: E402
from app.utils.async_bridge import resolve_maybe_async as _resolve  # noqa: E402

logger = logging.getLogger(__name__)

# Attempt cap: after this many failed attempts a row is quarantined
# (DELETEd, loudly logged) rather than retried forever.
MAX_REFRESH_ATTEMPTS = 5

# Concurrency control: a constant advisory-lock key so only one drain pass
# can run at a time (the cron runs every minute; a slow pass — mlwebhook
# down, 10s timeout x rows — can still be alive when the next one starts,
# double-incrementing `attempts` for the same due mlas).
_DRAIN_LOCK_KEY = 84_217_001

# Bound on how many due rows a single pass processes, so a huge backlog
# cannot make one pass run unboundedly long (and hold the advisory lock
# indefinitely).
MAX_ROWS_PER_PASS = 100


def _try_acquire_drain_lock(db) -> bool:
    """Attempts a session-level Postgres advisory lock so overlapping
    drain passes cannot both process the same due rows. The lock is
    released automatically when the session/connection closes (end of the
    `with get_background_db()` block)."""
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _DRAIN_LOCK_KEY}).scalar())


def _due_mlas(db) -> list:
    # oldest-due-first: a LIMIT without ORDER BY is non-deterministic in
    # Postgres, so a persistent >100-row backlog could starve the same rows
    # pass after pass. Ordering by due_at guarantees forward progress.
    now = datetime.now(timezone.utc)
    return (
        db.query(PromoRefreshPending)
        .filter(PromoRefreshPending.due_at <= now)
        .order_by(PromoRefreshPending.due_at)
        .limit(MAX_ROWS_PER_PASS)
        .all()
    )


def _drain_one(mla: str) -> None:
    """Refreshes a single mla in its own short-lived session, mirroring
    `sync_promo_prices._recompute_item_with_retries`'s per-item isolation.
    Never raises: any error here must not abort the batch."""
    try:
        ok = _resolve(ml_webhook_client.refresh_item_promotions(mla))
    except Exception:
        logger.warning("drain_promo_refresh: refresh_item_promotions raised for mla=%s", mla, exc_info=True)
        ok = False

    with get_background_db() as db:
        row = db.query(PromoRefreshPending).filter(PromoRefreshPending.mla == mla).first()
        if row is None:
            return

        if ok:
            db.delete(row)
            db.commit()
            return

        row.attempts += 1
        if row.attempts >= MAX_REFRESH_ATTEMPTS:
            logger.error(
                "drain_promo_refresh: mla=%s QUARANTINED after %s attempts — "
                "will re-freshen via the next webhook/backfill cycle",
                mla,
                row.attempts,
            )
            db.delete(row)
        else:
            row.due_at = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_RETRY_DELAY_SECONDS)
        db.commit()


def run_drain() -> None:
    """Orchestrates one drain pass. See module docstring for the full
    contract.

    Concurrency: a session-level `pg_try_advisory_lock` is acquired FIRST
    (before any read) and held for the lifetime of this call (released
    automatically when its session closes at function return) so an
    overlapping pass — the cron runs every minute; a slow pass can still be
    alive when the next starts — exits immediately instead of racing the
    same due rows (which would double-increment `attempts` and duplicate
    the outbound HTTP refresh)."""
    if not settings.PROMOS_WRITE_ENABLED:
        logger.info("drain_promo_refresh: PROMOS_WRITE_ENABLED is False — exiting without any read/write")
        return

    with get_background_db() as lock_db:
        if not _try_acquire_drain_lock(lock_db):
            logger.info("drain_promo_refresh: another pass already holds the drain lock — exiting")
            return

        rows = _due_mlas(lock_db)
        if len(rows) == MAX_ROWS_PER_PASS:
            logger.warning(
                "drain_promo_refresh: due backlog hit the %s-row cap this pass "
                "(oldest-due-first; the rest drain next pass)",
                MAX_ROWS_PER_PASS,
            )
        mlas = [row.mla for row in rows]

        if not mlas:
            return

        for mla in mlas:
            try:
                _drain_one(mla)
            except Exception:
                # Per-item isolation: one poison mla must never abort the batch.
                logger.error("drain_promo_refresh: unhandled error draining mla=%s", mla, exc_info=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_drain()


if __name__ == "__main__":
    main()
