"""
Script para sincronizar clases fiscales desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_fiscal_classes
    python -m app.scripts.sync_fiscal_classes --fc-id 1
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from app.core.database import SessionLocal
from app.models.tb_fiscal_class import TBFiscalClass
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_fiscal_classes_from_erp(fc_id: int = None):
    """
    Obtiene clases fiscales desde el ERP vía gbp-parser.

    Args:
        fc_id: ID de clase fiscal específica

    Returns:
        Lista de registros
    """
    params = {
        'strScriptLabel': 'scriptFiscalClass'
    }

    if fc_id:
        params['fcID'] = fc_id

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


def sync_fiscal_classes(fc_id: int = None):
    """
    Sincroniza clases fiscales desde el ERP.

    Args:
        fc_id: ID específico de clase fiscal (opcional)
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de clases fiscales ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_fiscal_classes_from_erp(fc_id=fc_id)

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Procesar registros
        for record in registros_erp:
            fc_id_val = record.get('fc_id')

            if not fc_id_val:
                logger.warning(f"Registro sin fc_id: {record}")
                continue

            # Preparar datos (columnas lowercase, .get() con camelCase del ERP)
            datos = {
                'fc_id': fc_id_val,
                'fc_desc': record.get('fc_desc'),
                'fc_kindof': record.get('fc_KindOf'),
                'country_id': record.get('country_id'),
                'fc_legaltaxid': record.get('fc_LegalTaxId'),
            }

            # Verificar si existe
            existente = db_local.query(TBFiscalClass).filter(
                TBFiscalClass.fc_id == fc_id_val
            ).first()

            if existente:
                for key, value in datos.items():
                    setattr(existente, key, value)
                total_actualizados += 1
            else:
                nuevo_registro = TBFiscalClass(**datos)
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

    parser = argparse.ArgumentParser(description='Sincronizar clases fiscales desde ERP')
    parser.add_argument(
        '--fc-id',
        type=int,
        help='ID de clase fiscal específica'
    )

    args = parser.parse_args()

    sync_fiscal_classes(fc_id=args.fc_id)
