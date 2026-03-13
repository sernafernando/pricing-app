"""
Backfill de fichadas Hikvision desde 2026-01-01 hasta hoy.

Script one-shot para cargar el histórico completo de fichadas.
Procesa por semana para no exceder los límites del dispositivo.
Dedup automático: si ya existen, las ignora.

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.backfill_hikvision_2026
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

from app.core.database import SessionLocal
from app.services.rrhh_hikvision_client import ART_TZ, HikvisionClient


def main() -> None:
    """Backfill fichadas desde 2026-01-01 hasta hoy, semana por semana.

    Usa hora local Argentina (ART, UTC-3) porque el dispositivo Hikvision
    opera en hora local y rechaza timestamps UTC con HTTP 400.
    """
    start_date = datetime(2026, 1, 1, tzinfo=ART_TZ)
    end_date = datetime.now(ART_TZ)

    print(f"[{datetime.now()}] Backfill Hikvision: {start_date.date()} → {end_date.date()}")

    db = SessionLocal()
    total_nuevas = 0
    total_duplicadas = 0
    total_sin_empleado = 0
    total_errores = 0

    try:
        client = HikvisionClient(db)

        # Procesar por semana (7 días)
        current = start_date
        week_num = 0

        while current < end_date:
            week_num += 1
            week_end = min(current + timedelta(days=7), end_date)

            print(
                f"  Semana {week_num}: {current.date()} → {week_end.date()}...",
                end=" ",
                flush=True,
            )

            result = client.sync_fichadas(current, week_end)
            db.commit()

            total_nuevas += result["nuevas"]
            total_duplicadas += result["duplicadas"]
            total_sin_empleado += result["sin_empleado"]
            total_errores += result["errores"]

            print(f"nuevas={result['nuevas']}, dup={result['duplicadas']}, sin_emp={result['sin_empleado']}")

            current = week_end

        print(
            f"\n[{datetime.now()}] Backfill completado!"
            f"\n  Total nuevas:       {total_nuevas}"
            f"\n  Total duplicadas:   {total_duplicadas}"
            f"\n  Total sin empleado: {total_sin_empleado}"
            f"\n  Total errores:      {total_errores}"
        )

    except Exception as e:
        db.rollback()
        print(f"\n[{datetime.now()}] ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
