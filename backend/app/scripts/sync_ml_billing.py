"""Cron entry point for the ML billing daily sweep (ml-ventas-desglose-
costos, corte 3).

Runs `billing_sweep_service.run_billing_sweep()`, which is itself a
complete no-op (zero HTTP calls, zero DB writes/reads) while
`ML_BILLING_ENABLED` is False.

Run:
    python -m app.scripts.sync_ml_billing
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

from app.services.ml_billing.billing_sweep_service import run_billing_sweep  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    result = run_billing_sweep()
    if not result.ran:
        # `already running` is neither of those, and saying so sends
        # whoever reads this log looking at the wrong thing.
        reason = result.error or "flag off or misconfigured"
        logger.info("sync_ml_billing: sweep did not run (%s)", reason)
        return 0
    if result.error:
        logger.error("sync_ml_billing: sweep failed (period=%s): %s", result.period_key, result.error)
        return 1
    outcome = "sweep stopped early (request failed, no retry)" if result.stopped_early else "sweep complete"
    logger.info(
        "sync_ml_billing: %s -- period=%s seen=%s upserted=%s mapping_error=%s",
        outcome,
        result.period_key,
        result.charges_seen,
        result.charges_upserted,
        result.charges_mapping_error,
    )
    return 1 if result.stopped_early else 0


if __name__ == "__main__":
    sys.exit(main())
