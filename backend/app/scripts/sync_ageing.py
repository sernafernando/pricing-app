"""
Sincroniza productos_ageing desde el ERP via scriptAgeing.

scriptAgeing retorna el catálogo completo (~14 768 filas, ~5 MB) sin importar
la ventana de fechas — fromDate/toDate son requeridos por el endpoint pero no
filtran. El llamado tarda ~360s, por lo que se usa un httpx.AsyncClient propio
con timeout=600s (el timeout estándar de gbp_parser.py es 300s y siempre falla).

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
import json
import logging
import re
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

from fastapi import HTTPException

from app.api.endpoints.gbp_parser import (
    OPERATION_CONFIG,
    P_COMPANY,
    P_PASSWORD,
    P_USERNAME,
    P_WEBWS,
    SOAP_URL,
    authenticate_user,
    parse_soap_response,
)
from app.core.database import SessionLocal
from app.models.producto_ageing import ProductoAgeing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Timeout en segundos — scriptAgeing tarda ~360s; 600s da margen holgado
SOAP_TIMEOUT_SECONDS = 600.0

# Batch size para el upsert bulk (reduce memoria y presión en el pool)
UPSERT_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# ERP call
# ---------------------------------------------------------------------------


async def _call_ageing_soap(from_date: str, to_date: str) -> str:
    """Llama a wsGBPScriptExecute4Dataset para scriptAgeing con timeout largo.

    No reutiliza call_soap_service() de gbp_parser porque ese usa timeout=300s,
    que siempre falla para scriptAgeing (~360s). En su lugar construimos el
    envelope directamente con nuestro propio AsyncClient.
    """
    try:
        token = await authenticate_user()
    except HTTPException as exc:
        raise RuntimeError(f"ERP auth failed: {exc.detail}") from exc

    op = OPERATION_CONFIG["wsGBPScriptExecute4Dataset"]
    soap_action: str = op["soapAction"]

    json_params = json.dumps({"fromDate": from_date, "toDate": to_date})
    soap_body = op["template"].format(
        strScriptLabel="scriptAgeing",
        strJSonParameters=json_params.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
    )

    xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Header>
        <wsBasicQueryHeader xmlns="http://microsoft.com/webservices/">
          <pUsername>{P_USERNAME}</pUsername>
          <pPassword>{P_PASSWORD}</pPassword>
          <pCompany>{P_COMPANY}</pCompany>
          <pWebWervice>{P_WEBWS}</pWebWervice>
          <pAuthenticatedToken>{token}</pAuthenticatedToken>
        </wsBasicQueryHeader>
      </soap:Header>
      <soap:Body>
        {soap_body}
      </soap:Body>
    </soap:Envelope>"""

    logger.info("🔄 Llamando a scriptAgeing (timeout=%ss)…", SOAP_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            SOAP_URL,
            content=xml_payload,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": soap_action,
            },
        )

    xml_text: str = response.text

    # Token-expiry retry: re-authenticate once and re-POST with the same client
    if "TOKEN Expired" in xml_text:
        logger.warning("⚠️ Token expirado tras el POST — renovando y reintentando…")
        try:
            token = await authenticate_user()
        except HTTPException as exc:
            raise RuntimeError(f"ERP auth failed during token refresh: {exc.detail}") from exc

        # Rebuild envelope with fresh token
        xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Header>
        <wsBasicQueryHeader xmlns="http://microsoft.com/webservices/">
          <pUsername>{P_USERNAME}</pUsername>
          <pPassword>{P_PASSWORD}</pPassword>
          <pCompany>{P_COMPANY}</pCompany>
          <pWebWervice>{P_WEBWS}</pWebWervice>
          <pAuthenticatedToken>{token}</pAuthenticatedToken>
        </wsBasicQueryHeader>
      </soap:Header>
      <soap:Body>
        {soap_body}
      </soap:Body>
    </soap:Envelope>"""

        async with httpx.AsyncClient(timeout=SOAP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                SOAP_URL,
                content=xml_payload,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": soap_action,
                },
            )
        xml_text = response.text

    return xml_text


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

        # 1. Llamar al ERP (SOAP con timeout largo)
        xml_text = asyncio.run(_call_ageing_soap(from_date, to_date))
        raw = parse_soap_response(xml_text)
        rows = parse_ageing_response(raw)

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
