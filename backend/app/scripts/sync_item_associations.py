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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_item_associations_from_erp(
    itema_id: int = None, itema_id_4update: int = None, item_id: int = None, item1_id: int = None
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
    params = {"strScriptLabel": "scriptItemAssociation"}

    if itema_id:
        params["itemAID"] = itema_id
    if itema_id_4update:
        params["itemAID4update"] = itema_id_4update
    if item_id:
        params["itemID"] = item_id
    if item1_id:
        params["item1ID"] = item1_id

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
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def parse_decimal(value):
    """Parsea un valor decimal desde el ERP."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except:
        return None


def reconciliar_asociaciones_combo(db: Session, item_id: int, itema_ids_vigentes: list[int]) -> int:
    """
    Elimina las asociaciones locales de un combo que ya no existen en el ERP.

    Cuando en el ERP se modifica un combo (se cambia un componente por otro), la
    fila vieja de la asociación se borra en el origen. El sync es upsert puro y
    nunca reflejaba ese borrado: la fila quedaba para siempre en la tabla local
    con `iasso_qty > 0`, y el prearmador la mostraba como un componente fantasma
    que el combo "todavía tiene".

    Esta función reconcilia un combo puntual: recibe la lista COMPLETA de
    `itema_id` que el ERP devolvió para ese combo y borra localmente toda fila de
    ese combo cuyo `itema_id` no esté en la lista.

    Guard: si `itema_ids_vigentes` viene vacío no borra nada y retorna 0. Una
    respuesta vacía del ERP puede ser un fetch fallido — borrar en ese caso se
    llevaría puestas asociaciones válidas.

    Args:
        db: sesión SQLAlchemy ya abierta — no se commitea acá.
        item_id: id del item combo (padre) en tb_item_association.
        itema_ids_vigentes: itema_id de TODAS las asociaciones que el ERP
            devolvió para este combo.

    Returns:
        Cantidad de filas locales eliminadas.
    """
    if not itema_ids_vigentes:
        logger.warning(
            f"⚠️ Reconciliación omitida para combo item_id={item_id}: "
            f"el ERP no devolvió asociaciones (posible fetch fallido)"
        )
        return 0

    eliminadas = (
        db.query(TbItemAssociation)
        .filter(
            TbItemAssociation.item_id == item_id,
            TbItemAssociation.itema_id.notin_(itema_ids_vigentes),
        )
        .delete(synchronize_session=False)
    )

    if eliminadas:
        logger.info(f"🔄 Reconciliación combo item_id={item_id}: {eliminadas} asociación(es) fantasma eliminada(s)")
    return eliminadas


# Fracción mínima del padrón local que el fetch completo debe alcanzar para que
# la reconciliación global se considere segura. Un fetch truncado o a medio
# fallar devuelve muchas menos filas; borrar globalmente en ese caso vaciaría la
# tabla. Con un padrón sano el fetch completo trae ~100% de lo local, así que un
# piso del 50% deja margen amplio sin habilitar borrados catastróficos.
RECONCILIACION_GLOBAL_PISO = 0.5


def reconciliar_asociaciones_global(
    db: Session, itema_ids_erp: list[int], comp_ids_erp: set[int], local_count_pre: int
) -> int:
    """
    Elimina toda asociación local ausente del dataset COMPLETO del ERP.

    Versión a escala global de `reconciliar_asociaciones_combo`. El sync es upsert
    puro y nunca refleja los borrados del ERP, así que las filas viejas de combos
    modificados quedan como componentes fantasma. En un full sync (fetch sin
    filtros) el ERP devuelve TODAS las asociaciones vigentes, por lo que cualquier
    `itema_id` local que no esté en esa respuesta es un fantasma y se borra.

    El borrado se acota a las compañías (`comp_id`) que el ERP efectivamente
    devolvió: la clave de la tabla es `(comp_id, itema_id)` y el fetch sin filtros
    puede traer solo una compañía. Borrar por `itema_id` a secas se llevaría filas
    válidas de otra `comp_id` cuyo id no figure en la respuesta. Solo tocamos las
    compañías de las que el ERP nos habló.

    Un borrado global mal disparado vacía la tabla, así que solo se ejecuta bajo
    dos guards (el caller ya garantiza que no hay filas sin `itema_id`):
    - `itema_ids_erp` no vacío — una respuesta vacía es un fetch fallido.
    - El ERP devolvió al menos `RECONCILIACION_GLOBAL_PISO` del padrón local
      previo — protege contra un fetch truncado que se llevaría filas válidas.

    Args:
        db: sesión SQLAlchemy ya abierta — no se commitea acá.
        itema_ids_erp: itema_id de TODAS las asociaciones que el ERP devolvió en
            el fetch sin filtros.
        comp_ids_erp: comp_id presentes en la respuesta del ERP. El borrado se
            limita a estas compañías.
        local_count_pre: cantidad de filas locales ANTES de procesar este sync,
            para el guard de completitud.

    Returns:
        Cantidad de filas locales eliminadas.
    """
    if not itema_ids_erp:
        logger.warning("⚠️ Reconciliación global omitida: el ERP no devolvió asociaciones (posible fetch fallido)")
        return 0

    if local_count_pre and len(itema_ids_erp) < local_count_pre * RECONCILIACION_GLOBAL_PISO:
        logger.warning(
            f"⚠️ Reconciliación global omitida: el ERP devolvió {len(itema_ids_erp)} asociaciones "
            f"contra {local_count_pre} locales (por debajo del piso {RECONCILIACION_GLOBAL_PISO:.0%}, "
            f"posible fetch truncado)"
        )
        return 0

    eliminadas = (
        db.query(TbItemAssociation)
        .filter(
            TbItemAssociation.comp_id.in_(comp_ids_erp),
            TbItemAssociation.itema_id.notin_(itema_ids_erp),
        )
        .delete(synchronize_session=False)
    )

    if eliminadas:
        logger.info(f"🔄 Reconciliación global: {eliminadas} asociación(es) fantasma eliminada(s)")
    return eliminadas


def sync_item_associations(
    itema_id: int = None, itema_id_4update: int = None, item_id: int = None, item1_id: int = None
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
            itema_id=itema_id, itema_id_4update=itema_id_4update, item_id=item_id, item1_id=item1_id
        )

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Padrón local previo: lo necesita el guard de completitud de la
        # reconciliación global (no borrar si el fetch vino sospechosamente corto).
        local_count_pre = db_local.query(TbItemAssociation).count()

        # Obtener IDs existentes
        itema_ids = [r.get("itema_id") for r in registros_erp if r.get("itema_id")]
        existing = db_local.query(TbItemAssociation.itema_id).filter(TbItemAssociation.itema_id.in_(itema_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            itema_id_val = record.get("itema_id")

            if not itema_id_val:
                logger.warning(f"Registro sin itema_id: {record}")
                continue

            # Preparar datos
            datos = {
                "comp_id": record.get("comp_id", 1),
                "itema_id": itema_id_val,
                "item_id": record.get("item_id"),
                "item_id_1": record.get("item_id_1"),
                "iasso_qty": parse_decimal(record.get("iasso_qty")),
                "itema_canDeleteInSO": parse_bool(record.get("itema_canDeleteInSO")),
                "itema_discountPercentage4PriceListSUM": parse_decimal(
                    record.get("itema_discountPercentage4PriceListSUM")
                ),
            }

            # Verificar si existe
            if itema_id_val in ids_existentes:
                # Actualizar
                db_local.query(TbItemAssociation).filter(
                    TbItemAssociation.comp_id == datos["comp_id"], TbItemAssociation.itema_id == itema_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                # Insertar nuevo
                nuevo_registro = TbItemAssociation(**datos)
                db_local.add(nuevo_registro)
                total_nuevos += 1

        # Reconciliación por combo: si la sincronización fue scopeada a un combo
        # puntual (item_id, sin otros filtros), el ERP devolvió su BOM COMPLETA.
        # Borramos las asociaciones locales de ese combo que ya no existen en el
        # origen — los componentes fantasma de un combo que fue modificado.
        sin_filtros = not item_id and not itema_id and not itema_id_4update and not item1_id
        if item_id and not itema_id and not itema_id_4update and not item1_id:
            itema_ids_vigentes = [r.get("itema_id") for r in registros_erp if r.get("itema_id")]
            # Si algún registro vino sin itema_id, la respuesta es parcial y la
            # lista de "vigentes" quedaría incompleta — reconciliar borraría
            # asociaciones válidas. Ante una respuesta parcial, no reconciliamos.
            if len(itema_ids_vigentes) != len(registros_erp):
                logger.warning(
                    f"⚠️ Reconciliación omitida para combo item_id={item_id}: "
                    f"el ERP devolvió registros sin itema_id (respuesta parcial)"
                )
            else:
                reconciliar_asociaciones_combo(db_local, item_id, itema_ids_vigentes)

        # Reconciliación global: el full sync (sin ningún filtro) trae TODO el
        # padrón de asociaciones del ERP. Es el camino que corre el sync periódico
        # (`sync_master_tables_small`), así que es acá donde se barren los
        # componentes fantasma de combos modificados — el upsert nunca los borraba.
        elif sin_filtros:
            itema_ids_erp = [r.get("itema_id") for r in registros_erp if r.get("itema_id")]
            comp_ids_erp = {r.get("comp_id", 1) for r in registros_erp if r.get("itema_id")}
            # Misma salvaguarda parcial que la reconciliación por combo: si faltan
            # itema_id la respuesta es incompleta y un borrado global se llevaría
            # filas válidas.
            if len(itema_ids_erp) != len(registros_erp):
                logger.warning(
                    "⚠️ Reconciliación global omitida: el ERP devolvió registros sin itema_id (respuesta parcial)"
                )
            else:
                reconciliar_asociaciones_global(db_local, itema_ids_erp, comp_ids_erp, local_count_pre)

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

        # Padrón local previo para el guard de completitud de la reconciliación.
        local_count_pre = db.query(TbItemAssociation).count()

        # Obtener IDs existentes
        itema_ids = [r.get("itema_id") for r in registros_erp if r.get("itema_id")]
        existing = db.query(TbItemAssociation.itema_id).filter(TbItemAssociation.itema_id.in_(itema_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            itema_id_val = record.get("itema_id")

            if not itema_id_val:
                continue

            # Preparar datos
            datos = {
                "comp_id": record.get("comp_id", 1),
                "itema_id": itema_id_val,
                "item_id": record.get("item_id"),
                "item_id_1": record.get("item_id_1"),
                "iasso_qty": parse_decimal(record.get("iasso_qty")),
                "itema_canDeleteInSO": parse_bool(record.get("itema_canDeleteInSO")),
                "itema_discountPercentage4PriceListSUM": parse_decimal(
                    record.get("itema_discountPercentage4PriceListSUM")
                ),
            }

            # Verificar si existe
            if itema_id_val in ids_existentes:
                db.query(TbItemAssociation).filter(
                    TbItemAssociation.comp_id == datos["comp_id"], TbItemAssociation.itema_id == itema_id_val
                ).update(datos)
                total_actualizados += 1
            else:
                nuevo_registro = TbItemAssociation(**datos)
                db.add(nuevo_registro)
                total_nuevos += 1

        # Reconciliación global: este es un full sync (fetch sin filtros), así que
        # el ERP devolvió TODO el padrón. Barremos las asociaciones fantasma que el
        # upsert nunca borraba. Si faltan itema_id la respuesta es parcial y un
        # borrado global se llevaría filas válidas — no reconciliamos en ese caso.
        if len(itema_ids) != len(registros_erp):
            logger.warning(
                "⚠️ Reconciliación global omitida: el ERP devolvió registros sin itema_id (respuesta parcial)"
            )
        else:
            comp_ids_erp = {r.get("comp_id", 1) for r in registros_erp if r.get("itema_id")}
            reconciliar_asociaciones_global(db, itema_ids, comp_ids_erp, local_count_pre)

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
        last_id_result = db.query(TbItemAssociation.itema_id).order_by(TbItemAssociation.itema_id.desc()).first()

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
        itema_ids = [r.get("itema_id") for r in registros_erp if r.get("itema_id")]
        existing = db.query(TbItemAssociation.itema_id).filter(TbItemAssociation.itema_id.in_(itema_ids)).all()
        ids_existentes = {id[0] for id in existing}

        # Procesar registros
        for record in registros_erp:
            itema_id_val = record.get("itema_id")

            if not itema_id_val:
                continue

            # Preparar datos
            datos = {
                "comp_id": record.get("comp_id", 1),
                "itema_id": itema_id_val,
                "item_id": record.get("item_id"),
                "item_id_1": record.get("item_id_1"),
                "iasso_qty": parse_decimal(record.get("iasso_qty")),
                "itema_canDeleteInSO": parse_bool(record.get("itema_canDeleteInSO")),
                "itema_discountPercentage4PriceListSUM": parse_decimal(
                    record.get("itema_discountPercentage4PriceListSUM")
                ),
            }

            # Verificar si existe
            if itema_id_val in ids_existentes:
                db.query(TbItemAssociation).filter(
                    TbItemAssociation.comp_id == datos["comp_id"], TbItemAssociation.itema_id == itema_id_val
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

    parser = argparse.ArgumentParser(description="Sincronizar asociaciones de items desde ERP")
    parser.add_argument("--itema-id", type=int, help="ID específico de asociación")
    parser.add_argument("--from-id", type=int, help="ID de asociación desde (incremental)")
    parser.add_argument("--item-id", type=int, help="ID de item principal")
    parser.add_argument("--item1-id", type=int, help="ID de item asociado")

    args = parser.parse_args()

    sync_item_associations(
        itema_id=args.itema_id, itema_id_4update=args.from_id, item_id=args.item_id, item1_id=args.item1_id
    )
