"""Manual entry point: one pass of the `promo_refresh_pending` drain.

The scheduled drain is the `promo_write.refresh` worker handler (no cron). This script runs the same pass,
`app.services.promo_refresh_drain.drain`, by hand, with no deadline (the per-pass row cap still bounds it).

Run:
    python app/scripts/drain_promo_refresh.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

# Cargar variables de entorno desde .env
from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=backend_path / ".env")

from app.services import promo_refresh_drain  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("drain_promo_refresh: %s", promo_refresh_drain.drain(deadline=None))


if __name__ == "__main__":
    main()
