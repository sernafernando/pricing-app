"""
Limpieza periódica de notificaciones de markup_bajo.
Elimina las notificaciones con más de 15 días de antigüedad.

Ejecutar manualmente:
    cd backend
    python clear_notis.py

Cron (cada 15 días, domingos alternos a las 2:30 AM):
    30 2 1,15 * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python clear_notis.py >> /var/log/pricing-app/clear_notis.log 2>&1
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

load_dotenv(dotenv_path=backend_dir / ".env")

from datetime import datetime, timedelta, UTC

from app.core.database import SessionLocal
from app.models.notificacion import Notificacion

DIAS_RETENER = 15


def limpiar_notificaciones_antiguas() -> None:
    db = SessionLocal()
    try:
        fecha_corte = datetime.now(UTC) - timedelta(days=DIAS_RETENER)

        deleted = (
            db.query(Notificacion)
            .filter(
                Notificacion.tipo == "markup_bajo",
                Notificacion.fecha_creacion < fecha_corte,
            )
            .delete()
        )
        db.commit()

        print(f"🗑️  Eliminadas {deleted} notificaciones de markup_bajo con más de {DIAS_RETENER} días")
        print(f"   (anteriores a {fecha_corte.strftime('%Y-%m-%d %H:%M')} UTC)")

        # Contar las que quedan
        restantes = db.query(Notificacion).filter(Notificacion.tipo == "markup_bajo").count()
        print(f"📊 Quedan {restantes} notificaciones de markup_bajo (últimos {DIAS_RETENER} días)")
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    limpiar_notificaciones_antiguas()
