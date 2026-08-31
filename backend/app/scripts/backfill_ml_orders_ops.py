"""Manual entry point for the historical backfill over the rolling window
(slice 5 of ml-ventas-fuente-de-verdad).

Manual invocation only -- NOT wired into `crontab_fixed.txt`. Reuses
`backfill_service.run_backfill`, which is itself a complete no-op (zero
HTTP calls, zero DB writes/reads) while `ML_ORDERS_OPS_ENABLED` is False,
exactly like the sweep's own cron entry point.

Run:
    python -m app.scripts.backfill_ml_orders_ops --days 90
    python -m app.scripts.backfill_ml_orders_ops --days 90..180 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from app.services.ml_orders_ingestion.backfill_service import (  # noqa: E402
    parse_days_arg,
    run_backfill,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Historical backfill for ml_orders_ops")
    parser.add_argument(
        "--days",
        required=True,
        type=parse_days_arg,
        help="Either N (full width from today back to N days ago) or FROM..TO "
        "(only the historical tail between FROM and TO days ago), e.g. '90' or '90..180'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log the windows that would be fetched; make zero writes.",
    )
    parser.add_argument(
        "--seller-id",
        type=int,
        default=None,
        help="Override ML_USER_ID for this run.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    # `type=parse_days_arg` above already converts and validates --days;
    # argparse catches the ValueError it can raise and turns it into its
    # own usage message + a clean SystemExit(2), never an unhandled
    # traceback for an operator typo (finding 6).
    args = _build_parser().parse_args(argv)

    days_from, days_to = args.days

    result = run_backfill(
        days_from=days_from,
        days_to=days_to,
        seller_id=args.seller_id,
        dry_run=args.dry_run,
    )

    if not result.ran:
        reason = result.error or "flag off or misconfigured"
        logger.info("backfill_ml_orders_ops: did not run (%s)", reason)
        return
    if result.error:
        logger.error("backfill_ml_orders_ops: failed: %s", result.error)
        return
    outcome = "backfill stopped early (fetch budget)" if result.budget_exhausted else "backfill complete"
    logger.info(
        "backfill_ml_orders_ops: %s (dry_run=%s) — days_completed=%s seen=%s upserted=%s "
        "skipped_stale=%s mapping_error=%s out_of_window=%s",
        outcome,
        result.dry_run,
        result.days_completed,
        result.orders_seen,
        result.orders_upserted,
        result.orders_skipped_stale,
        result.orders_mapping_error,
        result.orders_out_of_window,
    )


if __name__ == "__main__":
    main()
