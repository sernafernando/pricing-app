"""
Script para sincronizar tipos de documento desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_document_files
    python -m app.scripts.sync_document_files --df-id 1
    python -m app.scripts.sync_document_files --bra-id 1
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from app.core.database import SessionLocal
from app.models.tb_document_file import TBDocumentFile
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_document_files_from_erp(
    df_id: int = None,
    bra_id: int = None
):
    """
    Obtiene tipos de documento desde el ERP vía gbp-parser.

    Args:
        df_id: ID de documento específico
        bra_id: ID de sucursal

    Returns:
        Lista de registros
    """
    params = {
        'strScriptLabel': 'scriptDocumentFile'
    }

    if df_id:
        params['dfID'] = df_id
    if bra_id:
        params['braID'] = bra_id

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


def parse_bool(value):
    """Parsea un valor booleano desde el ERP."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    return bool(value)


def sync_document_files(
    df_id: int = None,
    bra_id: int = None
):
    """
    Sincroniza tipos de documento desde el ERP.

    Args:
        df_id: ID específico de documento (opcional)
        bra_id: ID de sucursal (opcional)
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de tipos de documento ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_document_files_from_erp(
            df_id=df_id,
            bra_id=bra_id
        )

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Procesar registros
        for record in registros_erp:
            df_id_val = record.get('df_id')
            bra_id_val = record.get('bra_id')

            if not df_id_val or not bra_id_val:
                logger.warning(f"Registro sin df_id o bra_id: {record}")
                continue

            comp_id = record.get('comp_id', 1)

            # Preparar datos (columnas lowercase, .get() con camelCase del ERP)
            datos = {
                'comp_id': comp_id,
                'bra_id': bra_id_val,
                'df_id': df_id_val,
                'df_desc': record.get('df_desc'),
                'df_pointofsale': record.get('df_pointOfSale'),
                'df_number': record.get('df_number'),
                'df_tonumber': record.get('df_toNumber'),
                'df_disabled': parse_bool(record.get('df_Disabled')),
                'df_iselectronicinvoice': parse_bool(record.get('df_isElectronicInvoice')),
            }

            # Verificar si existe (PK compuesta: comp_id, bra_id, df_id)
            existente = db_local.query(TBDocumentFile).filter(
                TBDocumentFile.comp_id == comp_id,
                TBDocumentFile.bra_id == bra_id_val,
                TBDocumentFile.df_id == df_id_val
            ).first()

            if existente:
                for key, value in datos.items():
                    setattr(existente, key, value)
                total_actualizados += 1
            else:
                nuevo_registro = TBDocumentFile(**datos)
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

    parser = argparse.ArgumentParser(description='Sincronizar tipos de documento desde ERP')
    parser.add_argument(
        '--df-id',
        type=int,
        help='ID de documento específico'
    )
    parser.add_argument(
        '--bra-id',
        type=int,
        help='ID de sucursal'
    )

    args = parser.parse_args()

    sync_document_files(
        df_id=args.df_id,
        bra_id=args.bra_id
    )
