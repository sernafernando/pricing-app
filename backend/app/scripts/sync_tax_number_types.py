"""
Script para sincronizar tipos de número de impuesto desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_tax_number_types
    python -m app.scripts.sync_tax_number_types --tnt-id 1
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from app.core.database import SessionLocal
from app.models.tb_tax_number_type import TBTaxNumberType
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_tax_number_types_from_erp(tnt_id: int = None):
    """
    Obtiene tipos de número de impuesto desde el ERP vía gbp-parser.

    Args:
        tnt_id: ID de tipo específico

    Returns:
        Lista de registros
    """
    params = {
        'strScriptLabel': 'scriptTaxNumberType'
    }

    if tnt_id:
        params['tntID'] = tnt_id

    logger.info(f"Consultando ERP con params: {params}")

    try:
        response = requests.get(WORKER_URL, params=params, timeout=60)
        response.raise_for_status()

        data = response.json()

        if isinstance(data, list):
            return data
        else:
            logger.error(f"Respuesta inesperada del worker: {type(data)}")
            return []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error al consultar el worker: {e}")
        raise


def sync_tax_number_types(tnt_id: int = None):
    """
    Sincroniza tipos de número de impuesto desde el ERP.

    Args:
        tnt_id: ID específico de tipo (opcional)
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de tipos de número de impuesto ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_tax_number_types_from_erp(tnt_id=tnt_id)

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Procesar registros
        for record in registros_erp:
            tnt_id_val = record.get('tnt_id')

            if not tnt_id_val:
                logger.warning(f"Registro sin tnt_id: {record}")
                continue

            # Preparar datos
            datos = {
                'tnt_id': tnt_id_val,
                'tnt_desc': record.get('tnt_desc'),
                'tnt_afip': record.get('tnt_afip'),
            }

            # Verificar si existe
            existente = db_local.query(TBTaxNumberType).filter(
                TBTaxNumberType.tnt_id == tnt_id_val
            ).first()

            if existente:
                for key, value in datos.items():
                    setattr(existente, key, value)
                total_actualizados += 1
            else:
                nuevo_registro = TBTaxNumberType(**datos)
                db_local.add(nuevo_registro)
                total_nuevos += 1

        # Commit final
        db_local.commit()

        logger.info("\n=== Sincronización completada ===")
        logger.info(f"  Total nuevos: {total_nuevos}")
        logger.info(f"  Total actualizados: {total_actualizados}")
        logger.info(f"  Total procesados: {total_nuevos + total_actualizados}")

        return (total_nuevos, total_actualizados)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        if db_local:
            db_local.rollback()
        raise

    finally:
        if db_local:
            db_local.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar tipos de número de impuesto desde ERP')
    parser.add_argument(
        '--tnt-id',
        type=int,
        help='ID de tipo específico'
    )

    args = parser.parse_args()

    sync_tax_number_types(tnt_id=args.tnt_id)
