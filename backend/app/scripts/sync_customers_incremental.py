"""
Script para sincronizar clientes desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_customers_incremental
    python -m app.scripts.sync_customers_incremental --from-id 1 --to-id 50000
    python -m app.scripts.sync_customers_incremental --cust-id 12345
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from datetime import datetime
import requests
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tb_customer import TBCustomer
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_customers_from_erp(cust_id: int = None, from_cust_id: int = None, to_cust_id: int = None):
    """
    Obtiene clientes desde el ERP vía gbp-parser.

    Args:
        cust_id: ID de cliente específico
        from_cust_id: ID desde (para paginación)
        to_cust_id: ID hasta (para paginación)

    Returns:
        Lista de registros
    """
    params = {"strScriptLabel": "scriptCustomer"}

    if cust_id:
        params["custID"] = cust_id
    if from_cust_id:
        params["fromCustID"] = from_cust_id
    if to_cust_id:
        params["toCustID"] = to_cust_id

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


def parse_datetime(value):
    """Parsea un valor de fecha/hora desde el ERP."""
    if not value:
        return None
    try:
        if "T" in str(value):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        else:
            return datetime.strptime(str(value), "%m/%d/%Y %I:%M:%S %p")
    except:
        return None


def parse_bool(value):
    """Parsea un valor booleano desde el ERP."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def sync_customers(from_cust_id: int = None, to_cust_id: int = None, cust_id: int = None, batch_size: int = 10000):
    """
    Sincroniza clientes desde el ERP.

    Args:
        from_cust_id: ID desde
        to_cust_id: ID hasta
        cust_id: ID específico
        batch_size: Tamaño del batch para paginación
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de clientes ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Si es un cliente específico
        if cust_id:
            registros_erp = fetch_customers_from_erp(cust_id=cust_id)
            from_id = cust_id
            to_id = cust_id
        else:
            # Si no hay rango, determinar el último ID que tenemos
            if not from_cust_id:
                last_record = db_local.query(TBCustomer).order_by(TBCustomer.cust_id.desc()).first()
                from_id = (last_record.cust_id + 1) if last_record else 1
            else:
                from_id = from_cust_id

            to_id = to_cust_id or (from_id + batch_size - 1)
            registros_erp = fetch_customers_from_erp(from_cust_id=from_id, to_cust_id=to_id)

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Obtener IDs existentes
        cust_ids = [r.get("cust_id") for r in registros_erp if r.get("cust_id")]
        existing = db_local.query(TBCustomer.cust_id).filter(TBCustomer.cust_id.in_(cust_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            cust_id_val = record.get("cust_id")

            if not cust_id_val:
                logger.warning(f"Registro sin cust_id: {record}")
                continue

            # Preparar datos
            datos = {
                "comp_id": record.get("comp_id", 1),
                "cust_id": cust_id_val,
                "bra_id": record.get("bra_id"),
                "cust_name": record.get("cust_name"),
                "cust_name1": record.get("cust_name1"),
                "fc_id": record.get("fc_id"),
                "cust_taxnumber": record.get("cust_taxNumber"),
                "tnt_id": record.get("tnt_id"),
                "cust_address": record.get("cust_address"),
                "cust_city": record.get("cust_city"),
                "cust_zip": record.get("cust_zip"),
                "country_id": record.get("country_id"),
                "state_id": record.get("state_id"),
                "cust_phone1": record.get("cust_phone1"),
                "cust_cellphone": record.get("cust_cellPhone"),
                "cust_email": record.get("cust_email"),
                "sm_id": record.get("sm_id"),
                "sm_id_2": record.get("sm_id_2"),
                "cust_inactive": parse_bool(record.get("cust_inactive")),
                "prli_id": record.get("prli_id"),
                "cust_mercadolibrenickname": record.get("cust_MercadoLibreNickName"),
                "cust_mercadolibreid": record.get("cust_MercadoLibreID"),
                "cust_cd": parse_datetime(record.get("cust_cd")),
                "cust_lastupdate": parse_datetime(record.get("cust_LastUpdate")),
            }

            # Verificar si existe
            if cust_id_val in ids_existentes:
                # Actualizar
                db_local.query(TBCustomer).filter(
                    TBCustomer.comp_id == datos["comp_id"], TBCustomer.cust_id == cust_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                # Insertar nuevo
                nuevo_registro = TBCustomer(**datos)
                db_local.add(nuevo_registro)
                total_nuevos += 1

            # Commit cada 500 registros
            if (total_nuevos + total_actualizados) % 500 == 0:
                db_local.commit()
                logger.info(f"  Procesados: {total_nuevos + total_actualizados}")

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


async def sync_customers_incremental(db: Session, batch_size: int = 10000):
    """
    Versión async para usar en sync_all_incremental.
    Sincroniza registros nuevos desde el último cust_id que tenemos.

    Args:
        db: Sesión de base de datos
        batch_size: Tamaño del batch

    Returns:
        tuple: (nuevos, actualizados)
    """
    logger.info("=== Iniciando sincronización incremental de clientes ===")

    try:
        # Obtener el último registro que tenemos
        last_record = db.query(TBCustomer).order_by(TBCustomer.cust_id.desc()).first()

        from_id = (last_record.cust_id + 1) if last_record else 1

        logger.info(f"Sincronizando desde cust_id={from_id}")

        total_nuevos = 0
        total_actualizados = 0
        batch_num = 0

        while True:
            batch_num += 1
            to_id = from_id + batch_size - 1

            logger.info(f"\n--- Batch {batch_num}: cust_id {from_id} a {to_id} ---")

            # Obtener registros del ERP
            registros_erp = fetch_customers_from_erp(from_cust_id=from_id, to_cust_id=to_id)

            logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

            if not registros_erp:
                logger.info("No hay más registros para sincronizar")
                break

            # Obtener IDs existentes
            cust_ids = [r.get("cust_id") for r in registros_erp if r.get("cust_id")]
            existing = db.query(TBCustomer.cust_id).filter(TBCustomer.cust_id.in_(cust_ids)).all()
            ids_existentes = {id[0] for id in existing}

            # Procesar registros
            nuevos = 0
            actualizados = 0

            for record in registros_erp:
                cust_id_val = record.get("cust_id")

                if not cust_id_val:
                    continue

                # Preparar datos
                datos = {
                    "comp_id": record.get("comp_id", 1),
                    "cust_id": cust_id_val,
                    "bra_id": record.get("bra_id"),
                    "cust_name": record.get("cust_name"),
                    "cust_name1": record.get("cust_name1"),
                    "fc_id": record.get("fc_id"),
                    "cust_taxnumber": record.get("cust_taxNumber"),
                    "tnt_id": record.get("tnt_id"),
                    "cust_address": record.get("cust_address"),
                    "cust_city": record.get("cust_city"),
                    "cust_zip": record.get("cust_zip"),
                    "country_id": record.get("country_id"),
                    "state_id": record.get("state_id"),
                    "cust_phone1": record.get("cust_phone1"),
                    "cust_cellphone": record.get("cust_cellPhone"),
                    "cust_email": record.get("cust_email"),
                    "sm_id": record.get("sm_id"),
                    "sm_id_2": record.get("sm_id_2"),
                    "cust_inactive": parse_bool(record.get("cust_inactive")),
                    "prli_id": record.get("prli_id"),
                    "cust_mercadolibrenickname": record.get("cust_MercadoLibreNickName"),
                    "cust_mercadolibreid": record.get("cust_MercadoLibreID"),
                    "cust_cd": parse_datetime(record.get("cust_cd")),
                    "cust_lastupdate": parse_datetime(record.get("cust_LastUpdate")),
                }

                # Verificar si existe
                if cust_id_val in ids_existentes:
                    db.query(TBCustomer).filter(
                        TBCustomer.comp_id == datos["comp_id"], TBCustomer.cust_id == cust_id_val
                    ).update(datos)
                    actualizados += 1
                else:
                    nuevo_registro = TBCustomer(**datos)
                    db.add(nuevo_registro)
                    nuevos += 1

            # Commit batch
            db.commit()

            logger.info(f"Batch {batch_num}: {nuevos} nuevos, {actualizados} actualizados")
            total_nuevos += nuevos
            total_actualizados += actualizados

            # Avanzar al siguiente rango
            from_id = to_id + 1

            # Si no hay nuevos, terminamos
            if nuevos == 0 and actualizados == 0:
                logger.info("No hay registros nuevos, sync completo")
                break

        logger.info(f"Sincronización completada: {total_nuevos} nuevos, {total_actualizados} actualizados")
        return (total_nuevos, total_actualizados)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        db.rollback()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sincronizar clientes desde ERP")
    parser.add_argument("--from-id", type=int, help="ID de cliente desde")
    parser.add_argument("--to-id", type=int, help="ID de cliente hasta")
    parser.add_argument("--cust-id", type=int, help="ID de cliente específico")
    parser.add_argument("--batch-size", type=int, default=10000, help="Cantidad de registros por batch")

    args = parser.parse_args()

    sync_customers(from_cust_id=args.from_id, to_cust_id=args.to_id, cust_id=args.cust_id, batch_size=args.batch_size)
