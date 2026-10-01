"""Fill and heal `ml_product_daily_metrics` from source (ODD
`metricas-ml-tablero` T2).

The worker keeps the rollup current for every sale it (re)stores from now
on; history from before the table existed -- and any bucket that drifted --
only gets there through this script. It walks every (MLA, day) bucket that
either has a sale (an accredited group, `ml_group_metrics.group_date`) or
has a stored row, and rewrites only the buckets whose stored rows differ
from source (`rollup.stale_buckets`), with the SAME writer the worker uses
(`rollup.refresh_rollup`). Idempotent: a second run writes nothing.

    python -m app.scripts.backfill_ml_daily_metrics --dry-run   # cuántos buckets cambiarían
    python -m app.scripts.backfill_ml_daily_metrics             # hacerlo, entero

Same reporting discipline as `backfill_group_date_accreditation.py`:
`examined` = buckets scanned, `written` = buckets rewritten, `remaining` =
a FULL re-scan after the run of buckets that still differ. A non-zero
`remaining` on a real run is a loud NOT DONE warning.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.ml_daily_metrics import MlProductDailyMetrics  # noqa: E402
from app.models.ml_group_metrics import MlGroupMetrics  # noqa: E402
from app.models.ml_orders_ops import MlOrderItemOps  # noqa: E402
from app.services.ml_daily_metrics.rollup import business_day, refresh_rollup, stale_buckets  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
_ORDER_CHUNK = 5000

Bucket = Tuple[str, date]


def all_buckets(db) -> List[Bucket]:
    """Every (MLA, day) bucket with a sale or a stored row, sorted by day so
    a batch touches few days."""
    day_of_order: Dict[int, date] = {}
    for group_date, members in db.query(MlGroupMetrics.group_date, MlGroupMetrics.member_order_ids).filter(
        MlGroupMetrics.group_date.isnot(None)
    ):
        day = business_day(group_date)
        for order_id in members or ():
            day_of_order[int(order_id)] = day

    buckets: Set[Bucket] = set()
    order_ids = list(day_of_order)
    for start in range(0, len(order_ids), _ORDER_CHUNK):
        chunk = order_ids[start : start + _ORDER_CHUNK]
        for order_id, mla in db.query(MlOrderItemOps.order_id, MlOrderItemOps.item_id).filter(
            MlOrderItemOps.order_id.in_(chunk)
        ):
            buckets.add((mla, day_of_order[order_id]))
    buckets.update(db.query(MlProductDailyMetrics.mla, MlProductDailyMetrics.day).distinct())
    return sorted(buckets, key=lambda b: (b[1], b[0]))


def _batches(buckets: List[Bucket], batch_size: int) -> List[List[Bucket]]:
    """Batches of buckets grouped by day (one source query per batch)."""
    by_day: Dict[date, List[Bucket]] = defaultdict(list)
    for bucket in buckets:
        by_day[bucket[1]].append(bucket)
    batches: List[List[Bucket]] = []
    current: List[Bucket] = []
    for day in sorted(by_day):
        current.extend(by_day[day])
        if len(current) >= batch_size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches


def count_remaining(db, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """FULL re-scan: buckets whose stored rows still differ from source."""
    return sum(len(stale_buckets(db, batch)) for batch in _batches(all_buckets(db), batch_size))


def run_backfill(dry_run: bool, limit: Optional[int] = None, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    db = SessionLocal()
    result = {"examined": 0, "written": 0, "remaining": 0}
    try:
        buckets = all_buckets(db)
        result["examined"] = len(buckets)
        if dry_run:
            result["remaining"] = count_remaining(db, batch_size)
            return result

        for batch in _batches(buckets, batch_size):
            if limit is not None and result["written"] >= limit:
                break
            stale = stale_buckets(db, batch)
            if limit is not None:
                stale = set(sorted(stale)[: limit - result["written"]])
            if stale:
                refresh_rollup(db, stale)
                db.commit()
            result["written"] += len(stale)

        # Counted AFTER the writes: what this run actually left behind.
        result["remaining"] = count_remaining(db, batch_size)
        return result
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after rewriting this many buckets. For a cautious first pass; the run then reports remaining > 0.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="Report how many buckets WOULD change; write nothing.")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    result = run_backfill(dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size)
    logger.info(
        "backfill_ml_daily_metrics: complete (dry_run=%s) -- examined=%s written=%s remaining=%s",
        args.dry_run,
        result["examined"],
        result["written"],
        result["remaining"],
    )
    if result["remaining"] and not args.dry_run:
        # Loud on purpose: a backfill that stopped early must never look the
        # same as one that finished.
        logger.warning(
            "backfill_ml_daily_metrics: NOT DONE -- %s buckets still differ from source. Run again (without --limit).",
            result["remaining"],
        )


if __name__ == "__main__":
    main()
