"""
Script de recuperación para re-ejecutar todos los syncs que fallaron
debido al error de mapper de SQLAlchemy (RolPermisoBase).

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.recovery_sync
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
from datetime import datetime
from app.core.database import SessionLocal

# Importar todos los modelos PRIMERO para evitar el error de mapper
import app.models  # noqa

# Ahora importar las funciones de sync
from app.scripts.sync_ml_publications_incremental import sync_ml_publications_incremental
from app.scripts.sync_ml_items_publicados_incremental import sync_items_publicados_incremental
from app.scripts.sync_ml_items_publicados_full import sync_items_publicados_full


async def run_recovery():
    """Ejecuta todos los syncs de recuperación"""
    print("=" * 60)
    print("RECUPERACIÓN DE SYNCS FALLIDOS")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 1. Sync completo de items publicados (trae todas las activas)
        print("\n" + "=" * 60)
        print("1/3 - SYNC COMPLETO DE ITEMS PUBLICADOS")
        print("=" * 60)
        try:
            result = await sync_items_publicados_full(db)
            print(f"Resultado: {result}")
        except Exception as e:
            print(f"Error: {e}")

        # 2. Sync incremental de items publicados
        print("\n" + "=" * 60)
        print("2/3 - SYNC INCREMENTAL DE ITEMS PUBLICADOS")
        print("=" * 60)
        try:
            result = await sync_items_publicados_incremental(db)
            print(f"Resultado: {result}")
        except Exception as e:
            print(f"Error: {e}")

        # 3. Sync de snapshots ML (publicaciones)
        print("\n" + "=" * 60)
        print("3/3 - SYNC DE SNAPSHOTS ML")
        print("=" * 60)
        try:
            result = await sync_ml_publications_incremental(db)
            print(f"Resultado: {result}")
        except Exception as e:
            print(f"Error: {e}")

    finally:
        db.close()

    print("\n" + "=" * 60)
    print("RECUPERACIÓN COMPLETADA")
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_recovery())
