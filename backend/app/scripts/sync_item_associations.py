"""
Script para sincronizar asociaciones de items desde el ERP.
Usa el gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_item_associations
    python -m app.scripts.sync_item_associations --item-id 123
    python -m app.scripts.sync_item_associations --itema-id 456
    python -m app.scripts.sync_item_associations --from-id 1000
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from decimal import Decimal
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tb_item_association import TbItemAssociation
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_item_associations_from_erp(
    itema_id: int = None,
    itema_id_4update: int = None,
    item_id: int = None,
    item1_id: int = None
):
    """
    Obtiene asociaciones de items desde el ERP vía gbp-parser.

    Args:
        itema_id: ID específico de asociación
        itema_id_4update: ID desde (para paginación incremental)
        item_id: ID de item principal
        item1_id: ID de item asociado

    Returns:
        Lista de registros
    """
    params = {
        'strScriptLabel': 'scriptItemAssociation'
    }

    if itema_id:
        params['itemAID'] = itema_id
    if itema_id_4update:
        params['itemAID4update'] = itema_id_4update
    if item_id:
        params['itemID'] = item_id
    if item1_id:
        params['item1ID'] = item1_id

    logger.info(f"Consultando ERP con params: {params}")

    try:
        response = requests.get(WORKER_URL, params=params, timeout=120)
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


def parse_decimal(value):
    """Parsea un valor decimal desde el ERP."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except:
        return None


