"""Cron sweep for the publication-link hybrid backfill
(productos-catalog-family-tree, PR1b).

Refreshes already-filled `ml_publication_links` rows on a slow cadence
(oldest `fetched_at` first, bounded batch), complementing PR2's lazy-fill
(fills on first product tree-expand) so warm rows stay fresh even for
products nobody has viewed recently.

DB-safety (mirrors `drain_promo_refresh.py` — this repo had a real
DB-pool-exhaustion incident from holding a session across an external
HTTP round-trip):
  0. A session-level `pg_try_advisory_lock` is acquired FIRST; if another
     sweep already holds it, this pass exits immediately (the cron runs
     every 4h but a slow pass — proxy down, per-batch pauses — can still
     be alive when the next fires, and two passes racing the same rows
     could leave `ml_item_relations` transiently empty via overlapping
     delete-then-insert). The lock connection (`lock_db`) is held for the
     whole pass but stays IDLE during the HTTP fetch — it runs no query
     across the round-trip, so the pool-exhaustion shape is still avoided.
  1. The due rows are read (oldest `fetched_at` first, capped at
     MAX_ROWS_PER_PASS) via the lock session.
  2. The HTTP fetch (`get_items_full_batch`, one batched call for the
     whole due set) happens with no read/write query in flight.
  3. Each row is then persisted in its OWN short-lived session
     (`_persist_one`), so a poison mla's DB error cannot hold a
     connection open or abort the rest of the batch.

Run:
    python app/scripts/sync_publication_links.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from datetime import datetime, timezone  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.core.database import get_background_db  # noqa: E402
from app.models.ml_publication_link import MlPublicationLink  # noqa: E402
from app.services.ml_publication_link_service import replace_relations, upsert_link  # noqa: E402
from app.services.ml_webhook_client import ml_webhook_client  # noqa: E402
from app.utils.async_bridge import resolve_maybe_async as _resolve  # noqa: E402

logger = logging.getLogger(__name__)

# Bound on how many stale rows a single pass refreshes, so a huge backlog
# cannot make one pass run unboundedly long / fetch unboundedly many items
# (and cannot hold the advisory lock indefinitely).
MAX_ROWS_PER_PASS = 200

# Constant advisory-lock key so only one sweep pass runs at a time. Distinct
# from drain_promo_refresh's key (84_217_001) so the two crons never contend.
_SWEEP_LOCK_KEY = 84_217_002


def _try_acquire_sweep_lock(db) -> bool:
    """Session-level Postgres advisory lock so overlapping sweep passes cannot
    both process the same due rows. Released automatically when the session
    closes (end of the `with get_background_db()` block in `run_sweep`)."""
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _SWEEP_LOCK_KEY}).scalar())


def _due_rows(db) -> List[MlPublicationLink]:
    """Already-filled rows ordered oldest-`fetched_at`-first, bounded."""
    return (
        db.query(MlPublicationLink)
        .order_by(MlPublicationLink.fetched_at.asc().nulls_first())
        .limit(MAX_ROWS_PER_PASS)
        .all()
    )


def _persist_one(mla: str, item_id: int, item_data: Dict) -> None:
    """Persists one refreshed row in its OWN short-lived session, mirroring
    `drain_promo_refresh._drain_one`'s per-item isolation. Never raises up
    to the caller — an unhandled error here must not abort the batch."""
    now = datetime.now(timezone.utc)
    with get_background_db() as db:
        upsert_link(db, mla, item_data, item_id, now)
        replace_relations(db, mla, item_data.get("item_relations") or [])
        db.commit()


def run_sweep() -> None:
    """Orchestrates one cron sweep pass. See module docstring for the
    full DB-safety contract (short-lived sessions, HTTP outside any
    session, per-row isolation)."""
    with get_background_db() as lock_db:
        if not _try_acquire_sweep_lock(lock_db):
            logger.info("sync_publication_links: another sweep already holds the lock — exiting")
            return

        rows = _due_rows(lock_db)
        if len(rows) == MAX_ROWS_PER_PASS:
            logger.warning(
                "sync_publication_links: stale backlog hit the %s-row cap this pass "
                "(oldest-fetched_at-first; the rest refresh next pass)",
                MAX_ROWS_PER_PASS,
            )
        # mla -> item_id, captured while the session is open — the HTTP
        # fetch below runs no query on lock_db (it only holds the lock).
        item_id_by_mla = {row.mla: row.item_id for row in rows}

        mlas = list(item_id_by_mla.keys())
        if not mlas:
            return

        fetched = _resolve(ml_webhook_client.get_items_full_batch(mlas)) or {}
        persisted = 0
        for mla, item_data in fetched.items():
            try:
                _persist_one(mla, item_id_by_mla[mla], item_data)
                persisted += 1
            except Exception:
                # Per-item isolation: one poison mla must never abort the batch.
                logger.error("sync_publication_links: unhandled error persisting mla=%s", mla, exc_info=True)

        logger.info(
            "sync_publication_links: pass complete — due=%s persisted=%s proxy_omitted=%s",
            len(mlas),
            persisted,
            len(mlas) - len(fetched),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_sweep()


if __name__ == "__main__":
    main()
