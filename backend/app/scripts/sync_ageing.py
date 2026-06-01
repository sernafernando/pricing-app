"""
Sincroniza productos_ageing desde el ERP via scriptAgeing.

scriptAgeing retorna el catálogo completo (~14 768 filas, ~5 MB) sin importar
la ventana de fechas — fromDate/toDate son requeridos por el endpoint pero no
filtran. El llamado tarda ~360s.

Este script delega la llamada SOAP al endpoint interno gbp-parser
(settings.GBP_PARSER_URL), que corre siempre junto a la app y maneja la
autenticación + retry de token. El endpoint tiene timeout=600s para scriptAgeing
(ver SCRIPT_TIMEOUTS en gbp_parser.py). El cliente HTTP de este script usa
GBP_PARSER_HTTP_TIMEOUT=620s para dar margen al server-side timeout.

Modos de uso:
    # Sync completo (ventana por defecto: desde 2000-01-01 hasta hoy)
    python -m app.scripts.sync_ageing

    # Ventana explícita (no cambia el resultado, requerida por el ERP)
    python -m app.scripts.sync_ageing --from-date "2020-01-01 00:00:00" --to-date "2026-12-31 23:59:59"

Cron recomendado (diario en horario de menor carga):
    # Ejecutar de lunes a domingo a las 02:30 AM
    30 2 * * * /path/to/venv/bin/python -m app.scripts.sync_ageing >> /var/log/pricing/sync_ageing.log 2>&1

Registro en el scheduler del proyecto:
    Ver backend/app/scripts/sync_all_incremental.sh — agregar entrada equivalente
    si se desea integración con el runner existente.
"""

import asyncio
import logging
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

# Add backend directory to path so the module is importable standalone
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.producto_ageing import ProductoAgeing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Timeout del cliente HTTP hacia el endpoint gbp-parser.
# Debe exceder el server-side timeout de scriptAgeing (600s en SCRIPT_TIMEOUTS).
GBP_PARSER_HTTP_TIMEOUT = 620.0

# Batch size para el upsert bulk (reduce memoria y presión en el pool)
UPSERT_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# ERP call via gbp-parser endpoint
# ---------------------------------------------------------------------------


async def _fetch_ageing(from_date: str, to_date: str) -> list[dict]:
    """Llama al endpoint interno gbp-parser para obtener las filas de scriptAgeing.

    Usa GET con query params porque el endpoint lee request.query_params en GET
    (y await request.json() en POST — que requeriría JSON body, no params).

    El endpoint ya maneja: autenticación ERP, token-expiry retry, SOAP envelope,
    y parsing XML → JSON. Devuelve list[dict] con las filas del catálogo.

    Args:
        from_date: Fecha inicio en formato "YYYY-MM-DD HH:MM:SS".
        to_date:   Fecha fin en formato "YYYY-MM-DD HH:MM:SS".

    Returns:
        Lista de dicts con las filas de scriptAgeing (puede ser vacía).

    Raises:
        RuntimeError: Si la respuesta HTTP no es 2xx o si el formato es inesperado.
    """
    params = {
        "strScriptLabel": "scriptAgeing",
        "fromDate": from_date,
        "toDate": to_date,
    }
    logger.info("🔄 Llamando a gbp-parser para scriptAgeing (timeout=%ss)…", GBP_PARSER_HTTP_TIMEOUT)
    async with httpx.AsyncClient(timeout=GBP_PARSER_HTTP_TIMEOUT) as client:
        resp = await client.get(settings.GBP_PARSER_URL, params=params)

    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list):
        raise RuntimeError(f"Respuesta inesperada del gbp-parser: {data!r}")

    return data


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_ageing_response(raw: Any) -> list[dict]:
    """Normaliza la respuesta del ERP a lista de filas.

    Args:
        raw: Lo que devuelve parse_soap_response() — se espera list[dict].

    Returns:
        Lista de dicts (puede estar vacía). Nunca lanza excepción.
    """
    if not isinstance(raw, list):
        logger.warning("⚠️ Respuesta inesperada del ERP (tipo %s) — se descarta", type(raw).__name__)
        return []
    return raw


# ---------------------------------------------------------------------------
# Código → item_id resolution
# ---------------------------------------------------------------------------


def _resolve_codigo_map(db: Session, codigos: set[str]) -> dict[str, int]:
    """Consulta productos_erp y retorna {codigo: item_id} para los códigos conocidos.

    Códigos sin match son simplemente ignorados (el caller los cuenta como skipped).
    """
    if not codigos:
        return {}

    result = db.execute(
        text("SELECT codigo, item_id FROM productos_erp WHERE codigo = ANY(:codigos)"),
        {"codigos": list(codigos)},
    ).fetchall()

    mapping = {row[0]: row[1] for row in result}

    if len(result) != len(mapping):
        duplicate_count = len(result) - len(mapping)
        logger.warning(
            "⚠️ _resolve_codigo_map: %d duplicate codigo(s) in productos_erp — last-write-wins applied",
            duplicate_count,
        )

    return mapping


# ---------------------------------------------------------------------------
# Upsert payload building
# ---------------------------------------------------------------------------


