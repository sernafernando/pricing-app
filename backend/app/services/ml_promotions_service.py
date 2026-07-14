"""
Cross-DB read service for ML Seller Promotions (base mlwebhook, READ-ONLY).

ml-webhook owns the write path for `ml_promotions` and `ml_item_promotions`
(populated from ML Central de Promociones). pricing-app only READS these
tables here; enrollment/removal writes go through the ml-webhook proxy
(see `MLWebhookClient`), not directly against these tables.

Accessed with the same engine used for ml_previews / ml_cancelled_orders
(get_mlwebhook_engine), never with the pricing_dev session.

Schema (base mlwebhook), verified against a live information_schema
introspection of the real mlwebhook DB (column names, order and PKs match):

    ml_promotions
        promotion_id    TEXT/VARCHAR PRIMARY KEY
        promotion_type  TEXT   -- SELLER_CAMPAIGN, DEAL, PRICE_DISCOUNT, SMART, DOD, LIGHTNING
        sub_type        TEXT
        status          TEXT
        name            TEXT
        start_date      TIMESTAMPTZ
        finish_date     TIMESTAMPTZ
        deadline_date   TIMESTAMPTZ
        payload         JSONB   -- snapshot completo (no se lee acá por peso)
        updated_at      TIMESTAMPTZ

    ml_item_promotions
        mla                         TEXT
        promotion_id                TEXT   -- PK(mla, promotion_id); for
                                            -- PRICE_DISCOUNT, ML sends no id
                                            -- and promotion_id == promotion_type
        promotion_type               TEXT
        sub_type                     TEXT
        status                       TEXT   -- candidate | started | finished
        original_price                NUMERIC
        price                         NUMERIC
        min_discounted_price          NUMERIC
        max_discounted_price          NUMERIC
        suggested_discounted_price    NUMERIC
        payload                       JSONB
        updated_at                    TIMESTAMPTZ

`ml_item_promotions` is the source of truth for an item's final promotion
state (candidate|started|finished), not the live ML API read-back.
"""

import asyncio
import inspect
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.database import get_mlwebhook_engine
from app.services.ml_webhook_client import ml_webhook_client

logger = logging.getLogger(__name__)

_KNOWN_ITEM_STATUSES = {"candidate", "started", "finished"}

_PROMOTIONS_SELECT_COLUMNS = """
    promotion_id,
    promotion_type,
    sub_type,
    status,
    name,
    start_date,
    finish_date,
    deadline_date,
    payload,
    updated_at
"""

_ITEM_PROMOTIONS_SELECT_COLUMNS = """
    mla,
    promotion_id,
    promotion_type,
    sub_type,
    status,
    original_price,
    price,
    min_discounted_price,
    max_discounted_price,
    suggested_discounted_price,
    payload,
    updated_at
"""


def _validate_item_status(status: Any) -> str:
    """Validate an ml_item_promotions.status against candidate|started|finished.

    ml-webhook already stores status in this domain, so this is a defensive
    pass-through: known values are returned unchanged, and unexpected ones are
    logged (never silently dropped or remapped) and still surfaced as-is so a
    schema drift upstream is observable rather than hidden.
    """
    if status not in _KNOWN_ITEM_STATUSES:
        logger.warning("Unexpected ml_item_promotions.status value: %r", status)
    return status


def _promotion_row_to_dict(row: Any) -> Dict[str, Any]:
    """Maps a row from ml_promotions to dict (order = _PROMOTIONS_SELECT_COLUMNS)."""
    return {
        "promotion_id": row[0],
        "promotion_type": row[1],
        "sub_type": row[2],
        "status": row[3],
        "name": row[4],
        "start_date": row[5],
        "finish_date": row[6],
        "deadline_date": row[7],
        "payload": row[8] or {},
        "updated_at": row[9],
    }


def _item_promotion_row_to_dict(row: Any) -> Dict[str, Any]:
    """Maps a row from ml_item_promotions to dict (order = _ITEM_PROMOTIONS_SELECT_COLUMNS).

    The human-readable `name` is NOT a column on this table; it is read from
    the JSONB `payload` (payload.name), which mirrors the live ML API
    response for the promotion. PRICE_DISCOUNT sends payload.name == "" (ML
    doesn't name price-discount promos), so an empty string is normalized to
    None and the FE falls back to promotion_type.
    """
    payload_dict = row[10] or {}
    return {
        "mla": row[0],
        "promotion_id": row[1],
        "promotion_type": row[2],
        "sub_type": row[3],
        "status": _validate_item_status(row[4]),
        "original_price": row[5],
        "price": row[6],
        "min_discounted_price": row[7],
        "max_discounted_price": row[8],
        "suggested_discounted_price": row[9],
        "payload": payload_dict,
        "updated_at": row[11],
        "name": (payload_dict.get("name") or None) if isinstance(payload_dict, dict) else None,
    }


