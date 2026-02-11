"""
Script para sincronizar sucursales desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_branches
    python -m app.scripts.sync_branches --bra-id 1
    python -m app.scripts.sync_branches --from-id 1 --to-id 100
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tb_branch import TBBranch
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_branches_from_erp(bra_id: int = None, from_bra_id: int = None, to_bra_id: int = None):
    """
    Obtiene sucursales desde el ERP vía gbp-parser.

    Args:
        bra_id: ID de sucursal específica
        from_bra_id: ID desde (para paginación)
        to_bra_id: ID hasta (para paginación)

    Returns:
        Lista de registros
    """
    params = {"strScriptLabel": "scriptBranch"}

    if bra_id:
        params["braID"] = bra_id
    if from_bra_id:
        params["frombraID"] = from_bra_id
    if to_bra_id:
        params["tobraID"] = to_bra_id

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


def sync_branches(bra_id: int = None, from_bra_id: int = None, to_bra_id: int = None):
    """
    Sincroniza sucursales desde el ERP.

    Args:
        bra_id: ID específico de sucursal (opcional)
        from_bra_id: ID desde (para paginación)
        to_bra_id: ID hasta (para paginación)
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de sucursales ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_branches_from_erp(bra_id=bra_id, from_bra_id=from_bra_id, to_bra_id=to_bra_id)

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Obtener IDs existentes
        bra_ids = [r.get("bra_id") for r in registros_erp if r.get("bra_id")]
        existing = db_local.query(TBBranch.bra_id).filter(TBBranch.bra_id.in_(bra_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            bra_id_val = record.get("bra_id")

            if not bra_id_val:
                logger.warning(f"Registro sin bra_id: {record}")
                continue

            # Preparar datos (columnas lowercase, .get() con camelCase del ERP)
            datos = {
                "comp_id": record.get("comp_id", 1),
                "bra_id": bra_id_val,
                "bra_desc": record.get("bra_desc"),
                "bra_maindesc": record.get("bra_mainDesc"),
                "country_id": record.get("country_id"),
                "state_id": record.get("state_id"),
                "bra_address": record.get("bra_address"),
                "bra_phone": record.get("bra_phone"),
                "bra_taxnumber": record.get("bra_taxNumber"),
                "bra_disabled": parse_bool(record.get("bra_disabled")),
            }

            # Verificar si existe
            if bra_id_val in ids_existentes:
                # Actualizar
                db_local.query(TBBranch).filter(
                    TBBranch.comp_id == datos["comp_id"], TBBranch.bra_id == bra_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                # Insertar nuevo
                nuevo_registro = TBBranch(**datos)
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


async def sync_branches_all(db: Session):
    """
    Versión async para usar en sync_all_incremental.
    Sincroniza todas las sucursales.

    Args:
        db: Sesión de base de datos

    Returns:
        tuple: (nuevos, actualizados)
    """
    logger.info("=== Iniciando sincronización de sucursales ===")

    try:
        # Obtener todos los registros del ERP
        registros_erp = fetch_branches_from_erp()

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        total_nuevos = 0
        total_actualizados = 0

        # Obtener IDs existentes
        bra_ids = [r.get("bra_id") for r in registros_erp if r.get("bra_id")]
        existing = db.query(TBBranch.bra_id).filter(TBBranch.bra_id.in_(bra_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            bra_id_val = record.get("bra_id")

            if not bra_id_val:
                continue

            # Preparar datos
            datos = {
                "comp_id": record.get("comp_id", 1),
                "bra_id": bra_id_val,
                "bra_desc": record.get("bra_desc"),
                "bra_maindesc": record.get("bra_mainDesc"),
                "country_id": record.get("country_id"),
                "state_id": record.get("state_id"),
                "bra_address": record.get("bra_address"),
                "bra_phone": record.get("bra_phone"),
                "bra_taxnumber": record.get("bra_taxNumber"),
                "bra_disabled": parse_bool(record.get("bra_disabled")),
            }

            # Verificar si existe
            if bra_id_val in ids_existentes:
                db.query(TBBranch).filter(TBBranch.comp_id == datos["comp_id"], TBBranch.bra_id == bra_id_val).update(
                    datos
                )
                total_actualizados += 1
            else:
                nuevo_registro = TBBranch(**datos)
                db.add(nuevo_registro)
                total_nuevos += 1

        # Commit
        db.commit()

        logger.info(f"Sincronización completada: {total_nuevos} nuevos, {total_actualizados} actualizados")
        return (total_nuevos, total_actualizados)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        db.rollback()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sincronizar sucursales desde ERP")
    parser.add_argument("--bra-id", type=int, help="ID de sucursal específica")
    parser.add_argument("--from-id", type=int, help="ID de sucursal desde")
    parser.add_argument("--to-id", type=int, help="ID de sucursal hasta")

    args = parser.parse_args()

    sync_branches(bra_id=args.bra_id, from_bra_id=args.from_id, to_bra_id=args.to_id)
