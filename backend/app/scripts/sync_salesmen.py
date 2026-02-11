"""
Script para sincronizar vendedores desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_salesmen
    python -m app.scripts.sync_salesmen --sm-id 1
    python -m app.scripts.sync_salesmen --from-id 1 --to-id 100
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tb_salesman import TBSalesman
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_salesmen_from_erp(sm_id: int = None, from_sm_id: int = None, to_sm_id: int = None):
    """
    Obtiene vendedores desde el ERP vía gbp-parser.

    Args:
        sm_id: ID de vendedor específico
        from_sm_id: ID desde (para paginación)
        to_sm_id: ID hasta (para paginación)

    Returns:
        Lista de registros
    """
    params = {"strScriptLabel": "scriptSalesman"}

    if sm_id:
        params["smID"] = sm_id
    if from_sm_id:
        params["fromSmID"] = from_sm_id
    if to_sm_id:
        params["toSmID"] = to_sm_id

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
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def sync_salesmen(sm_id: int = None, from_sm_id: int = None, to_sm_id: int = None):
    """
    Sincroniza vendedores desde el ERP.

    Args:
        sm_id: ID específico de vendedor (opcional)
        from_sm_id: ID desde (para paginación)
        to_sm_id: ID hasta (para paginación)
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de vendedores ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_salesmen_from_erp(sm_id=sm_id, from_sm_id=from_sm_id, to_sm_id=to_sm_id)

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Obtener IDs existentes
        sm_ids = [r.get("sm_id") for r in registros_erp if r.get("sm_id")]
        existing = db_local.query(TBSalesman.sm_id).filter(TBSalesman.sm_id.in_(sm_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            sm_id_val = record.get("sm_id")

            if not sm_id_val:
                logger.warning(f"Registro sin sm_id: {record}")
                continue

            # Preparar datos (columnas lowercase, .get() con camelCase del ERP)
            datos = {
                "comp_id": record.get("comp_id", 1),
                "sm_id": sm_id_val,
                "sm_name": record.get("sm_name"),
                "sm_email": record.get("sm_email"),
                "bra_id": record.get("bra_id"),
                "sm_commission_bysale": record.get("sm_commission_bySale"),
                "sm_commission_byreceive": record.get("sm_commission_byReceive"),
                "sm_disabled": parse_bool(record.get("sm_disabled")),
            }

            # Verificar si existe
            if sm_id_val in ids_existentes:
                # Actualizar
                db_local.query(TBSalesman).filter(
                    TBSalesman.comp_id == datos["comp_id"], TBSalesman.sm_id == sm_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                # Insertar nuevo
                nuevo_registro = TBSalesman(**datos)
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

    parser = argparse.ArgumentParser(description="Sincronizar vendedores desde ERP")
    parser.add_argument("--sm-id", type=int, help="ID de vendedor específico")
    parser.add_argument("--from-id", type=int, help="ID de vendedor desde")
    parser.add_argument("--to-id", type=int, help="ID de vendedor hasta")

    args = parser.parse_args()

    sync_salesmen(sm_id=args.sm_id, from_sm_id=args.from_id, to_sm_id=args.to_id)
