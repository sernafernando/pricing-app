"""
Sync de fichadas desde Hikvision DS-K1T804AMF.

Estrategia: busca desde la última fichada guardada en DB (con margen de 1 hora
para cubrir dedup por proximity). Si no hay fichadas previas, trae el día actual.

Esto garantiza que si un sync falla (red, 401, etc.), el siguiente recupera
automáticamente los eventos perdidos sin intervención manual.

Dedup automático por event_id (serialNo) + proximity (120s mismo empleado).
Fichadas sin empleado mapeado se guardan con empleado_id=NULL.

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_hikvision_fichadas

Para cron (cada 2 horas):
    0 */2 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_hikvision_fichadas >> /var/log/pricing-app/hikvision_sync.log 2>&1
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

from datetime import datetime, timedelta

from sqlalchemy import func as sql_func

from app.core.database import SessionLocal
from app.models.rrhh_fichada import RRHHFichada
from app.services.rrhh_hikvision_client import ART_TZ, HikvisionClient


# Máximo de días hacia atrás para buscar si no hay fichadas recientes.
# Evita consultar años enteros al dispositivo si la DB está vacía.
MAX_LOOKBACK_DAYS = 14


def _get_last_fichada_timestamp(db) -> datetime | None:
    """Obtiene el timestamp de la última fichada Hikvision en la DB."""
    result = db.query(sql_func.max(RRHHFichada.timestamp)).filter(RRHHFichada.origen == "hikvision").scalar()
    return result


def main() -> None:
    """Sync fichadas desde Hikvision con auto-recuperación.

    En vez de buscar solo el día actual, busca desde la última fichada
    guardada en DB. Si un sync previo falló, el siguiente lo recupera
    automáticamente.

    Usa hora local Argentina (ART, UTC-3) porque el dispositivo Hikvision
    opera en hora local y rechaza timestamps UTC con HTTP 400.
    """
    print(f"[{datetime.now()}] Iniciando sync Hikvision fichadas...")

    db = SessionLocal()
    try:
        # Determinar desde cuándo buscar
        last_ts = _get_last_fichada_timestamp(db)

        if last_ts:
            # Buscar desde 1 hora antes de la última fichada (margen para proximity dedup)
            desde = last_ts - timedelta(hours=1)
            # Asegurar timezone ART
            if desde.tzinfo is None:
                desde = desde.replace(tzinfo=ART_TZ)
            else:
                desde = desde.astimezone(ART_TZ)
            print(f"[{datetime.now()}] Última fichada en DB: {last_ts} — buscando desde {desde}")
        else:
            # No hay fichadas previas — buscar los últimos MAX_LOOKBACK_DAYS días
            desde = datetime.now(ART_TZ) - timedelta(days=MAX_LOOKBACK_DAYS)
            desde = desde.replace(hour=0, minute=0, second=0, microsecond=0)
            print(f"[{datetime.now()}] Sin fichadas previas — buscando últimos {MAX_LOOKBACK_DAYS} días desde {desde}")

        client = HikvisionClient(db)
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