def _build_upsert_rows(
    rows: list[dict],
    codigo_map: dict[str, int],
    sync_ts: datetime,
) -> tuple[list[dict], int]:
    """Construye la lista de dicts para el upsert masivo.

    Args:
        rows: Filas del scriptAgeing (ya parseadas).
        codigo_map: {codigo: item_id} de productos_erp.
        sync_ts: Timestamp de sincronización (se usa para fecha_sync y updated_at).

    Returns:
        (upsert_rows, skipped_count)

    TRAP: updated_at se setea EXPLÍCITAMENTE en cada fila porque on_conflict_do_update
    no dispara el onupdate del ORM. Sin esto, updated_at queda congelado en insert time.
    """
    upsert_rows: list[dict] = []
    skipped = 0

    for row in rows:
        codigo: str = row.get("Código", "")
        item_id = codigo_map.get(codigo)

        if item_id is None:
            skipped += 1
            logger.debug("⚠️ Código sin match en productos_erp: %r — se omite", codigo)
            continue

        ageing_dias_raw = row.get("Ageing")
        ageing_dias: int | None = int(ageing_dias_raw) if ageing_dias_raw is not None else None

        upsert_rows.append(
            {
                "item_id": item_id,
                "ageing_dias": ageing_dias,
                "ageing_payload": dict(row),  # copia defensiva
                "fecha_sync": sync_ts,
                # Explícito: on_conflict_do_update no dispara ORM onupdate
                "updated_at": sync_ts,
            }
        )

    return upsert_rows, skipped


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


def _upsert_batch(db: Session, batch: list[dict]) -> None:
    """Ejecuta un INSERT … ON CONFLICT DO UPDATE para un lote de filas."""
    stmt = pg_insert(ProductoAgeing).values(batch)
    stmt = stmt.on_conflict_do_update(
        index_elements=["item_id"],
        set_={
            "ageing_dias": stmt.excluded.ageing_dias,
            "ageing_payload": stmt.excluded.ageing_payload,
            "fecha_sync": stmt.excluded.fecha_sync,
            # updated_at MUST be set explicitly — ORM onupdate does not fire here
            "updated_at": stmt.excluded.updated_at,
        },
    )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------


def sync_ageing(from_date: str, to_date: str) -> tuple[int, int, int]:
    """Sync standalone: abre su propia sesión de DB (no leakea conexiones del pool).

    Args:
        from_date: Fecha inicio en formato "YYYY-MM-DD HH:MM:SS" (requerida por ERP).
        to_date:   Fecha fin en formato "YYYY-MM-DD HH:MM:SS" (requerida por ERP).

    Returns:
        (total_filas_erp, upserted, skipped)
    """
    db: Session | None = None
    try:
        logger.info("🔄 === Iniciando sincronización de productos_ageing ===")
        logger.info("🔄 Ventana ERP: %s → %s", from_date, to_date)

        # 1. Obtener filas del ERP via endpoint gbp-parser (ya parseadas)
        rows = asyncio.run(_fetch_ageing(from_date, to_date))

        total_erp = len(rows)
        logger.info("✅ Recibidas %d filas del ERP", total_erp)

        if not rows:
            logger.info("✅ Nada que sincronizar — respuesta vacía")
            return (0, 0, 0)

        # 2. Abrir sesión propia (patrón: commit b20cec86 — evitar pool leaks)
        db = SessionLocal()

        # 3. Resolver Código → item_id en una sola query
        codigos = {row.get("Código", "") for row in rows if row.get("Código")}
        logger.info("🔄 Resolviendo %d códigos ERP contra productos_erp…", len(codigos))
        codigo_map = _resolve_codigo_map(db, codigos)
        logger.info("✅ %d/%d códigos resueltos", len(codigo_map), len(codigos))

        # 4. Construir filas de upsert
        sync_ts = datetime.now(UTC)
        upsert_rows, skipped = _build_upsert_rows(rows, codigo_map, sync_ts=sync_ts)

        if skipped:
            logger.warning("⚠️ %d filas omitidas (Código sin match en productos_erp)", skipped)

        if not upsert_rows:
            logger.info("✅ Sin filas a upsertear tras el mapeo")
            return (total_erp, 0, skipped)

        # 5. Upsert en lotes
        logger.info("🔄 Upserteando %d filas en lotes de %d…", len(upsert_rows), UPSERT_BATCH_SIZE)
        for i in range(0, len(upsert_rows), UPSERT_BATCH_SIZE):
            batch = upsert_rows[i : i + UPSERT_BATCH_SIZE]
            _upsert_batch(db, batch)
            logger.info(
                "🔄  Lote %d/%d completado", i // UPSERT_BATCH_SIZE + 1, -(-len(upsert_rows) // UPSERT_BATCH_SIZE)
            )

        db.commit()
        upserted = len(upsert_rows)
        logger.info("✅ === Sincronización completada ===")
        logger.info("  Total ERP:   %d", total_erp)
        logger.info("  Upsertados:  %d", upserted)
        logger.info("  Omitidos:    %d", skipped)

        return (total_erp, upserted, skipped)

    except Exception:
        logger.exception("❌ Error durante la sincronización de ageing")
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sincronizar productos_ageing desde ERP (scriptAgeing)")
    parser.add_argument(
        "--from-date",
        type=str,
        default="2000-01-01 00:00:00",
        help='Fecha inicio para scriptAgeing (formato "YYYY-MM-DD HH:MM:SS"). Default: 2000-01-01 00:00:00',
    )
    parser.add_argument(
        "--to-date",
        type=str,
        default=None,
        help='Fecha fin para scriptAgeing (formato "YYYY-MM-DD HH:MM:SS"). Default: hoy 23:59:59',
    )
    args = parser.parse_args()

    to_date: str = args.to_date or datetime.now(UTC).strftime("%Y-%m-%d 23:59:59")
    sync_ageing(from_date=args.from_date, to_date=to_date)
