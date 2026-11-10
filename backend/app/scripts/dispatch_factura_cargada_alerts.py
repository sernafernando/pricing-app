#!/usr/bin/env python3
"""
Manual sweep of pending factura-cargada alerts after the ERP-check delay.

The scheduled run lives in the worker: handler `compras.factura_cargada_alerts`
in the main `REGISTRY` (`pricing-worker.service`), every minute. This script is
only a thin wrapper over `disparar_alertas_factura_pendientes`, useful to fire
pending rows by hand after a deploy or while debugging.

Cron entry: NONE. Do NOT add this script to any crontab; the worker already
runs it every minute, and a crontab entry would only duplicate it.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.dispatch_factura_cargada_alerts
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal  # noqa: E402
from app.services.compras_alertas_service import disparar_alertas_factura_pendientes  # noqa: E402


def main() -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db = SessionLocal()
    try:
        fired = disparar_alertas_factura_pendientes(db)
        db.commit()
        print(f"[{timestamp}] factura_cargada sweep fired={fired}", flush=True)
    except Exception as exc:
        db.rollback()
        print(f"[{timestamp}] Error factura_cargada sweep: {exc}", flush=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
