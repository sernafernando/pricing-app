"""Backfill the sell-in allocation (`sell_in_consumos`, sell-in-sell-out T5).

Until T5 the `sell.drain` was inert: it acked queued sale lines without
computing anything. This script recomputes, through the active
`SellInCosting` strategy, every product that has sell-in purchase lines (any
state: a voided purchase's product must release its units) or stored
consumptions, so the allocation matches the sales as they are now. After it,
the drain keeps it current.

Idempotent: the strategy recomputes a product from scratch and writes only the
difference, so a re-run writes nothing. The % of the sale's cost bonuses
(`bonos_costo`, T25b2) take only the units the FIFO leaves, so each batch
recomputes theirs for the products whose FIFO recompute succeeded, in the same
transaction (`bono_costo_inserted` / `bono_costo_deleted`); a product whose
cost bonus cannot be computed (a missing VAT rate) keeps its rows as they were
and is listed in `failed_items` too (its FIFO still commits). Bounded and resumable: keyset
pagination on `item_id`, one short session and one commit per batch (rolled
back under `--dry-run`, which still reports what would change); `--after-item`
(the `last_item_id` of a previous summary) skips what is done.

A product whose recompute fails is rolled back alone and listed in the
summary's `failed_items`; a batch that fails outside the per-product savepoint
(shared reads, the lock, the commit) is rolled back whole and all its products
are listed; `--after-item` would skip them, so `--items` (a CSV of
item ids) reruns exactly those products and nothing else.

If a session cannot be opened, reading the next candidates fails, or a failed
batch cannot even be rolled back (a dead connection), the run stops there: the summary keeps
what was committed and sets `stopped_at_after_item` (resume with
`--after-item`) and `stop_error`.

Exits 1 when any product failed (after printing the `--items` rerun line) or
the run stopped early (after printing the `--after-item` resume line), 0
otherwise. Run from `backend/` with `-m`: the settings read `backend/.env`
from there, so the module does no import-time bootstrap.

Run:
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_in_consumos --dry-run
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_in_consumos
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_in_consumos --items 2270,2964
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.sell_in import bonos_costo
from app.services.sell_in.costing import RecomputeResult, get_costing

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


def _stop(summary: dict, exc: BaseException, what: str) -> None:
    """Ends the run at the last committed product, keeping the summary so far."""
    logger.exception("backfill_sell_in_consumos: %s after item %s failed", what, summary["last_item_id"])
    summary["stopped_at_after_item"] = summary["last_item_id"]
    summary["stop_error"] = f"{type(exc).__name__}: {exc}"[:500]


def _cost_bonuses(db: Session, items: set[int]) -> bonos_costo.CostoResult:
    """The % of cost bonuses of `items` after their FIFO, in a savepoint as in `sell.drain`: a bonus that cannot be
    computed (a missing VAT rate) lists its products; any other error rolls back only the savepoint, keeps their rows
    and lists every one of `items`, and the batch's FIFO still commits."""
    try:
        with db.begin_nested():
            costo = bonos_costo.recalcular(db, items)
    except Exception as exc:  # noqa: BLE001 - the batch's FIFO must commit
        logger.exception("backfill_sell_in_consumos: cost bonuses not recomputed for products %s", sorted(items))
        error = f"{type(exc).__name__}: {exc}"[:500]
        return bonos_costo.CostoResult(failed={item: error for item in items})
    bonos_costo.registrar_fallidos(costo, "backfill_sell_in_consumos")
    return costo


def _close(db: Session) -> None:
    try:
        db.close()
    except Exception:  # noqa: BLE001 - the batch outcome is already decided
        logger.warning("backfill_sell_in_consumos: closing the session failed", exc_info=True)


