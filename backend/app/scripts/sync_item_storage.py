"""
Sincroniza tb_item_storage desde el ERP via gbp-parser (scriptItemStorage).

Modos de uso:
    # Full sync del depósito 1
    python -m app.scripts.sync_item_storage --stor 1

    # Sync incremental desde fecha
    python -m app.scripts.sync_item_storage --stor 1 --update-from "2026-05-08T00:00:00"

    # Item puntual
    python -m app.scripts.sync_item_storage --stor 1 --item-id 14
"""

import logging
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tb_item_storage import TbItemStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WORKER_URL = settings.GBP_PARSER_URL


def fetch_item_storage_from_erp(
    stor_id: int | None = None,
    item_id: int | None = None,
    item_id_from: int | None = None,
    item_id_to: int | None = None,
    update_from: str | None = None,
    update_to: str | None = None,
) -> list[dict]:
    """Llama a scriptItemStorage en el gbp-parser y devuelve los registros."""
    params: dict[str, Any] = {"strScriptLabel": "scriptItemStorage"}
    if stor_id is not None:
        params["storID"] = stor_id
    if item_id is not None:
        params["itemID"] = item_id
    if item_id_from is not None:
        params["itemIDfrom"] = item_id_from
    if item_id_to is not None:
        params["itemIDto"] = item_id_to
    if update_from is not None:
        params["updateFromDate"] = update_from
    if update_to is not None:
        params["updateToDate"] = update_to

    logger.info(f"🔄 Consultando ERP con params: {params}")

    response = requests.get(WORKER_URL, params=params, timeout=300)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        logger.error(f"❌ Respuesta inesperada del worker: {type(data)}")
        return []
    return data


def parse_decimal(valor):
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (ValueError, ArithmeticError):
        return None


