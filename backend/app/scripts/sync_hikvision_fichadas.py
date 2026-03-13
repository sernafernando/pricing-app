"""
Sync diario de fichadas desde Hikvision DS-K1T804AMF.

Trae los eventos del día (desde las 00:00) y los guarda en rrhh_fichadas.
Dedup automático por event_id (serialNo).
Fichadas sin empleado mapeado se guardan con empleado_id=NULL.

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_hikvision_fichadas

Para cron (diario a las 23:55):
    55 23 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_hikvision_fichadas >> /var/log/pricing-app/hikvision_sync.log 2>&1
"""

import sys
import os
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.services.rrhh_hikvision_client import HikvisionClient


def main() -> None:
    """Sync fichadas del día desde Hikvision."""
    print(f"[{datetime.now()}] Iniciando sync Hikvision fichadas...")

    db = SessionLocal()
    try:
        client = HikvisionClient(db)

        # Sync desde las 00:00 del día
        desde = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        result = client.sync_fichadas(desde)
        db.commit()

        print(
            f"[{datetime.now()}] Sync completado: "
            f"nuevas={result['nuevas']}, "
            f"duplicadas={result['duplicadas']}, "
            f"sin_empleado={result['sin_empleado']}, "
            f"errores={result['errores']}"
        )

    except Exception as e:
        db.rollback()
        print(f"[{datetime.now()}] ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
