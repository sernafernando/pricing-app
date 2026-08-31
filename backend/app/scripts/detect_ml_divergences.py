"""Cron entry point for ML-vs-GBP divergence detection (slice 6 of
ml-ventas-fuente-de-verdad). No-op while `ML_ORDERS_OPS_ENABLED` is False
(same precedent as `sync_ml_orders_ops.py`).

Run:
    python -m app.scripts.detect_ml_divergences
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

from app.core.database import get_background_db  # noqa: E402
from app.services.ml_orders_ingestion.divergence_service import detect_divergences  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with get_background_db() as db:
        result = detect_divergences(db)

    if not result.ran:
        logger.info("detect_ml_divergences: detection did not run (flag off)")
        return
    if result.error:
        logger.error("detect_ml_divergences: detection failed: %s", result.error)
        return
    logger.info(
        "detect_ml_divergences: pass complete — missing_in_gbp=%s missing_in_ml=%s "
        "field_mismatches=%s unenumerable_purged=%s",
        result.missing_in_gbp,
        result.missing_in_ml,
        result.field_mismatches,
        result.unenumerable_purged,
    )


if __name__ == "__main__":
    main()
