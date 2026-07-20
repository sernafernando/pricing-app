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
  2. Selects `promo_refresh_pending` rows where `due_at <= now()`.
  3. Each row is refreshed in its own short-lived `get_background_db()`
     session (never one session held across the whole batch — this repo
     had a DB-pool-exhaustion incident). A per-row failure is caught,
     logged, and does not abort the run or affect other rows.
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

from app.core.config import settings  # noqa: E402
from app.core.database import get_background_db  # noqa: E402
from app.models.promo_refresh_pending import PromoRefreshPending  # noqa: E402
from app.services.ml_promotions_write_service import REFRESH_RETRY_DELAY_SECONDS, _resolve  # noqa: E402
from app.services.ml_webhook_client import ml_webhook_client  # noqa: E402

logger = logging.getLogger(__name__)

# Attempt cap: after this many failed attempts a row is quarantined
# (DELETEd, loudly logged) rather than retried forever.
MAX_REFRESH_ATTEMPTS = 5


def _due_mlas(db) -> list:
    now = datetime.now(timezone.utc)
    return db.query(PromoRefreshPending).filter(PromoRefreshPending.due_at <= now).all()


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
    contract."""
    if not settings.PROMOS_WRITE_ENABLED:
        logger.info("drain_promo_refresh: PROMOS_WRITE_ENABLED is False — exiting without any read/write")
        return

    with get_background_db() as db:
        rows = _due_mlas(db)
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
