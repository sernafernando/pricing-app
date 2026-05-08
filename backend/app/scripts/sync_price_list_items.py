"""
Sincroniza tb_price_list_items desde el ERP via gbp-parser (scriptPriceListItems).

Modos de uso:
    # Full sync de la lista 4 (ML)
    python -m app.scripts.sync_price_list_items --price-list 4

    # Sync incremental desde fecha
    python -m app.scripts.sync_price_list_items --price-list 4 --update-from "2026-05-08T00:00:00"

    # Item puntual
    python -m app.scripts.sync_price_list_items --price-list 4 --item-id 14
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
from app.models.tb_price_list_items import TbPriceListItems

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WORKER_URL = settings.GBP_PARSER_URL


def fetch_price_list_items_from_erp(
    price_list_id: int | None = None,
    item_id: int | None = None,
    item_id_from: int | None = None,
    item_id_to: int | None = None,
    update_from: str | None = None,
    update_to: str | None = None,
) -> list[dict]:
    """Llama a scriptPriceListItems en el gbp-parser y devuelve los registros."""
    params: dict[str, Any] = {"strScriptLabel": "scriptPriceListItems"}
    if price_list_id is not None:
        params["priceListID"] = price_list_id
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


def parse_bool(valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.lower() in ("true", "1", "yes")
    return bool(valor)


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
        "prli_id": record.get("prli_id"),
        "item_id": record.get("item_id"),
        "prli_price": parse_decimal(record.get("prli_price")),
        "curr_id": record.get("curr_id"),
        "bra_id": record.get("bra_id"),
        "prli_price_PreLastUpdate": parse_decimal(record.get("prli_price_PreLastUpdate")),
        "curr_id_PreLastUpdate": record.get("curr_id_PreLastUpdate"),
        "prli_cd": parse_datetime(record.get("prli_cd")),
        "prli_updatedAt": parse_datetime(record.get("prli_updatedAt")),
        "prli_triggerUpdateCD": parse_datetime(record.get("prli_triggerUpdateCD")),
        "prli_lastModuleUpdate": record.get("prli_lastModuleUpdate"),
        "prli_lastRuleUpdate": parse_datetime(record.get("prli_lastRuleUpdate")),
        "user_id_lastUpdate": record.get("user_id_lastUpdate"),
        "prli_disabled4Rules": parse_bool(record.get("prli_disabled4Rules")),
    }


def _upsert_records(db: Session, registros: list[dict]) -> tuple[int, int]:
    """Bulk upsert con INSERT ... ON CONFLICT DO UPDATE (Postgres). Devuelve (nuevos, actualizados)."""
    payload = []
    for record in registros:
        datos = _record_to_datos(record)
        if datos["prli_id"] is None or datos["item_id"] is None:
            logger.warning(f"⚠️ Registro sin prli_id/item_id: {record}")
            continue
        payload.append(datos)

    if not payload:
        return (0, 0)

    # Saber cuántos ya existían (para distinguir nuevos vs actualizados en el reporte)
    keys = {(p["comp_id"], p["prli_id"], p["item_id"]) for p in payload}
    existing = (
        db.query(TbPriceListItems.comp_id, TbPriceListItems.prli_id, TbPriceListItems.item_id)
        .filter(
            (TbPriceListItems.comp_id.in_({k[0] for k in keys}))
            & (TbPriceListItems.prli_id.in_({k[1] for k in keys}))
            & (TbPriceListItems.item_id.in_({k[2] for k in keys}))
        )
        .all()
    )
    existentes = {(r[0], r[1], r[2]) for r in existing}
    actualizados = sum(1 for p in payload if (p["comp_id"], p["prli_id"], p["item_id"]) in existentes)
    nuevos = len(payload) - actualizados

    stmt = pg_insert(TbPriceListItems).values(payload)
    update_cols = {
        col.name: col for col in stmt.excluded if col.name not in ("comp_id", "prli_id", "item_id", "created_at")
    }
    stmt = stmt.on_conflict_do_update(index_elements=["comp_id", "prli_id", "item_id"], set_=update_cols)
    db.execute(stmt)

    return nuevos, actualizados


def sync_price_list_items(
    price_list_id: int | None = None,
    item_id: int | None = None,
    item_id_from: int | None = None,
    item_id_to: int | None = None,
    update_from: str | None = None,
    update_to: str | None = None,
) -> tuple[int, int]:
    """Sincronización standalone (abre y cierra su propia sesión)."""
    db = None
    try:
        logger.info("🔄 === Iniciando sincronización de tb_price_list_items ===")
        db = SessionLocal()

        registros = fetch_price_list_items_from_erp(
            price_list_id=price_list_id,
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


def sync_price_list_items_all(db: Session, price_list_id: int | None = None) -> tuple[int, int]:
    """Reutiliza sesión externa (uso en sync_all_incremental u orquestador). Sync (usa requests bloqueante).
    Si se llama desde un endpoint async, usar `await asyncio.to_thread(sync_price_list_items_all, db, ...)`."""
    logger.info("🔄 === Iniciando sincronización de tb_price_list_items ===")
    try:
        registros = fetch_price_list_items_from_erp(price_list_id=price_list_id)
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


def sync_price_list_items_incremental(
    db: Session, price_list_id: int | None = None, update_from: str | None = None
) -> tuple[int, int]:
    """Incremental: solo registros con prli_updatedAt >= update_from. Sync (usa requests bloqueante).

    Si no se pasa update_from, lo deduce del max(prli_updatedAt) local.
    Si se llama desde un endpoint async, usar `await asyncio.to_thread(...)`.
    """
    logger.info("🔄 === Iniciando sincronización incremental de tb_price_list_items ===")
    try:
        if update_from is None:
            q = db.query(TbPriceListItems.prli_updatedAt).order_by(TbPriceListItems.prli_updatedAt.desc())
            if price_list_id is not None:
                q = q.filter(TbPriceListItems.prli_id == price_list_id)
            last = q.first()
            update_from = last[0].isoformat() if last and last[0] else None
        logger.info(f"🔄 Sincronizando desde: {update_from}")

        registros = fetch_price_list_items_from_erp(price_list_id=price_list_id, update_from=update_from)
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

    parser = argparse.ArgumentParser(description="Sincronizar tb_price_list_items desde ERP")
    parser.add_argument("--price-list", type=int, help="ID de lista de precios (ej: 4 = ML)")
    parser.add_argument("--item-id", type=int, help="Item específico")
    parser.add_argument("--item-id-from", type=int, help="Rango desde item_id")
    parser.add_argument("--item-id-to", type=int, help="Rango hasta item_id")
    parser.add_argument("--update-from", type=str, help="Sync incremental desde fecha ISO (ej: 2026-05-08T00:00:00)")
    parser.add_argument("--update-to", type=str, help="Sync hasta fecha ISO")
    args = parser.parse_args()

    sync_price_list_items(
        price_list_id=args.price_list,
        item_id=args.item_id,
        item_id_from=args.item_id_from,
        item_id_to=args.item_id_to,
        update_from=args.update_from,
        update_to=args.update_to,
    )