def fetch_promotions() -> List[Dict[str, Any]]:
    """Lista las promociones del vendedor registradas en ml_promotions.

    Returns:
        Lista de promociones (dict). [] si no hay filas.

    Raises:
        RuntimeError: si ML_WEBHOOK_DB_URL no está configurada. El caller
            (router) es responsable de mapear esto a HTTP 503.
    """
    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT {_PROMOTIONS_SELECT_COLUMNS}
                FROM ml_promotions
                ORDER BY updated_at DESC
            """)
        ).fetchall()

    result = [_promotion_row_to_dict(row) for row in rows]
    logger.info("ml_promotions: %d promotions read", len(result))
    return result


def fetch_item_promotions(mla_id: str, active_only: bool = False) -> List[Dict[str, Any]]:
    """Lee las promociones aplicables a un MLA puntual desde ml_item_promotions.

    ml_item_promotions es la fuente de verdad del estado final del item.

    Args:
        mla_id: ID del item (ej: MLA1234567890).
        active_only: si True, devuelve solo status IN ('candidate','started').
            La tabla es upsert-only sin limpieza de stale, así que una promo
            terminada puede quedar con su último estado hasta que un webhook la
            marque 'finished'. El display (endpoint) usa active_only=True para no
            mostrar promos terminadas; la reconciliación de escrituras usa el
            default (False) porque necesita ver el estado crudo.

    Returns:
        Lista de promociones del item (dict), con status normalizado a
        candidate|started|finished. [] si no hay filas.

    Raises:
        RuntimeError: si ML_WEBHOOK_DB_URL no está configurada.
    """
    status_clause = "AND ip.status IN ('candidate', 'started')" if active_only else ""
    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT {_ITEM_PROMOTIONS_SELECT_COLUMNS}
                FROM ml_item_promotions AS ip
                WHERE ip.mla = :mla
                {status_clause}
                ORDER BY ip.updated_at DESC, ip.promotion_id
            """),
            {"mla": mla_id},
        ).fetchall()

    result = [_item_promotion_row_to_dict(row) for row in rows]
    logger.info("ml_item_promotions: %d promotions read for %s", len(result), mla_id)
    return result


def fetch_promo_summary_by_mla(mla_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Lee un resumen batcheado de promos activas por MLA (una sola query).

    Usado por el enrichment del endpoint lite de productos (badges/indicadores
    en la UI). Agrega en SQL (GROUP BY mla) para evitar N+1: cuenta promos
    activas (candidate|started), determina si hay al menos una `started`
    ("aplicada" al item) y resuelve el nombre de la promo aplicada más
    reciente (payload->>'name', con fallback a promotion_type cuando el
    payload no trae nombre, ej. PRICE_DISCOUNT).

    Args:
        mla_ids: lista de MLAs a resumir. [] no ejecuta ninguna query.

    Returns:
        Dict keyed por mla: {"active_count": int, "has_applied": bool,
        "applied_name": Optional[str]}. MLAs sin promos activas no aparecen
        como key (el caller debe tratar la ausencia como 0/False/None).

    Raises:
        RuntimeError: si ML_WEBHOOK_DB_URL no está configurada.
    """
    if not mla_ids:
        return {}

    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    ip.mla,
                    COUNT(*)                                 AS active_count,
                    bool_or(ip.status = 'started')           AS has_applied,
                    (array_agg(COALESCE(NULLIF(ip.payload->>'name', ''), ip.promotion_type) ORDER BY ip.updated_at DESC)
                        FILTER (WHERE ip.status = 'started'))[1] AS applied_name
                FROM ml_item_promotions ip
                WHERE ip.mla = ANY(:mlas)
                  AND ip.status IN ('candidate', 'started')
                GROUP BY ip.mla
            """),
            {"mlas": mla_ids},
        ).fetchall()

    result: Dict[str, Dict[str, Any]] = {}
    for mla, active_count, has_applied, applied_name in rows:
        result[mla] = {
            "active_count": active_count,
            "has_applied": bool(has_applied),
            "applied_name": applied_name,
        }

    logger.info("ml_item_promotions: promo summary read for %d mlas", len(result))
    return result


