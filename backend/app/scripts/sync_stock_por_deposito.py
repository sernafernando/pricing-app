"""Sincroniza stock disponible por depósito desde el ERP via gbp-parser.

Para cada depósito conocido (DISTINCT stor_id de tb_item_storage) llama al
endpoint ``ItemStorage_funGetXMLData`` del gbp-parser con ese ``intStor_id`` y
hace UPSERT masivo en la tabla ``stock_por_deposito``.

El mismo ERP op alimenta ``productos_erp.stock`` (intStor_id=1) desde erp_sync.
Extendemos esa lógica a todos los depósitos para que los endpoints de consultas
(ranking, resumen, kpis) usen stock real disponible en vez de itst_cant espejo.

Modos de uso::

    python -m app.scripts.sync_stock_por_deposito

Cron recomendado (diario fuera de horario pico, después de sync_ageing)::

    0 3 * * * /path/to/venv/bin/python -m app.scripts.sync_stock_por_deposito \\
        >> /var/log/pricing/sync_stock_por_deposito.log 2>&1

El timeout HTTP por depósito es 300 s (igual que ERP_FETCH_TIMEOUT en erp_sync).
Errores por depósito individual se loguean y el script continúa con el siguiente.
"""

import asyncio
import logging
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

# Allow running standalone: ``python -m app.scripts.sync_stock_por_deposito``
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import httpx
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.stock_por_deposito import StockPorDeposito

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Timeout per-depot HTTP call — these can take tens of seconds.
GBP_PARSER_HTTP_TIMEOUT = 300.0

# Upsert batch size (rows per INSERT … ON CONFLICT DO UPDATE)
UPSERT_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Integer coercion (mirrors convertir_a_entero in erp_sync)
# ---------------------------------------------------------------------------


def _to_int(valor: Any, default: int = 0) -> int:
    """Convert a value to int, truncating decimals. Never raises."""
    try:
        return int(float(str(valor)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# ERP call
# ---------------------------------------------------------------------------


async def _fetch_stock_for_depot(stor_id: int) -> list[dict]:
    """Fetch available stock for a single depot from gbp-parser.

    Args:
        stor_id: The ERP storage/depot ID (intStor_id parameter).

    Returns:
        List of dicts with at least ``item_id`` and ``Stock`` keys.

    Raises:
        httpx.HTTPError: On network or non-2xx response.
        RuntimeError: If response is not a list.
    """
    params = {
        "opName": "ItemStorage_funGetXMLData",
        "intStor_id": stor_id,
        "intItem_id": -1,
    }
    async with httpx.AsyncClient(timeout=GBP_PARSER_HTTP_TIMEOUT) as client:
        resp = await client.get(settings.GBP_PARSER_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected gbp-parser response for stor_id={stor_id}: {data!r}")
    return data


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_depot_ids(db: Session) -> list[int]:
    """Return the distinct stor_ids present in tb_item_storage."""
    rows = db.execute(
        text("SELECT DISTINCT stor_id FROM tb_item_storage WHERE stor_id IS NOT NULL ORDER BY stor_id")
    ).fetchall()
    return [int(row[0]) for row in rows]


def _upsert_batch(db: Session, rows: list[dict]) -> None:
    """Bulk-upsert a batch of rows into stock_por_deposito.

    Args:
        db: Active SQLAlchemy session (no autocommit).
        rows: List of dicts with keys item_id, stor_id, stock, updated_at.
    """
    if not rows:
        return
    stmt = pg_insert(StockPorDeposito).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["item_id", "stor_id"],
        set_={
            "stock": stmt.excluded.stock,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# Main sync logic
# ---------------------------------------------------------------------------


async def sync_depot(db: Session, stor_id: int) -> int:
    """Sync stock for a single depot. Returns number of rows upserted."""
    logger.info("🔄 Sincronizando depósito stor_id=%d …", stor_id)
    raw = await _fetch_stock_for_depot(stor_id)

    now = datetime.now(UTC)
    batch: list[dict] = []
    total = 0

    for item in raw:
        item_id = _to_int(item.get("item_id"))
        if item_id <= 0:
            continue
        stock = _to_int(item.get("Stock", 0))
        batch.append(
            {
                "item_id": item_id,
                "stor_id": stor_id,
                "stock": stock,
                "updated_at": now,
            }
        )
        if len(batch) >= UPSERT_BATCH_SIZE:
            _upsert_batch(db, batch)
            total += len(batch)
            batch = []

    if batch:
        _upsert_batch(db, batch)
        total += len(batch)

    logger.info("✅ Depósito stor_id=%d: %d filas procesadas", stor_id, total)
    return total


async def run_sync() -> None:
    """Main entry point: sync all depots, commit once, rollback on fatal error."""
    db = SessionLocal()
    try:
        depot_ids = _get_depot_ids(db)
        if not depot_ids:
            logger.warning("⚠️ No se encontraron depósitos en tb_item_storage — nada que sincronizar")
            return

        logger.info("🔄 Iniciando sync de stock por depósito para %d depósitos: %s", len(depot_ids), depot_ids)
        grand_total = 0

        for stor_id in depot_ids:
            try:
                count = await sync_depot(db, stor_id)
                grand_total += count
            except httpx.HTTPError as exc:
                logger.error("❌ Error HTTP al obtener stock para stor_id=%d: %s — continuando", stor_id, exc)
            except RuntimeError as exc:
                logger.error("❌ Error de formato para stor_id=%d: %s — continuando", stor_id, exc)

        db.commit()
        logger.info("✅ Sync completado: %d filas upsertadas en total", grand_total)

    except Exception as exc:
        logger.error("❌ Error fatal durante sync_stock_por_deposito: %s", exc, exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(run_sync())
