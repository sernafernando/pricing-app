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
  6. The watermark advances ONLY after every affected item processed
     successfully this run, to the max `updated_at` seen in the batch. If
     ANY item fails, the watermark is left untouched so next run retries the
     whole batch — safe because `recompute_item` is idempotent.

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

from app.core.config import settings  # noqa: E402
from app.core.database import get_background_db, get_mlwebhook_engine  # noqa: E402
from app.models.promo_sync_watermark import get_watermark, set_watermark  # noqa: E402
from app.models.publicacion_ml import PublicacionML  # noqa: E402
from app.services.promo_price_propagation import recompute_item  # noqa: E402

logger = logging.getLogger(__name__)


def _fetch_newly_active_rows(watermark: Optional[datetime]) -> List[Tuple[str, datetime]]:
    """ONE cross-DB query: (mla, updated_at) for every `ml_item_promotions`
    row that became active (candidate|started) since `watermark`. If
    `watermark` is None (first-ever run), every currently-active row is
    returned."""
    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT mla, updated_at
                FROM ml_item_promotions
                WHERE status IN ('candidate', 'started')
                  AND (:watermark IS NULL OR updated_at > :watermark)
            """),
            {"watermark": watermark},
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _map_activation_by_item(db, rows: List[Tuple[str, datetime]]) -> Dict[int, datetime]:
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

    max_seen = max(updated_at for _, updated_at in rows)

    had_failure = False
    for item_id, activation_time in activation_by_item.items():
        try:
            with get_background_db() as db:
                recompute_item(db, item_id, now=activation_time)
        except Exception:
            had_failure = True
            logger.exception(
                "sync_promo_prices: recompute_item failed for item_id=%s (isolated — other items still processed)",
                item_id,
            )

    if had_failure:
        logger.warning(
            "sync_promo_prices: at least one item failed this run — watermark NOT advanced, "
            "next run retries the whole batch (recompute_item is idempotent)"
        )
        return

    with get_background_db() as db:
        set_watermark(db, max_seen)
    logger.info("sync_promo_prices: run complete — watermark advanced to %s", max_seen)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_sync()


if __name__ == "__main__":
    main()
