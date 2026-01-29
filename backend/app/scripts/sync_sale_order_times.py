"""
Script para sincronizar transacciones de órdenes de venta desde el ERP
Tabla: tbSaleOrderTimes

Esta tabla registra todas las transacciones de una sale order:
- 10: Creación del Pedido
- 15: Modificación del Pedido
- 20: Envío a Preparación
- 30: Comienzo de Preparación
- 40: Cierre del Pedido ← CLAVE para detectar pedidos cerrados
- 50: Procesamiento del Pedido
- 60: Salida del Pedido
- 70: Entrega del Pedido

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_sale_order_times
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Cargar .env
from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

import requests
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.sale_order_times import SaleOrderTimes
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_sale_order_times_from_erp(from_date: date = None, to_date: date = None):
    """Obtiene transacciones de órdenes de venta desde el ERP vía GBP Worker"""
    url = "http://localhost:8002/api/gbp-parser"

    # Por defecto, últimos 12 meses (tabla acumulativa)
    if not from_date:
        from_date = date.today() - timedelta(days=365)
    if not to_date:
        # Sumar 1 día para incluir transacciones creadas HOY
        to_date = date.today() + timedelta(days=1)

    params = {
        'strScriptLabel': 'scriptSaleOrderTimes',
        'fromDate': from_date.isoformat(),
        'toDate': to_date.isoformat()
    }

    logger.info(f"📥 Descargando transacciones de órdenes desde {from_date} hasta {to_date}...")

    try:
        response = requests.get(url, params=params, timeout=300)
        response.raise_for_status()
        data = response.json()

        logger.info(f"  ✓ Obtenidos {len(data)} registros")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Error consultando ERP: {e}")
        return []


def sync_sale_order_times(db: Session, data: list):
    """Sincroniza las transacciones de órdenes en la base de datos local"""

    if not data:
        logger.warning("  ⚠️  No hay datos para sincronizar")
        return 0, 0, 0

    logger.info(f"\n💾 Sincronizando {len(data)} registros...")

    insertados = 0
    actualizados = 0
    errores = 0

    for record in data:
        try:
            comp_id = record.get('comp_id')
            bra_id = record.get('bra_id')
            soh_id = record.get('soh_id')
            sot_id = record.get('sot_id')

            # Buscar registro existente por clave compuesta
            existente = db.query(SaleOrderTimes).filter(
                and_(
                    SaleOrderTimes.comp_id == comp_id,
                    SaleOrderTimes.bra_id == bra_id,
                    SaleOrderTimes.soh_id == soh_id,
                    SaleOrderTimes.sot_id == sot_id
                )
            ).first()

            # Preparar datos
            datos = {
                'comp_id': comp_id,
                'bra_id': bra_id,
                'soh_id': soh_id,
                'sot_id': sot_id,
                'sot_cd': record.get('sot_cd'),
                'ssot_id': record.get('ssot_id'),
                'user_id': record.get('user_id')
            }

            if existente:
                # Actualizar registro existente
                for key, value in datos.items():
                    setattr(existente, key, value)
                actualizados += 1
            else:
                # Insertar nuevo registro
                nuevo = SaleOrderTimes(**datos)
                db.add(nuevo)
                insertados += 1

            # Commit cada 1000 registros
            if (insertados + actualizados) % 1000 == 0:
                db.commit()
                logger.info(f"  💾 Progreso: {insertados} insertados, {actualizados} actualizados")

        except Exception as e:
            logger.error(f"  ❌ Error procesando registro {record.get('soh_id')}: {e}")
            errores += 1

    # Commit final
    db.commit()

    logger.info(f"\n✅ Sincronización completada:")
    logger.info(f"  - Insertados: {insertados}")
    logger.info(f"  - Actualizados: {actualizados}")
    logger.info(f"  - Errores: {errores}")

    return insertados, actualizados, errores


if __name__ == "__main__":
    logger.info("\n" + "="*70)
    logger.info("SINCRONIZAR TRANSACCIONES DE ÓRDENES DE VENTA (tbSaleOrderTimes)")
    logger.info("="*70 + "\n")

    db = SessionLocal()

    try:
        # 1. Obtener datos del ERP
        data = fetch_sale_order_times_from_erp()

        # 2. Sincronizar en DB local
        if data:
            sync_sale_order_times(db, data)
        else:
            logger.warning("⚠️  No se obtuvieron datos del ERP")

    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
    finally:
        db.close()

    logger.info("\n" + "="*70)
    logger.info("PROCESO FINALIZADO")
    logger.info("="*70 + "\n")
