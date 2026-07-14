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

import logging
from typing import Any, Dict, List

from sqlalchemy import text

from app.core.database import get_mlwebhook_engine

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
    ip.mla,
    ip.promotion_id,
    ip.promotion_type,
    ip.sub_type,
    ip.status,
    ip.original_price,
    ip.price,
    ip.min_discounted_price,
    ip.max_discounted_price,
    ip.suggested_discounted_price,
    ip.payload,
    ip.updated_at,
    p.name
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
    """Maps a row from ml_item_promotions to dict (order = _ITEM_PROMOTIONS_SELECT_COLUMNS)."""
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
        "payload": row[10] or {},
        "updated_at": row[11],
        "name": row[12],
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
                LEFT JOIN ml_promotions AS p ON ip.promotion_id = p.promotion_id
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
    reciente (ml_promotions.name, con fallback a promotion_type cuando el
    join no matchea, ej. PRICE_DISCOUNT).

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
                    (array_agg(COALESCE(p.name, ip.promotion_type) ORDER BY ip.updated_at DESC)
                        FILTER (WHERE ip.status = 'started'))[1] AS applied_name
                FROM ml_item_promotions ip
                LEFT JOIN ml_promotions p ON p.promotion_id = ip.promotion_id
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
                LEFT JOIN ml_promotions AS p ON ip.promotion_id = p.promotion_id
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