def parse_datetime(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _record_to_datos(record: dict) -> dict:
    return {
        "comp_id": record.get("comp_id", 1),
        "stor_id": record.get("stor_id"),
        "item_id": record.get("item_id"),
        "itst_cant": parse_decimal(record.get("itst_cant")),
        "itst_PickingLocation": record.get("itst_PickingLocation") or None,
        "itst_StorageLocation": record.get("itst_StorageLocation") or None,
        "itst_cd": parse_datetime(record.get("itst_cd")),
        "itst_updateByInTransitStock": parse_datetime(record.get("itst_updateByInTransitStock")),
        "itst_LastAvailableInRelalculation": parse_datetime(record.get("itst_LastAvailableInRelalculation")),
        "itst_LastQTYAtQuery": parse_datetime(record.get("itst_LastQTYAtQuery")),
    }


def _upsert_records(db: Session, registros: list[dict]) -> tuple[int, int]:
    """Bulk upsert con INSERT ... ON CONFLICT DO UPDATE (Postgres). Devuelve (nuevos, actualizados)."""
    payload = []
    for record in registros:
        datos = _record_to_datos(record)
        if datos["stor_id"] is None or datos["item_id"] is None:
            logger.warning(f"⚠️ Registro sin stor_id/item_id: {record}")
            continue
        payload.append(datos)

    if not payload:
        return (0, 0)

    keys = {(p["comp_id"], p["stor_id"], p["item_id"]) for p in payload}
    existing = (
        db.query(TbItemStorage.comp_id, TbItemStorage.stor_id, TbItemStorage.item_id)
        .filter(
            (TbItemStorage.comp_id.in_({k[0] for k in keys}))
            & (TbItemStorage.stor_id.in_({k[1] for k in keys}))
            & (TbItemStorage.item_id.in_({k[2] for k in keys}))
        )
        .all()
    )
    existentes = {(r[0], r[1], r[2]) for r in existing}
    actualizados = sum(1 for p in payload if (p["comp_id"], p["stor_id"], p["item_id"]) in existentes)
    nuevos = len(payload) - actualizados

    stmt = pg_insert(TbItemStorage).values(payload)
    update_cols = {
        col.name: col for col in stmt.excluded if col.name not in ("comp_id", "stor_id", "item_id", "created_at")
    }
    stmt = stmt.on_conflict_do_update(index_elements=["comp_id", "stor_id", "item_id"], set_=update_cols)
    db.execute(stmt)

    return nuevos, actualizados


def sync_item_storage(
    stor_id: int | None = None,
    item_id: int | None = None,
    item_id_from: int | None = None,
    item_id_to: int | None = None,
    update_from: str | None = None,
    update_to: str | None = None,
) -> tuple[int, int]:
    """Sincronización standalone (abre y cierra su propia sesión)."""
    db = None
    try:
        logger.info("🔄 === Iniciando sincronización de tb_item_storage ===")
        db = SessionLocal()

        registros = fetch_item_storage_from_erp(
            stor_id=stor_id,
            item_id=item_id,
            item_id_from=item_id_from,
            item_id_to=item_id_to,
            update_from=update_from,
            update_to=update_to,
        )
        logger.info(f"✅ Recibidos {len(registros)} registros del ERP")

        if not registros:
            return (0, 0)

        nuevos, actualizados = _upsert_records(db, registros)
        db.commit()

        logger.info("✅ === Sincronización completada ===")
        logger.info(f"  Total nuevos: {nuevos}")
        logger.info(f"  Total actualizados: {actualizados}")
        return (nuevos, actualizados)

    except Exception:
        logger.exception("❌ Error durante la sincronización")
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()


def sync_item_storage_all(db: Session, stor_id: int | None = None) -> tuple[int, int]:
    """Reutiliza sesión externa. Sync (usa requests bloqueante).
    Si se llama desde un endpoint async, usar `await asyncio.to_thread(sync_item_storage_all, db, ...)`."""
    logger.info("🔄 === Iniciando sincronización de tb_item_storage ===")
    try:
        registros = fetch_item_storage_from_erp(stor_id=stor_id)
        logger.info(f"✅ Recibidos {len(registros)} registros del ERP")
        if not registros:
            return (0, 0)
        nuevos, actualizados = _upsert_records(db, registros)
        db.commit()
        logger.info(f"✅ Sincronización completada: {nuevos} nuevos, {actualizados} actualizados")
        return (nuevos, actualizados)
    except Exception:
        logger.exception("❌ Error durante la sincronización")
        db.rollback()
        raise


def sync_item_storage_incremental(
    db: Session, stor_id: int | None = None, update_from: str | None = None
) -> tuple[int, int]:
    """Incremental: solo registros modificados desde `update_from`. Sync (usa requests bloqueante).

    Si no se pasa `update_from`, lo deduce del max(COALESCE(itst_LastAvailableInRelalculation, itst_cd)) local.
    Usa COALESCE porque items recién creados pueden tener `itst_LastAvailableInRelalculation = NULL`
    hasta que se ejecute la primera recalculación de stock; `itst_cd` (creation date) sí siempre está.
    Si se llama desde un endpoint async, usar `await asyncio.to_thread(...)`.
    """
    from sqlalchemy import func

    logger.info("🔄 === Iniciando sincronización incremental de tb_item_storage ===")
    try:
        if update_from is None:
            efectiva = func.coalesce(TbItemStorage.itst_LastAvailableInRelalculation, TbItemStorage.itst_cd)
            q = db.query(func.max(efectiva))
            if stor_id is not None:
                q = q.filter(TbItemStorage.stor_id == stor_id)
            last = q.scalar()
            update_from = last.isoformat() if last else None
        logger.info(f"🔄 Sincronizando desde: {update_from}")

        registros = fetch_item_storage_from_erp(stor_id=stor_id, update_from=update_from)
        logger.info(f"✅ Recibidos {len(registros)} registros nuevos del ERP")
        if not registros:
            return (0, 0)
        nuevos, actualizados = _upsert_records(db, registros)
        db.commit()
        logger.info(f"✅ Sincronización incremental completada: {nuevos} nuevos, {actualizados} actualizados")
        return (nuevos, actualizados)
    except Exception:
        logger.exception("❌ Error durante la sincronización")
        db.rollback()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sincronizar tb_item_storage desde ERP")
    parser.add_argument("--stor", type=int, help="ID del depósito (ej: 1 = principal)")
    parser.add_argument("--item-id", type=int, help="Item específico")
    parser.add_argument("--item-id-from", type=int, help="Rango desde item_id")
    parser.add_argument("--item-id-to", type=int, help="Rango hasta item_id")
    parser.add_argument("--update-from", type=str, help="Sync incremental desde fecha ISO")
    parser.add_argument("--update-to", type=str, help="Sync hasta fecha ISO")
    args = parser.parse_args()

    sync_item_storage(
        stor_id=args.stor,
        item_id=args.item_id,
        item_id_from=args.item_id_from,
        item_id_to=args.item_id_to,
        update_from=args.update_from,
        update_to=args.update_to,
    )
