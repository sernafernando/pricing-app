"""
Periodic promo-price sync job (SDD promo-price-propagation, slice 4).

Complements the panel enroll/remove hook (slice 3, `ml_promotions_write_service`)
by picking up promos that became active WITHOUT going through this app's own
enroll flow (e.g. promos created directly in ML's Centro de Promociones).

Mechanism (design #937, MUST-RESOLVE #2):
  1. Kill-switch (`settings.PROMOS_WRITE_ENABLED`) is checked FIRST, before
     any read (cross-DB or otherwise) — a disabled kill-switch must not even
     touch `ml_item_promotions`.
  2. A persisted watermark (`promo_sync_watermark`) tracks the last
     `ml_item_promotions.updated_at` fully processed. Each run selects the
     NEWLY-ACTIVE rows (`updated_at > watermark AND status IN
     ('candidate','started')`) in ONE cross-DB query — this single query is
     the batching, never a per-item read.
  3. Affected MLAs are mapped to `item_id` via `PublicacionML` and deduped.
  4. For each affected item, `recompute_item(db, item_id, now=activation_time)`
     is called (slice 3's core, unchanged) where `activation_time` is the MAX
     `updated_at` among that item's newly-active rows in this batch — NOT
     wall-clock now. This is what lets `recompute_item`'s last-write-wins
     guard freeze a manual edit made AFTER the promo activated.
  5. Each item is processed in its own short-lived `get_background_db()`
     session (never one session held across the whole batch — this repo had
     a DB-pool-exhaustion incident). A per-item failure is caught, logged,
     and does not abort the run or corrupt other items.
  6. Each item gets a small bounded number of in-run retries (self-heals
     transient blips within the same run). After that, the watermark
     advances to the max `updated_at` seen in the batch AS SOON AS AT LEAST
     ONE item succeeded this run — a single poison item (deterministically
     failing) must never block the whole sync forever. Items that still
     fail after retries are QUARANTINED for this cycle (logged loudly with
     `logger.error`); their price re-propagates next time their promo row's
     `updated_at` changes, or via manual intervention. Only when EVERY
     affected item fails (a systemic outage, e.g. mlwebhook down) is the
     watermark withheld so the next run retries the whole batch — safe
     because `recompute_item` is idempotent.

Run:
    python app/scripts/sync_promo_prices.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

# Cargar variables de entorno desde .env
from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import get_background_db, get_mlwebhook_engine  # noqa: E402
from app.models.promo_sync_watermark import get_watermark, set_watermark  # noqa: E402
from app.models.publicacion_ml import PublicacionML  # noqa: E402
from app.services.promo_price_propagation import recompute_item  # noqa: E402

logger = logging.getLogger(__name__)

# Bounded in-run retries per item: 1 initial attempt + this many extra
# attempts, so a transient blip self-heals within the same run without
# stalling on external backoff.
MAX_ITEM_ATTEMPTS = 3


def _recompute_item_with_retries(item_id: int, activation_time: datetime) -> bool:
    """Attempts `recompute_item` for a single item up to `MAX_ITEM_ATTEMPTS`
    times, each in its own short-lived `get_background_db()` session.
    Returns True on success, False if every attempt failed."""
    for attempt in range(1, MAX_ITEM_ATTEMPTS + 1):
        try:
            with get_background_db() as db:
                recompute_item(db, item_id, now=activation_time)
            return True
        except Exception:
            logger.warning(
                "sync_promo_prices: recompute_item failed for item_id=%s (attempt %s/%s)",
                item_id,
                attempt,
                MAX_ITEM_ATTEMPTS,
                exc_info=True,
            )
    return False


def _fetch_newly_active_rows(watermark: Optional[datetime]) -> List[Tuple[str, datetime]]:
    """ONE cross-DB query: (mla, updated_at) for every `ml_item_promotions`
    row that became active (candidate|started) since `watermark`. If
    `watermark` is None (first-ever run), every currently-active row is
    returned."""
    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                -- DECISION (SDD promo-pending-and-price-matching, D2): deliberately
                -- NOT adding 'pending' here. A pending->started transition bumps
                -- updated_at and is already caught by the 'started' clause below,
                -- which is when the price actually matters; adding 'pending' would
                -- only trigger redundant no-op recomputes (recompute_item still
                -- hard-filters to 'started' per REQ-10).
                SELECT mla, updated_at
                FROM ml_item_promotions
                WHERE status IN ('candidate', 'started')
                  AND (:watermark IS NULL OR updated_at > :watermark)
            """),
            {"watermark": watermark},
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _map_activation_by_item(db: Session, rows: List[Tuple[str, datetime]]) -> Dict[int, datetime]:
    """Maps the affected MLAs to their `item_id` (PublicacionML, pricing DB)
    and dedupes to the distinct set of affected items, each with the MAX
    `updated_at` among its newly-active rows in this batch (the activation
    time `recompute_item`'s no-clobber-manual guard compares against)."""
    mlas = {mla for mla, _ in rows}
    if not mlas:
        return {}

    mla_to_item: Dict[str, int] = {
        mla: item_id
        for mla, item_id in db.query(PublicacionML.mla, PublicacionML.item_id).filter(PublicacionML.mla.in_(mlas)).all()
    }

    activation_by_item: Dict[int, datetime] = {}
    for mla, updated_at in rows:
        item_id = mla_to_item.get(mla)
        if item_id is None:
            continue
        current = activation_by_item.get(item_id)
        if current is None or updated_at > current:
            activation_by_item[item_id] = updated_at
    return activation_by_item


def run_sync() -> None:
    """Orchestrates one sync pass. See module docstring for the full
    contract."""
    if not settings.PROMOS_WRITE_ENABLED:
        logger.info("sync_promo_prices: PROMOS_WRITE_ENABLED is False — exiting without any read/write")
        return

    with get_background_db() as db:
        watermark = get_watermark(db)

    rows = _fetch_newly_active_rows(watermark)
    if not rows:
        logger.info("sync_promo_prices: no newly-active promo rows since watermark=%s — nothing to do", watermark)
        return

    with get_background_db() as db:
        activation_by_item = _map_activation_by_item(db, rows)

    if not activation_by_item:
        logger.info("sync_promo_prices: no affected items mapped this run — watermark unchanged")
        return

    max_seen = max(updated_at for _, updated_at in rows)

    quarantined: List[int] = []
    succeeded_count = 0
    for item_id, activation_time in activation_by_item.items():
        if _recompute_item_with_retries(item_id, activation_time):
            succeeded_count += 1
        else:
            quarantined.append(item_id)

    if succeeded_count == 0:
        logger.warning(
            "sync_promo_prices: ALL %s affected item(s) failed this run (systemic outage suspected) — "
            "watermark NOT advanced, next run retries the whole batch (recompute_item is idempotent)",
            len(activation_by_item),
        )
        return

    if quarantined:
        logger.error(
            "sync_promo_prices: item_id(s) %s QUARANTINED this cycle after %s attempts each — "
            "will re-propagate next time their promo row's updated_at changes, or via manual intervention",
            quarantined,
            MAX_ITEM_ATTEMPTS,
        )

    with get_background_db() as db:
        set_watermark(db, max_seen)
    logger.info(
        "sync_promo_prices: run complete — watermark advanced to %s (%s succeeded, %s quarantined)",
        max_seen,
        succeeded_count,
        len(quarantined),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_sync()


if __name__ == "__main__":
    main()
