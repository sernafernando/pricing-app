"""One-off backfill: queue every active catalog listing that never had a catalog-competition snapshot.

Run once after deploy (owner decision, 2026-11-16). It only fills the existing queue
(`catalog_competition_refresh_pending`); the `ml_publications.catalog_competition_refresh` worker drains it at its
own rate (`catalog_competition_refresh.rate_per_min`), so no ML call is made here.

Entries are spaced `--spacing-seconds` apart (default: one per worker slot at 10/min), so the backlog never sits in
front of a live change: the worker claims by due time and a change-driven entry slots in between.

Resumable and idempotent: a listing already queued or already consulted is skipped, so it can be stopped and run
again. `--dry-run` only counts.

    cd /srv/apps/pricing-app/backend && venv/bin/python -m app.scripts.catalog_competition_backfill --dry-run
    cd /srv/apps/pricing-app/backend && venv/bin/python -m app.scripts.catalog_competition_backfill
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import exists
from sqlalchemy.orm import Session

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending
from app.models.ml_catalog_competition import MLCatalogCompetition
from app.models.ml_publications import MlItem
from app.services import catalog_competition_refresh_queue as queue

logger = logging.getLogger(__name__)

DEFAULT_SPACING_SECONDS = 6.0
CHUNK = 500


def never_consulted(db: Session, limit: Optional[int] = None) -> list[str]:
    """Active catalog listings with no snapshot and not already queued, in a stable order."""
    query = (
        db.query(MlItem.item_id)
        .filter(
            MlItem.catalog_listing.is_(True),
            MlItem.status == "active",
            ~exists().where(MLCatalogCompetition.mla == MlItem.item_id),
            ~exists().where(CatalogCompetitionRefreshPending.mla == MlItem.item_id),
        )
        .order_by(MlItem.item_id)
    )
    if limit is not None:
        query = query.limit(limit)
    return [item_id for (item_id,) in query]


def enqueue_never_consulted(
    db: Session,
    now: datetime,
    *,
    spacing_seconds: float = DEFAULT_SPACING_SECONDS,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> int:
    """Queue the never-consulted listings spaced from `now`; returns how many (would be) queued.

    A spacing of 0 or less would make the whole backlog due at once, ahead of every live change: refused."""
    if spacing_seconds <= 0:
        raise ValueError("spacing_seconds must be greater than 0")
    mlas = never_consulted(db, limit)
    if dry_run or not mlas:
        return len(mlas)
    for start in range(0, len(mlas), CHUNK):
        chunk = mlas[start : start + CHUNK]
        queue.enqueue_debounced(
            db, [(mla, now + timedelta(seconds=spacing_seconds * (start + i))) for i, mla in enumerate(chunk)]
        )
        db.commit()
    return len(mlas)


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--spacing-seconds must be a number, got {value!r}") from None
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"--spacing-seconds must be greater than 0, got {value}")
    return seconds


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spacing-seconds", type=_positive_seconds, default=DEFAULT_SPACING_SECONDS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        count = enqueue_never_consulted(
            db,
            datetime.now(timezone.utc),
            spacing_seconds=args.spacing_seconds,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        db.close()
    hours = count * args.spacing_seconds / 3600
    verb = "would queue" if args.dry_run else "queued"
    logger.info("catalog competition backfill: %s %s listings (last due in ~%.1f h)", verb, count, hours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