def sync_item_associations(
    itema_id: int = None,
    itema_id_4update: int = None,
    item_id: int = None,
    item1_id: int = None
):
    """
    Sincroniza asociaciones de items desde el ERP.

    Args:
        itema_id: ID específico de asociación (opcional)
        itema_id_4update: ID desde para sync incremental
        item_id: ID de item principal
        item1_id: ID de item asociado
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de asociaciones de items ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_item_associations_from_erp(
            itema_id=itema_id,
            itema_id_4update=itema_id_4update,
            item_id=item_id,
            item1_id=item1_id
        )

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Obtener IDs existentes
        itema_ids = [r.get('itema_id') for r in registros_erp if r.get('itema_id')]
        existing = db_local.query(TbItemAssociation.itema_id).filter(
            TbItemAssociation.itema_id.in_(itema_ids)
        ).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            itema_id_val = record.get('itema_id')

            if not itema_id_val:
                logger.warning(f"Registro sin itema_id: {record}")
                continue

            # Preparar datos
            datos = {
                'comp_id': record.get('comp_id', 1),
                'itema_id': itema_id_val,
                'item_id': record.get('item_id'),
                'item_id_1': record.get('item_id_1'),
                'iasso_qty': parse_decimal(record.get('iasso_qty')),
                'itema_canDeleteInSO': parse_bool(record.get('itema_canDeleteInSO')),
                'itema_discountPercentage4PriceListSUM': parse_decimal(record.get('itema_discountPercentage4PriceListSUM')),
            }

            # Verificar si existe
            if itema_id_val in ids_existentes:
                # Actualizar
                db_local.query(TbItemAssociation).filter(
                    TbItemAssociation.comp_id == datos['comp_id'],
                    TbItemAssociation.itema_id == itema_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                # Insertar nuevo
                nuevo_registro = TbItemAssociation(**datos)
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


async def sync_item_associations_all(db: Session):
    """
    Versión async para usar en sync_all_incremental.
    Sincroniza todas las asociaciones de items.

    Args:
        db: Sesión de base de datos

    Returns:
        tuple: (nuevos, actualizados)
    """
    logger.info("=== Iniciando sincronización de asociaciones de items ===")

    try:
        # Obtener todos los registros del ERP
        registros_erp = fetch_item_associations_from_erp()

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        total_nuevos = 0
        total_actualizados = 0

        # Obtener IDs existentes
        itema_ids = [r.get('itema_id') for r in registros_erp if r.get('itema_id')]
        existing = db.query(TbItemAssociation.itema_id).filter(
            TbItemAssociation.itema_id.in_(itema_ids)
        ).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            itema_id_val = record.get('itema_id')

            if not itema_id_val:
                continue

            # Preparar datos
            datos = {
                'comp_id': record.get('comp_id', 1),
                'itema_id': itema_id_val,
                'item_id': record.get('item_id'),
                'item_id_1': record.get('item_id_1'),
                'iasso_qty': parse_decimal(record.get('iasso_qty')),
                'itema_canDeleteInSO': parse_bool(record.get('itema_canDeleteInSO')),
                'itema_discountPercentage4PriceListSUM': parse_decimal(record.get('itema_discountPercentage4PriceListSUM')),
            }

            # Verificar si existe
            if itema_id_val in ids_existentes:
                db.query(TbItemAssociation).filter(
                    TbItemAssociation.comp_id == datos['comp_id'],
                    TbItemAssociation.itema_id == itema_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                nuevo_registro = TbItemAssociation(**datos)
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


async def sync_item_associations_incremental(db: Session):
    """
    Versión async incremental para usar en sync_all_incremental.
    Sincroniza solo los registros nuevos desde el último itema_id.

    Args:
        db: Sesión de base de datos

    Returns:
        tuple: (nuevos, actualizados)
    """
    logger.info("=== Iniciando sincronización incremental de asociaciones de items ===")

    try:
        # Obtener el último itema_id en la base de datos local
        last_id_result = db.query(TbItemAssociation.itema_id).order_by(
            TbItemAssociation.itema_id.desc()
        ).first()

        last_id = last_id_result[0] if last_id_result else 0
        logger.info(f"Último itema_id en BD local: {last_id}")

        # Obtener registros del ERP desde ese ID
        registros_erp = fetch_item_associations_from_erp(itema_id_4update=last_id)

        logger.info(f"Recibidos {len(registros_erp)} registros nuevos del ERP")

        if not registros_erp:
            logger.info("No hay registros nuevos para sincronizar")
            return (0, 0)

        total_nuevos = 0
        total_actualizados = 0

        # Obtener IDs existentes (por si hay updates)
        itema_ids = [r.get('itema_id') for r in registros_erp if r.get('itema_id')]
        existing = db.query(TbItemAssociation.itema_id).filter(
            TbItemAssociation.itema_id.in_(itema_ids)
        ).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            itema_id_val = record.get('itema_id')

            if not itema_id_val:
                continue

            # Preparar datos
            datos = {
                'comp_id': record.get('comp_id', 1),
                'itema_id': itema_id_val,
                'item_id': record.get('item_id'),
                'item_id_1': record.get('item_id_1'),
                'iasso_qty': parse_decimal(record.get('iasso_qty')),
                'itema_canDeleteInSO': parse_bool(record.get('itema_canDeleteInSO')),
                'itema_discountPercentage4PriceListSUM': parse_decimal(record.get('itema_discountPercentage4PriceListSUM')),
            }

            # Verificar si existe
            if itema_id_val in ids_existentes:
                db.query(TbItemAssociation).filter(
                    TbItemAssociation.comp_id == datos['comp_id'],
                    TbItemAssociation.itema_id == itema_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                nuevo_registro = TbItemAssociation(**datos)
                db.add(nuevo_registro)
                total_nuevos += 1

        # Commit
        db.commit()

        logger.info(f"Sincronización incremental completada: {total_nuevos} nuevos, {total_actualizados} actualizados")
        return (total_nuevos, total_actualizados)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        db.rollback()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar asociaciones de items desde ERP')
    parser.add_argument(
        '--itema-id',
        type=int,
        help='ID específico de asociación'
    )
    parser.add_argument(
        '--from-id',
        type=int,
        help='ID de asociación desde (incremental)'
    )
    parser.add_argument(
        '--item-id',
        type=int,
        help='ID de item principal'
    )
    parser.add_argument(
        '--item1-id',
        type=int,
        help='ID de item asociado'
    )

    args = parser.parse_args()

    sync_item_associations(
        itema_id=args.itema_id,
        itema_id_4update=args.from_id,
        item_id=args.item_id,
        item1_id=args.item1_id
    )
