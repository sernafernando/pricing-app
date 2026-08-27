"""Cron entry point for the ML orders reconciliation sweep (slice 3 of
ml-ventas-fuente-de-verdad).

Runs `sweep_service.run_sweep()`, which is itself a complete no-op (zero
HTTP calls, zero DB writes/reads) while `ML_ORDERS_OPS_ENABLED` is False --
this script adds no logic on top of that gate, so it stays a no-op too.

Run:
    python -m app.scripts.sync_ml_orders_ops
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from app.services.ml_orders_ingestion.sweep_service import run_sweep  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = run_sweep()
    if not result.ran:
        # `already running` is neither of those, and saying so sends whoever
        # reads this log looking at the wrong thing.
        reason = result.error or "flag off or misconfigured"
        logger.info("sync_ml_orders_ops: sweep did not run (%s)", reason)
        return
    if result.error:
        logger.error("sync_ml_orders_ops: sweep failed: %s", result.error)
        return
    # A pass that ran out of fetch budget covered only part of the window;
    # calling that "complete" is how a partial sweep passes for a finished one.
    outcome = "sweep stopped early (fetch budget)" if result.budget_exhausted else "sweep complete"
    logger.info(
        "sync_ml_orders_ops: %s — seen=%s upserted=%s skipped_stale=%s "
        "mapping_error=%s out_of_window=%s unenumerable=%s truncated=%s window=[%s, %s]",
        outcome,
        result.orders_seen,
        result.orders_upserted,
        result.orders_skipped_stale,
        result.orders_mapping_error,
        result.orders_out_of_window,
        result.windows_unenumerable,
        result.budget_exhausted,
        result.window_from,
        result.window_to,
    )


if __name__ == "__main__":
    main()
