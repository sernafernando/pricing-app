"""
Script para sincronizar el historial de costos de items desde el ERP.
Usa el Cloudflare Worker para obtener los datos.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from datetime import datetime
import requests
import json
from app.core.database import SessionLocal
from app.models.item_cost_list_history import ItemCostListHistory
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del Cloudflare Worker
WORKER_URL = "https://parser-worker-js.gaussonline.workers.dev/consulta?strScriptLabel=scriptItemCostListHistory"


def fetch_cost_history_from_erp(fecha_desde: datetime = None, iclh_id: int = None):
    """
    Obtiene el historial de costos desde el ERP vía Cloudflare Worker.

    Args:
        fecha_desde: Fecha desde la cual traer registros
        iclh_id: ID desde el cual traer registros (para paginación)

    Returns:
        Lista de registros
    """
    # Construir parámetros para el worker
    params = {}

    if fecha_desde:
        params['fromDate'] = fecha_desde.isoformat()

    if iclh_id:
        params['iclhID'] = iclh_id

    # El worker espera los parámetros en formato JSON
    # según el script SQL: JSON_VALUE(@strParamOUT, '$.fromDate')
    headers = {
        'Content-Type': 'application/json'
    }

    logger.info(f"Consultando ERP Worker con params: {params}")

    try:
        # POST con los parámetros en el body
        response = requests.post(WORKER_URL, json=params, headers=headers, timeout=30)
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


def sync_item_cost_history(
    fecha_desde: datetime = None,
    batch_size: int = 5000,
    test_mode: bool = False
):
    """
    Sincroniza el historial de costos desde el ERP.

    Args:
        fecha_desde: Solo sincronizar registros desde esta fecha
        batch_size: Cantidad de registros por batch
        test_mode: Si es True, solo procesa un batch
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de historial de costos ===")

        db_local = SessionLocal()

        # Si no hay fecha_desde, obtener el último registro que tenemos
        last_iclh_id = None
        if not fecha_desde:
            last_record = db_local.query(ItemCostListHistory).order_by(
                ItemCostListHistory.iclh_id.desc()
            ).first()

            if last_record:
                last_iclh_id = last_record.iclh_id
                logger.info(f"Último registro en DB: iclh_id={last_iclh_id}")

        total_nuevos = 0
        total_actualizados = 0
        batch_num = 0

        while True:
            batch_num += 1
            logger.info(f"\n--- Batch {batch_num} ---")

            # Obtener registros del ERP
            registros_erp = fetch_cost_history_from_erp(
                fecha_desde=fecha_desde,
                iclh_id=last_iclh_id
            )

            logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

            if not registros_erp:
                logger.info("No hay más registros para sincronizar")
                break

            # Obtener IDs existentes en este batch
            iclh_ids = [r.get('iclh_id') or r.get('iclhID') for r in registros_erp if r.get('iclh_id') or r.get('iclhID')]
            existing = db_local.query(ItemCostListHistory.iclh_id).filter(
                ItemCostListHistory.iclh_id.in_(iclh_ids)
            ).all()
            ids_existentes = {id[0] for id in existing}

            # Procesar registros
            nuevos = 0
            actualizados = 0

            for record in registros_erp:
                # El worker puede devolver iclh_id o iclhID
                iclh_id = record.get('iclh_id') or record.get('iclhID')

                if not iclh_id:
                    logger.warning(f"Registro sin iclh_id: {record}")
                    continue

                # Parsear fecha
                iclh_cd = None
                if record.get('iclh_cd'):
                    try:
                        iclh_cd = datetime.fromisoformat(record['iclh_cd'].replace('Z', '+00:00'))
                    except:
                        pass

                # Verificar si existe
                if iclh_id in ids_existentes:
                    # Actualizar
                    db_local.query(ItemCostListHistory).filter(
                        ItemCostListHistory.iclh_id == iclh_id
                    ).update({
                        'comp_id': record.get('comp_id'),
                        'coslis_id': record.get('coslis_id'),
                        'item_id': record.get('item_id'),
                        'iclh_lote': record.get('iclh_lote'),
                        'iclh_price': record.get('iclh_price'),
                        'iclh_price_aw': record.get('iclh_price_aw'),
                        'curr_id': record.get('curr_id'),
                        'iclh_cd': iclh_cd,
                        'user_id_lastupdate': record.get('user_id_lastUpdate')
                    })
                    actualizados += 1
                else:
                    # Insertar nuevo
                    nuevo_registro = ItemCostListHistory(
                        iclh_id=iclh_id,
                        comp_id=record.get('comp_id'),
                        coslis_id=record.get('coslis_id'),
                        item_id=record.get('item_id'),
                        iclh_lote=record.get('iclh_lote'),
                        iclh_price=record.get('iclh_price'),
                        iclh_price_aw=record.get('iclh_price_aw'),
                        curr_id=record.get('curr_id'),
                        iclh_cd=iclh_cd,
                        user_id_lastupdate=record.get('user_id_lastUpdate')
                    )
                    db_local.add(nuevo_registro)
                    nuevos += 1

                # Actualizar last_iclh_id para paginación
                if iclh_id > (last_iclh_id or 0):
                    last_iclh_id = iclh_id

            # Commit batch
            db_local.commit()

            logger.info(f"Batch {batch_num}: {nuevos} nuevos, {actualizados} actualizados")
            total_nuevos += nuevos
            total_actualizados += actualizados

            # Si es test mode, solo un batch
            if test_mode:
                logger.info("Modo test: deteniendo después de un batch")
                break

            # Si no hay nuevos registros en este batch, ya terminamos (estamos en loop)
            if nuevos == 0:
                logger.info("No hay registros nuevos en este batch, sync completo")
                break

            # Si recibimos menos registros que batch_size, terminamos
            if len(registros_erp) < batch_size:
                logger.info("Recibidos menos registros que batch_size, sync completo")
                break

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


