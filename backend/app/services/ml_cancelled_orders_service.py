"""
Lectura cross-DB de ml_cancelled_orders (base mlwebhook, READ-ONLY).

ml-webhook hace UPSERT idempotente (por order_id) en ml_cancelled_orders cada
vez que llega un webhook de una orden ML con status == 'cancelled'. pricing-app
solo LEE esa tabla para reconciliar métricas; la escritura la maneja ml-webhook.

Se accede con el mismo engine que ya se usa para ml_previews
(get_mlwebhook_engine), no con la sesión de pricing_dev.

Schema relevante de ml_cancelled_orders (base mlwebhook):
    order_id       BIGINT PRIMARY KEY   -- id de la orden ML
    pack_id        BIGINT
    status         TEXT                 -- siempre 'cancelled'
    status_detail  TEXT                 -- motivo (puede ser null)
    cancelled_by   TEXT                 -- buyer / seller / ML (puede ser null)
    date_created   TIMESTAMPTZ
    date_closed    TIMESTAMPTZ          -- cierre/cancelación de la orden
    total_amount   NUMERIC(18,2)
    currency_id    TEXT
    buyer_id       BIGINT
    buyer_nickname TEXT
    seller_id      BIGINT
    items          JSONB                -- [{item_id, seller_sku, title, quantity, unit_price}]
    payload        JSONB                -- snapshot completo (no se lee acá por peso)
    cancelled_at   TIMESTAMPTZ          -- cuándo lo registró ml-webhook
    updated_at     TIMESTAMPTZ
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.database import get_mlwebhook_engine

logger = logging.getLogger(__name__)

# Columnas que se leen siempre (se omite payload por peso; pedirlo aparte si hace falta)
_SELECT_COLUMNS = """
    order_id,
    pack_id,
    status,
    status_detail,
    cancelled_by,
    date_created,
    date_closed,
    total_amount,
    currency_id,
    buyer_id,
    buyer_nickname,
    seller_id,
    items,
    cancelled_at,
    updated_at
"""


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Mapea una fila de ml_cancelled_orders a dict (orden = _SELECT_COLUMNS)."""
    return {
        "order_id": row[0],
        "pack_id": row[1],
        "status": row[2],
        "status_detail": row[3],
        "cancelled_by": row[4],
        "date_created": row[5],
        "date_closed": row[6],
        "total_amount": row[7],
        "currency_id": row[8],
        "buyer_id": row[9],
        "buyer_nickname": row[10],
        "seller_id": row[11],
        "items": row[12] or [],
        "cancelled_at": row[13],
        "updated_at": row[14],
    }


def fetch_cancelled_by_order_ids(order_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Lee en batch las órdenes canceladas para un conjunto de order_ids.

    Útil para chequear un lote concreto de ventas (ej. las filas presentes en
    ml_ventas_metricas) contra la tabla de cancelaciones.

    Args:
        order_ids: lista de order_id (BIGINT) de ml_cancelled_orders.

    Returns:
        Dict {order_id: fila_dict} solo para las órdenes que figuran canceladas.
    """
    if not order_ids:
        return {}

    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT {_SELECT_COLUMNS}
                FROM ml_cancelled_orders
                WHERE order_id = ANY(:order_ids)
            """),
            {"order_ids": order_ids},
        ).fetchall()

    result: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        data = _row_to_dict(row)
        result[data["order_id"]] = data

    logger.info(f"🔄 ml_cancelled_orders: {len(result)}/{len(order_ids)} órdenes del lote figuran canceladas")
    return result


def fetch_cancelled_since(
    since: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Lee las órdenes canceladas registradas a partir de un momento dado.

    Pensado para la reconciliación incremental: se filtra por cancelled_at
    (cuándo ml-webhook registró la cancelación), que es monótono creciente y
    cubre cancelaciones de órdenes viejas que el sync incremental nunca revisita.

    Args:
        since: solo filas con cancelled_at > since. None = trae todas (barrido full).
        limit: tope opcional de filas (None = sin tope).

    Returns:
        Lista de filas (dict) ordenadas por cancelled_at ascendente.
    """
    engine = get_mlwebhook_engine()

    where_clause = "WHERE cancelled_at > :since" if since is not None else ""
    limit_clause = "LIMIT :limit" if limit is not None else ""

    params: Dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    if limit is not None:
        params["limit"] = limit

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT {_SELECT_COLUMNS}
                FROM ml_cancelled_orders
                {where_clause}
                ORDER BY cancelled_at ASC
                {limit_clause}
            """),
            params,
        ).fetchall()

    result = [_row_to_dict(row) for row in rows]
    logger.info(f"🔄 ml_cancelled_orders: {len(result)} cancelaciones leídas (since={since})")
    return result
