"""
Script para sincronizar costos faltantes en item_cost_list_history.
Crea registros de historial para productos que tienen costo en productos_erp
pero no tienen registro en item_cost_list_history.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal
from app.services.cost_history_manager import sincronizar_costos_faltantes
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=== Iniciando sincronización de costos faltantes ===")

    db = SessionLocal()

    try:
        registros_creados = sincronizar_costos_faltantes(db, commit=True)
        logger.info(f"\n✅ Sincronización completada")
        logger.info(f"   Registros creados: {registros_creados}")

    except Exception as e:
        logger.error(f"❌ Error durante la sincronización: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