def fetch_promotion_items(promotion_id: str, promotion_type: str) -> List[Dict[str, Any]]:
    """Lee los items de una promoción puntual desde ml_item_promotions.

    Nota: para PRICE_DISCOUNT, ML no envía un id propio de promoción; en ese
    caso ml_item_promotions.promotion_id == promotion_type.

    Args:
        promotion_id: ID de la promoción (o el promotion_type para PRICE_DISCOUNT).
        promotion_type: Tipo de promoción (requerido).

    Returns:
        Lista de items (dict) de la promoción. [] si no hay filas.

    Raises:
        RuntimeError: si ML_WEBHOOK_DB_URL no está configurada.
    """
    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT {_ITEM_PROMOTIONS_SELECT_COLUMNS}
                FROM ml_item_promotions AS ip
                WHERE ip.promotion_id = :promotion_id
                  AND ip.promotion_type = :promotion_type
                ORDER BY ip.updated_at DESC, ip.promotion_id
            """),
            {"promotion_id": promotion_id, "promotion_type": promotion_type},
        ).fetchall()

    result = [_item_promotion_row_to_dict(row) for row in rows]
    logger.info(
        "ml_item_promotions: %d items read for promotion %s (%s)",
        len(result),
        promotion_id,
        promotion_type,
    )
    return result


def _resolve(value: Any) -> Any:
    """Bridges `MLWebhookClient`'s async methods into this module's
    synchronous API. Mirrors `ml_promotions_write_service._resolve`: real
    calls return a coroutine (awaited here via `asyncio.run`), and unit-test
    mocks (`patch(..., return_value=...)`) return the plain value directly,
    so both paths work unchanged.
    """
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def reconcile_started_promotions(mla_id: str, promotions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reconciles a stale "more than one `started`" table read against the
    LIVE proxy read.

    `ml_item_promotions` is upsert-only with no stale cleanup: a promo that
    was bumped out of `started` (e.g. superseded, cancelled) can linger as
    `started` in the table. More than one `started` row for the same MLA is
    impossible in reality (ML only ever has one truly applied promo per
    item) — a stale-signal trigger for reconciling against the live read.

    Fast path (0 or 1 `started`): returns `promotions` unchanged, with NO
    extra live call — the common case stays table-only.

    Reconcile path (>1 `started`): reads `ml_webhook_client.get_item_promotions`
    (a BARE LIST of promo entries keyed by `id`, not a `{"promotions": [...]}`
    wrapper — see `MLWebhookClient.get_item_promotions`) and, for each table
    promo whose `promotion_id` matches a live entry's `id`, OVERRIDES the
    table's `status` with the live one (live is the source of truth for the
    applied state). A table promo with no matching live entry is left
    unchanged — the live read may simply not include exotic types, and a
    graceful "still showing the stale table value" is safer than guessing.

    Graceful degradation: if the live read raises or returns `None`/falsy,
    logs a warning and returns `promotions` UNCHANGED (never 500s) — a
    multi-started display is an acceptable fallback vs. a broken panel.

    Args:
        mla_id: The item ID (e.g. MLA2361127120).
        promotions: Table rows from `fetch_item_promotions` (mutated
            in-place and also returned).

    Returns:
        `promotions`, with `status` reconciled against live when needed.
    """
    started_count = sum(1 for promo in promotions if promo.get("status") == "started")
    if started_count <= 1:
        return promotions

    logger.warning(
        "ml_item_promotions: %d 'started' promos for %s (stale signal, expected <=1) — reconciling against live",
        started_count,
        mla_id,
    )

    try:
        live = _resolve(ml_webhook_client.get_item_promotions(mla_id))
    except Exception as e:
        logger.warning("Live reconcile read failed for %s: %s; returning table data unchanged", mla_id, e)
        return promotions

    if not live:
        logger.warning(
            "Live reconcile read returned no data for %s; returning table data unchanged",
            mla_id,
        )
        return promotions

    live_status_by_id: Dict[str, Optional[str]] = {
        entry.get("id"): entry.get("status") for entry in live if entry.get("id")
    }

    for promo in promotions:
        live_status = live_status_by_id.get(promo.get("promotion_id"))
        if live_status is not None:
            promo["status"] = live_status

    return promotions
