"""Manual entry point for the historical backfill of payments and shipment
costs (ml-backfill-pagos-y-costos).

Manual invocation only -- NOT wired into `crontab_fixed.txt`. Reuses
`backfill_payments_costs_service.run_backfill`, which is itself a complete
no-op (zero HTTP calls, zero DB writes) while `ML_ORDERS_OPS_ENABLED` is
False, exactly like the sweep's and the orders backfill's own entry
points.

Run:
    python -m app.scripts.backfill_ml_payments_costs --limit 500
    python -m app.scripts.backfill_ml_payments_costs --limit 500 --dry-run
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

from app.services.ml_orders_ingestion.backfill_payments_costs_service import (  # noqa: E402
    DEFAULT_LIMIT,
    run_backfill,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Historical backfill for ml_orders_ops.payments_synced_at / "
        "ml_shipments_ops.costs_synced_at -- orders and shipments no sweep "
        "window will ever revisit."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max candidates pulled per category (orders missing payments, shipments missing "
        f"costs) in this run. Default {DEFAULT_LIMIT}. A run resolves and seals a bounded "
        "slice; sealed rows drop out of the next run's candidate query, so repeated runs "
        "with the same --limit drain the backlog without extra bookkeeping.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidates and log them; make zero HTTP calls and zero writes, take no lock.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)

    result = run_backfill(limit=args.limit, dry_run=args.dry_run)

    if not result.ran:
        reason = result.error or "flag off or misconfigured"
        logger.info("backfill_ml_payments_costs: did not run (%s)", reason)
        if result.error:
            # Same discipline as `backfill_ml_orders_ops.py`: the flag-off
            # no-op is a genuine success (exit 0); anything else that kept
            # this run from happening -- "already running" -- is a real
            # failure a chained/scripted invocation must see as non-zero.
            sys.exit(1)
        return
    if result.error:
        logger.error("backfill_ml_payments_costs: failed: %s", result.error)
        sys.exit(1)

    logger.info(
        "backfill_ml_payments_costs: complete (dry_run=%s, limit=%s) -- "
        "order_candidates=%s payments_synced=%s orders_sealed=%s payments_budget_exhausted=%s "
        "shipment_candidates=%s shipment_costs_synced=%s costs_budget_exhausted=%s shipments_gave_up=%s",
        result.dry_run,
        args.limit,
        result.order_candidates,
        result.payments_synced,
        result.orders_sealed,
        result.payments_budget_exhausted,
        result.shipment_candidates,
        result.shipment_costs_synced,
        result.costs_budget_exhausted,
        result.shipments_gave_up,
    )


if __name__ == "__main__":
    main()
