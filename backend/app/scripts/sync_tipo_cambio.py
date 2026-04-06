#!/usr/bin/env python3
"""
Sincronización standalone de tipo de cambio BNA.

Reemplaza: curl -X POST http://127.0.0.1:8002/api/sync-tipo-cambio

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_tipo_cambio

Cron:
    */5 6-21 * * * cd /var/www/html/pricing-app/backend && \
        /var/www/html/pricing-app/backend/venv/bin/python \
        -m app.scripts.sync_tipo_cambio \
        >> /var/log/pricing-app/tipo-cambio.log 2>&1
"""

import os
import sys
from datetime import datetime
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal  # noqa: E402
from app.services.tipo_cambio_service import actualizar_tipo_cambio_bna  # noqa: E402


def main() -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = SessionLocal()
    try:
        result = actualizar_tipo_cambio_bna(db)
        print(f"[{timestamp}] Tipo cambio: {result}", flush=True)
    except Exception as e:
        print(f"[{timestamp}] Error tipo cambio: {e}", flush=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
