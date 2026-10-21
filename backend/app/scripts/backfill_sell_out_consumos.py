"""Backfill the sell-out allocation (`sell_out_consumos`, sell-in-sell-out T7 S2).

Rebuilds every campaign (any state: a voided one must lose its rows) through
`app.services.sell_out.asignacion.recalcular`, in id order. Each campaign is
rebuilt in its own savepoint together with the campaigns sharing products with
it, so one that fails (a percentage campaign, a missing BNA rate) is rolled back
alone and listed in `failed_campanas`; `--campanas` (a CSV of ids) reruns exactly
those. Idempotent: a rebuild writes only the difference, so a re-run writes
nothing. `pendientes_base` counts the percentage sales skipped because their base
(an unsettled ML order, a sale without its cost) is not known yet: they are
picked up when their campaign is rebuilt again.

Bounded: `--batch-size` campaigns per transaction, each with a local
`statement_timeout`; `--after-campana` (the `last_campana_id` of a previous
summary) resumes. `--dry-run` runs EVERYTHING in one transaction that is rolled
back at the end, so later campaigns see what earlier ones would have written,
and reports what would change.

Exits 1 when any campaign failed or the run stopped early, 0 otherwise. Run
from `backend/` with `-m` (the settings read `backend/.env` from there):
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_out_consumos --dry-run
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.backfill_sell_out_consumos
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.sell_out.asignacion import recalcular

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
STATEMENT_TIMEOUT_MS = 120_000

_CANDIDATES_SQL = text("SELECT id FROM sell_out_campanas WHERE id > :after ORDER BY id LIMIT :take")


def _timeout(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))


def _rebuild(db: Session, batch: list[int]) -> tuple[int, int, dict[int, str], dict[int, int]]:
    """`(inserted, deleted, {campaign: error}, {campaign: sales waiting for their base})` of one batch,
    each campaign in its own savepoint. A rebuild covers linked campaigns too: the latest count wins."""
    inserted = deleted = 0
    errors: dict[int, str] = {}
    pendientes: dict[int, int] = {}
    for campana_id in batch:
        try:
            with db.begin_nested():
                result = recalcular(db, [campana_id])
        except Exception as exc:  # noqa: BLE001 - one campaign must not block the rest
            logger.warning("backfill_sell_out_consumos: campaign %s failed: %s", campana_id, exc)
            errors[campana_id] = f"{type(exc).__name__}: {exc}"[:500]
            continue
        inserted += result.inserted
        deleted += result.deleted
        pendientes.update(result.pendientes_base)
    return inserted, deleted, errors, pendientes


def run_backfill(
    limit: int | None,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
    after_campana: int = 0,
    session_factory: Callable[[], Session] = SessionLocal,
    campanas: Iterable[int] | None = None,
) -> dict:
    """Rebuilds every campaign after `after_campana` (or exactly `campanas`), `batch_size` per commit."""
    if batch_size < 1 or (limit is not None and limit < 1):
        raise ValueError(f"batch_size and limit must be >= 1 (got batch_size={batch_size}, limit={limit})")
    wanted = sorted(set(campanas)) if campanas is not None else None
    summary = {
        "dry_run": dry_run,
        "campanas": 0,
        "batches": 0,
        "inserted": 0,
        "deleted": 0,
        "failed_campanas": [],
        "pendientes_base": 0,
        "errors": {},
        "last_campana_id": after_campana,
        "stopped_at_after_campana": None,
        "stop_error": None,
    }
    por_campana: dict[int, int] = {}
    db = session_factory()
    try:
        _timeout(db)
        while limit is None or summary["campanas"] < limit:
            take = batch_size if limit is None else min(batch_size, limit - summary["campanas"])
            if wanted is None:
                batch = [r[0] for r in db.execute(_CANDIDATES_SQL, {"after": summary["last_campana_id"], "take": take})]
            else:
                batch = [c for c in wanted if c > summary["last_campana_id"]][:take]
            if not batch:
                break
            inserted, deleted, errors, pendientes = _rebuild(db, batch)
            if not dry_run:
                db.commit()
                _timeout(db)
            summary["inserted"] += inserted
            summary["deleted"] += deleted
            summary["failed_campanas"].extend(errors)
            summary["errors"].update(errors)
            por_campana.update(pendientes)
            summary["pendientes_base"] = sum(por_campana.values())
            summary["campanas"] += len(batch)
            summary["batches"] += 1
            summary["last_campana_id"] = batch[-1]
    except Exception as exc:  # noqa: BLE001 - keep the summary of the committed batches
        logger.exception("backfill_sell_out_consumos: stopped after campaign %s", summary["last_campana_id"])
        summary["stopped_at_after_campana"] = summary["last_campana_id"]
        summary["stop_error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        db.rollback()  # a dry run's only transaction; after a commit, nothing
        db.close()
    return summary


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1: {value!r}")
    return number


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0: {value!r}")
    return number


def _ids(value: str) -> list[int]:
    try:
        ids = sorted({int(part) for part in value.split(",") if part.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a CSV of campaign ids: {value!r}") from None
    if not ids:
        raise argparse.ArgumentTypeError(f"no campaign ids in {value!r}")
    return ids


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild the sell-out allocation (sell_out_consumos).")
    parser.add_argument("--limit", type=_positive_int, default=None, help="Stop after this many campaigns.")
    parser.add_argument("--batch-size", type=_positive_int, default=DEFAULT_BATCH_SIZE, help="Campaigns per commit.")
    parser.add_argument("--after-campana", type=_non_negative_int, default=0, help="Resume after this campaign id.")
    parser.add_argument("--campanas", type=_ids, default=None, help="Rebuild exactly these campaigns (CSV of ids).")
    parser.add_argument("--dry-run", action="store_true", help="Compute and report in one rolled-back transaction.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    summary = run_backfill(
        limit=args.limit,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        after_campana=args.after_campana,
        campanas=args.campanas,
    )
    logger.info("backfill_sell_out_consumos: %s", summary)
    if summary["stopped_at_after_campana"] is not None:
        logger.error("backfill_sell_out_consumos: resume with --after-campana %s", summary["stopped_at_after_campana"])
    if summary["failed_campanas"]:
        logger.warning(
            "backfill_sell_out_consumos: rerun the failed ones with --campanas %s",
            ",".join(str(c) for c in summary["failed_campanas"]),
        )
    return 1 if summary["failed_campanas"] or summary["stopped_at_after_campana"] is not None else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