async def sync_item_cost_history_incremental(db: Session):
    """
    Versión async para usar en sync_all_incremental.
    Sincroniza registros nuevos desde el último iclh_id que tenemos.

    Args:
        db: Sesión de base de datos

    Returns:
        tuple: (nuevos, actualizados)
    """
    logger.info("=== Iniciando sincronización incremental de historial de costos ===")

    try:
        # Obtener el último registro que tenemos
        last_record = db.query(ItemCostListHistory).order_by(
            ItemCostListHistory.iclh_id.desc()
        ).first()

        last_iclh_id = last_record.iclh_id if last_record else None

        if last_iclh_id:
            logger.info(f"Último registro en DB: iclh_id={last_iclh_id}")
        else:
            logger.info("No hay registros previos, sincronizando desde el inicio")

        total_nuevos = 0
        total_actualizados = 0
        batch_num = 0

        while True:
            batch_num += 1
            logger.info(f"\n--- Batch {batch_num} ---")

            # Obtener registros del ERP
            registros_erp = fetch_cost_history_from_erp(iclh_id=last_iclh_id)

            logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

            if not registros_erp:
                logger.info("No hay más registros para sincronizar")
                break

            # Obtener IDs existentes en este batch
            iclh_ids = [r.get('iclh_id') or r.get('iclhID') for r in registros_erp if r.get('iclh_id') or r.get('iclhID')]
            existing = db.query(ItemCostListHistory.iclh_id).filter(
                ItemCostListHistory.iclh_id.in_(iclh_ids)
            ).all()
            ids_existentes = {id[0] for id in existing}

            # Procesar registros
            nuevos = 0
            actualizados = 0

            for record in registros_erp:
                iclh_id = record.get('iclh_id') or record.get('iclhID')

                if not iclh_id:
                    continue

                # Parsear fecha
                iclh_cd = None
                if record.get('iclh_cd'):
                    try:
                        iclh_cd = datetime.fromisoformat(record['iclh_cd'].replace('Z', '+00:00'))
                    except:
                        pass

                # Verificar si existe
                if iclh_id in ids_existentes:
                    # Actualizar
                    db.query(ItemCostListHistory).filter(
                        ItemCostListHistory.iclh_id == iclh_id
                    ).update({
                        'comp_id': record.get('comp_id'),
                        'coslis_id': record.get('coslis_id'),
                        'item_id': record.get('item_id'),
                        'iclh_lote': record.get('iclh_lote'),
                        'iclh_price': record.get('iclh_price'),
                        'iclh_price_aw': record.get('iclh_price_aw'),
                        'curr_id': record.get('curr_id'),
                        'iclh_cd': iclh_cd,
                        'user_id_lastupdate': record.get('user_id_lastUpdate')
                    })
                    actualizados += 1
                else:
                    # Insertar nuevo
                    nuevo_registro = ItemCostListHistory(
                        iclh_id=iclh_id,
                        comp_id=record.get('comp_id'),
                        coslis_id=record.get('coslis_id'),
                        item_id=record.get('item_id'),
                        iclh_lote=record.get('iclh_lote'),
                        iclh_price=record.get('iclh_price'),
                        iclh_price_aw=record.get('iclh_price_aw'),
                        curr_id=record.get('curr_id'),
                        iclh_cd=iclh_cd,
                        user_id_lastupdate=record.get('user_id_lastUpdate')
                    )
                    db.add(nuevo_registro)
                    nuevos += 1

                # Actualizar last_iclh_id para paginación
                if iclh_id > (last_iclh_id or 0):
                    last_iclh_id = iclh_id

            # Commit batch
            db.commit()

            logger.info(f"Batch {batch_num}: {nuevos} nuevos, {actualizados} actualizados")
            total_nuevos += nuevos
            total_actualizados += actualizados

            # Si no hay nuevos registros en este batch, ya terminamos
            if nuevos == 0:
                logger.info("No hay registros nuevos en este batch, sync completo")
                break

            # Si recibimos menos de 5000 registros, terminamos
            if len(registros_erp) < 5000:
                logger.info("Recibidos menos registros que batch_size, sync completo")
                break

        logger.info(f"✅ Sincronización completada: {total_nuevos} nuevos, {total_actualizados} actualizados")
        return (total_nuevos, total_actualizados)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        db.rollback()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar historial de costos desde ERP')
    parser.add_argument(
        '--fecha-desde',
        type=str,
        help='Fecha desde (formato: YYYY-MM-DD)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=5000,
        help='Cantidad de registros por batch'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Modo test: solo un batch'
    )

    args = parser.parse_args()

    fecha_desde = None
    if args.fecha_desde:
        fecha_desde = datetime.strptime(args.fecha_desde, '%Y-%m-%d')

    sync_item_cost_history(
        fecha_desde=fecha_desde,
        batch_size=args.batch_size,
        test_mode=args.test
    )
