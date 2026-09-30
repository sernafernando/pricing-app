"""Backfill `ml_group_metrics.group_date` onto the accreditation basis
(ODD `ventas-ml-dia-por-acreditacion`, decision 2026-09-30 --
`odd/tasks/ventas-ml-dia-por-acreditacion.md`).

WHY THIS IS NOT OPTIONAL: every one of the 77,521 existing `ml_group_metrics`
rows carries a `group_date` computed under the OLD basis (`MIN(date_created)`
across members). The day filter (`ml_sales_query/filters.py`) and
`_group_date` (`ml_group_metrics/compute.py`) now both read the SAME column
under the NEW basis (`MAX(date_approved)` over each group's RELEVANT
payments, across all members -- see `ml_sales_query/accreditation.py`'s
module docstring for the full rule). Nothing recomputes a stored group's
`group_date` on its own unless one of its members' OWN metrics changes
(the ordinary `store_order_metrics` -> `recompute_group_metrics` hook), so
every historical group's day stays wrong -- silently -- until this runs.

    python -m app.scripts.backfill_group_date_accreditation --dry-run   # cuántas filas cambiarían
    python -m app.scripts.backfill_group_date_accreditation             # hacerlo, entero

Same reporting discipline as `backfill_ml_group_metrics.py`: `remaining` is
a FULL re-scan (never trusted from `--limit`'s own pass) of how many rows
STILL disagree with the accreditation basis after this run, and a non-zero
`remaining` on a real run is a loud WARNING -- a partial run must never look
like a complete one.

Only UPDATEs `group_date` on a row whose recomputed value actually differs
from what is stored -- idempotent, safe to re-run, and never touches any
other column (`neto`/`total_gauss`/etc. are `recompute_group_metrics`'s
job, not this script's -- a full Gauss recompute is a heavier, unrelated
operation this migration does not need).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.ml_sales_query.accreditation import member_accreditation_dates  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500

_GroupRow = Tuple[List[int], object]


def _all_group_keys(db, limit: Optional[int]) -> List[str]:
    sql = "SELECT group_key FROM ml_group_metrics ORDER BY group_key"
    if limit is not None:
        sql = f"{sql} LIMIT {int(limit)}"
    return [row[0] for row in db.execute(text(sql)).all()]


def _members_and_current(db, group_keys: List[str]) -> Dict[str, _GroupRow]:
    """`group_key -> (member_order_ids, currently stored group_date)` for
    exactly the requested keys -- ONE query per batch, never per group."""
    if not group_keys:
        return {}
    rows = db.execute(
        text("SELECT group_key, member_order_ids, group_date FROM ml_group_metrics WHERE group_key = ANY(:keys)"),
        {"keys": list(group_keys)},
    ).all()
    return {row.group_key: (list(row.member_order_ids or []), row.group_date) for row in rows}


def _recomputed_group_dates(db, groups: Dict[str, _GroupRow]) -> Dict[str, object]:
    """The SAME resolver `ml_group_metrics/compute.py::_group_date` uses
    (`member_accreditation_dates`, bulk-fetched once for the whole batch --
    never a per-group query)."""
    all_order_ids = sorted({oid for members, _current in groups.values() for oid in members})
    accreditation_by_order = member_accreditation_dates(db, all_order_ids)
    result: Dict[str, object] = {}
    for group_key, (members, _current) in groups.items():
        fechas = [accreditation_by_order[oid] for oid in members if oid in accreditation_by_order]
        result[group_key] = max(fechas) if fechas else None
    return result


def _changed_keys(groups: Dict[str, _GroupRow], recomputed: Dict[str, object]) -> List[str]:
    return [group_key for group_key, (_members, current) in groups.items() if recomputed[group_key] != current]


def count_remaining(db, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Full-table scan: how many rows STILL disagree with the accreditation
    basis. This is what makes a partial run visible -- same rationale as
    `backfill_ml_group_metrics.py::count_missing_groups`."""
    all_keys = _all_group_keys(db, None)
    remaining = 0
    for inicio in range(0, len(all_keys), batch_size):
        lote = all_keys[inicio : inicio + batch_size]
        groups = _members_and_current(db, lote)
        recomputed = _recomputed_group_dates(db, groups)
        remaining += len(_changed_keys(groups, recomputed))
    return remaining


def run_backfill(limit: Optional[int], dry_run: bool, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    db = SessionLocal()
    resultado = {"examined": 0, "written": 0, "unchanged": 0, "remaining": 0}
    try:
        if dry_run:
            # The WHOLE pending set, not what a limited pass would touch --
            # same discipline `backfill_ml_group_metrics.py` applies.
            resultado["remaining"] = count_remaining(db, batch_size)
            resultado["examined"] = resultado["remaining"]
            logger.info("backfill_group_date_accreditation: %s rows WOULD change, dry run", resultado["remaining"])
            return resultado

        group_keys = _all_group_keys(db, limit)
        resultado["examined"] = len(group_keys)

        for inicio in range(0, len(group_keys), batch_size):
            lote = group_keys[inicio : inicio + batch_size]
            groups = _members_and_current(db, lote)
            recomputed = _recomputed_group_dates(db, groups)
            changed = _changed_keys(groups, recomputed)
            for group_key in changed:
                db.execute(
                    text("UPDATE ml_group_metrics SET group_date = :d WHERE group_key = :k"),
                    {"d": recomputed[group_key], "k": group_key},
                )
            db.commit()
            resultado["written"] += len(changed)
            resultado["unchanged"] += len(lote) - len(changed)

        # Counted AFTER the writes, so it reflects what this run actually
        # left behind. Non-zero means the job is NOT done: run it again.
        resultado["remaining"] = count_remaining(db, batch_size)
        return resultado
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many rows. For a cautious first pass; the run then reports remaining > 0.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows WOULD change; write nothing.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    resultado = run_backfill(limit=args.limit, dry_run=args.dry_run, batch_size=args.batch_size)
    logger.info(
        "backfill_group_date_accreditation: complete (dry_run=%s) -- examined=%s written=%s unchanged=%s remaining=%s",
        args.dry_run,
        resultado["examined"],
        resultado["written"],
        resultado["unchanged"],
        resultado["remaining"],
    )
    if resultado["remaining"] and not args.dry_run:
        # Loud on purpose: a backfill that stopped early must never look the
        # same as one that finished.
        logger.warning(
            "backfill_group_date_accreditation: NOT DONE -- %s rows still on the old basis. "
            "Run again (without --limit).",
            resultado["remaining"],
        )


if __name__ == "__main__":
    main()