def run_backfill(
    limit: int | None,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
    after_item: int = 0,
    session_factory: Callable[[], Session] = SessionLocal,
    items: Iterable[int] | None = None,
) -> dict:
    """Recomputes every candidate product after `after_item`, or, with `items`,
    exactly those products, `batch_size` per transaction."""
    if batch_size < 1 or (limit is not None and limit < 1):
        raise ValueError(f"batch_size and limit must be >= 1 (got batch_size={batch_size}, limit={limit})")
    wanted = sorted(set(items)) if items is not None else None
    summary = {
        "dry_run": dry_run,
        "products": 0,
        "batches": 0,
        "inserted": 0,
        "deleted": 0,
        "bono_costo_inserted": 0,
        "bono_costo_deleted": 0,
        "failed": 0,
        "failed_items": [],
        "last_item_id": after_item,
        "stopped_at_after_item": None,
        "stop_error": None,
    }
    while limit is None or summary["products"] < limit:
        take = batch_size if limit is None else min(batch_size, limit - summary["products"])
        try:
            db = session_factory()
        except Exception as exc:  # noqa: BLE001 - keep the summary of the committed batches
            _stop(summary, exc, "opening a session")
            break
        try:
            if wanted is None:
                params = {"after": summary["last_item_id"], "take": take}
                try:
                    batch = [row[0] for row in db.execute(_CANDIDATES_SQL, params)]
                except Exception as exc:  # noqa: BLE001 - keep the summary of the committed batches
                    _stop(summary, exc, "reading candidates")
                    break
            else:
                batch = [item for item in wanted if item > summary["last_item_id"]][:take]
            if not batch:
                break
            costo = bonos_costo.CostoResult()
            try:
                result = get_costing().recompute(db, batch)
                costo = _cost_bonuses(db, set(batch) - result.failed.keys())
                if dry_run:
                    db.rollback()
                else:
                    db.commit()
            except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the run's summary
                # Outside the per-product savepoint (shared reads, the lock, the
                # commit): the whole batch rolls back and is listed for --items.
                try:
                    db.rollback()
                except Exception as rollback_exc:  # noqa: BLE001 - dead connection: stop before this batch
                    logger.error("backfill_sell_in_consumos: batch %s..%s failed: %s", batch[0], batch[-1], exc)
                    _stop(summary, rollback_exc, "rolling back a failed batch")
                    break
                logger.exception("backfill_sell_in_consumos: batch %s..%s failed", batch[0], batch[-1])
                error = f"{type(exc).__name__}: {exc}"[:500]
                result = RecomputeResult(products=len(batch), failed={item: error for item in batch})
                costo = bonos_costo.CostoResult()
        finally:
            _close(db)
        failed = {**{item: error for item, error in costo.failed.items() if item in batch}, **result.failed}
        if failed:
            logger.warning("backfill_sell_in_consumos: failed products %s", failed)
        summary["products"] += len(batch)
        summary["batches"] += 1
        summary["inserted"] += result.inserted
        summary["deleted"] += result.deleted
        summary["bono_costo_inserted"] += costo.inserted
        summary["bono_costo_deleted"] += costo.deleted
        summary["failed"] += len(failed)
        summary["failed_items"].extend(sorted(failed))
        summary["last_item_id"] = batch[-1]
        if len(batch) < take:
            break
    return summary


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1: {value!r}")
    return number


def _item_ids(value: str) -> list[int]:
    try:
        ids = sorted({int(part) for part in value.split(",") if part.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a CSV of item ids: {value!r}") from None
    if not ids:
        raise argparse.ArgumentTypeError(f"no item ids in {value!r}")
    return ids


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recompute the sell-in allocation (sell_in_consumos) of every product with sell in."
    )
    parser.add_argument("--limit", type=_positive_int, default=None, help="Stop after this many products.")
    parser.add_argument(
        "--batch-size", type=_positive_int, default=DEFAULT_BATCH_SIZE, help="Products per batch and commit."
    )
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    summary = run_backfill(
        limit=args.limit,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        after_item=args.after_item,
        items=args.items,
    )
    stopped = summary.get("stopped_at_after_item")
    logger.info("backfill_sell_in_consumos: %s %s", "stopped" if stopped is not None else "complete", summary)
    if stopped is not None:
        logger.error(
            "backfill_sell_in_consumos: stopped at after_item=%s (%s); resume with --after-item %s",
            stopped,
            summary.get("stop_error"),
            stopped,
        )
    if summary["failed_items"]:
        logger.warning(
            "backfill_sell_in_consumos: %s product(s) failed; rerun them with --items %s",
            len(summary["failed_items"]),
            ",".join(str(item) for item in summary["failed_items"]),
        )
    return 1 if summary["failed_items"] or stopped is not None else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
