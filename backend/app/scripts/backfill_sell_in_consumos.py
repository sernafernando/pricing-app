"""Backfill the sell-in allocation (`sell_in_consumos`, sell-in-sell-out T5).

Until T5 the `sell.drain` was inert: it acked queued sale lines without
computing anything. This script recomputes, through the active
`SellInCosting` strategy, every product that has sell-in purchase lines (any
state: a voided purchase's product must release its units) or stored
consumptions, so the allocation matches the sales as they are now. After it,
the drain keeps it current.

Idempotent: the strategy recomputes a product from scratch and writes only the
difference, so a re-run writes nothing. Bounded and resumable: keyset
pagination on `item_id`, one short session and one commit per batch (rolled
back under `--dry-run`, which still reports what would change); `--after-item`
(the `last_item_id` of a previous summary) skips what is done.

A product whose recompute fails is rolled back alone and listed in the
summary's `failed_items`; `--after-item` would skip it, so `--items` (a CSV of
item ids) reruns exactly those products and nothing else.

Run:
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_in_consumos --dry-run
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_in_consumos
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_in_consumos --items 2270,2964
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable, Iterable, List, Optional

backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=backend_path / ".env")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.sell_in.costing import get_costing  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200

_CANDIDATES_SQL = text(
    """
SELECT item_id FROM (
    SELECT item_id FROM sell_in_compra_items
    UNION
    SELECT item_id FROM sell_in_consumos
) AS candidates
WHERE item_id > :after
ORDER BY item_id
LIMIT :take
"""
)


def run_backfill(
    limit: Optional[int],
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
    after_item: int = 0,
    session_factory: Callable[[], Session] = SessionLocal,
    items: Optional[Iterable[int]] = None,
) -> dict:
    """Recomputes every candidate product after `after_item`, or, with `items`,
    exactly those products, `batch_size` per transaction."""
    wanted = sorted(set(items)) if items is not None else None
    summary = {
        "dry_run": dry_run,
        "products": 0,
        "batches": 0,
        "inserted": 0,
        "deleted": 0,
        "failed": 0,
        "failed_items": [],
        "last_item_id": after_item,
    }
    while limit is None or summary["products"] < limit:
        take = batch_size if limit is None else min(batch_size, limit - summary["products"])
        db = session_factory()
        try:
            if wanted is None:
                params = {"after": summary["last_item_id"], "take": take}
                batch = [row[0] for row in db.execute(_CANDIDATES_SQL, params)]
            else:
                batch = [item for item in wanted if item > summary["last_item_id"]][:take]
            if not batch:
                break
            result = get_costing().recompute(db, batch)
            if dry_run:
                db.rollback()
            else:
                db.commit()
        finally:
            db.close()
        if result.failed:
            logger.warning("backfill_sell_in_consumos: failed products %s", result.failed)
        summary["products"] += len(batch)
        summary["batches"] += 1
        summary["inserted"] += result.inserted
        summary["deleted"] += result.deleted
        summary["failed"] += len(result.failed)
        summary["failed_items"].extend(sorted(result.failed))
        summary["last_item_id"] = batch[-1]
        if len(batch) < take:
            break
    return summary


def _item_ids(value: str) -> List[int]:
    try:
        return sorted({int(part) for part in value.split(",") if part.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a CSV of item ids: {value!r}") from None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recompute the sell-in allocation (sell_in_consumos) of every product with sell in."
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many products.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Products per batch and commit.")
    parser.add_argument(
        "--after-item", type=int, default=0, help="Resume after this item_id (the last_item_id of a previous summary)."
    )
    parser.add_argument(
        "--items",
        type=_item_ids,
        default=None,
        help="Recompute exactly these products (CSV of item_ids, e.g. the failed_items of a previous summary).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute and report; write nothing.")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    summary = run_backfill(
        limit=args.limit,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        after_item=args.after_item,
        items=args.items,
    )
    logger.info("backfill_sell_in_consumos: complete %s", summary)
    if summary["failed_items"]:
        logger.warning(
            "backfill_sell_in_consumos: %s product(s) failed; rerun them with --items %s",
            len(summary["failed_items"]),
            ",".join(str(item) for item in summary["failed_items"]),
        )


if __name__ == "__main__":
    main()
