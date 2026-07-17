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
from typing import Any, Dict, List, Set

from sqlalchemy import text

from app.core.database import get_mlwebhook_engine

logger = logging.getLogger(__name__)

_KNOWN_ITEM_STATUSES = {"candidate", "started", "pending", "finished"}

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

# Same columns as above but ip.-qualified (bare promotion_id/type/status would
# be ambiguous under the ml_promotions LEFT JOIN) plus the catalog name
# (row[12]) and catalog start/finish dates (row[13]/row[14]) as trailing
# columns. Used by fetch_item_promotions to recover the authoritative promo
# name and dates that payload lacks for some types (SELLER_CAMPAIGN/DEAL).
# NOTE: any positional row[N] access against this constant must be re-audited
# whenever a column is added/reordered here.
_ITEM_PROMOTIONS_SELECT_COLUMNS_JOINED = """
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
    p.name AS catalog_name,
    p.start_date AS catalog_start_date,
    p.finish_date AS catalog_finish_date
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
        "start_date": payload_dict.get("start_date") if isinstance(payload_dict, dict) else None,
        "finish_date": payload_dict.get("finish_date") if isinstance(payload_dict, dict) else None,
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
    status_clause = "AND ip.status IN ('candidate', 'started', 'pending')" if active_only else ""
    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT {_ITEM_PROMOTIONS_SELECT_COLUMNS_JOINED}
                FROM ml_item_promotions AS ip
                LEFT JOIN ml_promotions AS p ON p.promotion_id = ip.promotion_id
                WHERE ip.mla = :mla
                {status_clause}
                ORDER BY ip.updated_at DESC, ip.promotion_id
            """),
            {"mla": mla_id},
        ).fetchall()

    result = []
    for row in rows:
        item = _item_promotion_row_to_dict(row)
        # The authoritative human name is ml_promotions.name (catalog). For
        # SELLER_CAMPAIGN/DEAL, payload.name is empty and ONLY the catalog has
        # it; SMART fills payload.name. Catalog wins, then payload, then None
        # (FE falls back to promotion_type). Empty '' is treated as absent.
        catalog_name = row[12]
        item["name"] = catalog_name or item["name"]
        # ADD-2: catalog start_date/finish_date (timestamptz -> datetime) win
        # over payload's when present; payload wins when catalog is empty
        # (same catalog-then-payload-then-None precedence as name above).
        # MUST serialize to ISO string — the ItemPromotion schema field is
        # Optional[str] and the FE parses it with `new Date(...)`.
        catalog_start = row[13]
        catalog_finish = row[14]
        item["start_date"] = catalog_start.isoformat() if catalog_start else item["start_date"]
        item["finish_date"] = catalog_finish.isoformat() if catalog_finish else item["finish_date"]
        result.append(item)
    logger.info("ml_item_promotions: %d promotions read for %s", len(result), mla_id)
    return result


def fetch_promo_summary_by_mla(mla_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Lee un resumen batcheado de promos activas por MLA (una sola query).

    Usado por el enrichment del endpoint lite de productos (badges/indicadores
    en la UI). Agrega en SQL (GROUP BY mla) para evitar N+1: cuenta promos
    activas (candidate|started), determina si hay al menos una `started`
    ("aplicada" al item) y resuelve el nombre de la promo ACTIVA (la
    `started` de menor precio; ML solo aplica una y deja el resto
    programadas). El nombre sale del catálogo ml_promotions.name (autoritativo;
    SELLER_CAMPAIGN/DEAL tienen payload.name vacío), con fallback a
    payload->>'name' (SMART sí lo trae) y luego a promotion_type cuando ninguno
    tiene nombre (ej. PRICE_DISCOUNT). NULLS FIRST porque un precio null se
    considera activo (no descartable).

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
                    (array_agg(COALESCE(NULLIF(p.name, ''), NULLIF(ip.payload->>'name', ''), ip.promotion_type) ORDER BY ip.price ASC NULLS FIRST)
                        FILTER (WHERE ip.status = 'started'))[1] AS applied_name
                FROM ml_item_promotions ip
                LEFT JOIN ml_promotions p ON p.promotion_id = ip.promotion_id
                WHERE ip.mla = ANY(:mlas)
                  AND ip.status IN ('candidate', 'started', 'pending')
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


def fetch_mlas_with_active_promo_type(promo_types: List[str], applied_only: bool = False) -> Set[str]:
    """Lee el set de MLAs con al menos una promo activa de los tipos dados.

    Usado por el filtro "por tipo de promo" del LISTADO de Productos (feature
    productos-list-promo-filter): una sola query batcheada (nunca N+1) que
    resuelve, para los `promo_types` seleccionados, qué MLAs tienen una promo
    en estado activo según el modo elegido.

    Args:
        promo_types: lista de promotion_type a buscar (ANY). [] no ejecuta
            ninguna query (mirrors fetch_promo_summary_by_mla's guard).
        applied_only: si True (modo "aplicada"), sólo cuenta status='started'.
            Si False (modo "disponible", default), cuenta status IN
            ('candidate','started') — mirrors fetch_item_promotions'
            active_only semantics. La tabla es upsert-only sin limpieza de
            stale, así que este scope de status mantiene el set acotado a
            promos genuinamente activas (nunca 'finished').

    Returns:
        Set de mla (str). Vacío si no hay filas.

    Raises:
        RuntimeError: si ML_WEBHOOK_DB_URL no está configurada. El caller
            (endpoint) es responsable de mapear esto a HTTP 503.
    """
    if not promo_types:
        return set()

    status_clause = "AND status = 'started'" if applied_only else "AND status IN ('candidate', 'started')"

    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT DISTINCT mla
                FROM ml_item_promotions
                WHERE promotion_type = ANY(:types)
                {status_clause}
            """),
            {"types": promo_types},
        ).fetchall()

    result = {row[0] for row in rows}
    logger.info("ml_item_promotions: %d mlas with active promo type(s) %s", len(result), promo_types)
    return result


def derivar_application_status(promociones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derives `application_status` for a single MLA's promotions.

    ML's public API/tables mark every enrolled promo as `started` — a single
    item can be legitimately enrolled in MULTIPLE promos, but ML only
    actually APPLIES the one with the lowest price and leaves the rest
    PROGRAMMED (scheduled, not currently applied). This distinction is not
    stored anywhere and must be derived here:

      - `status != 'started'` (i.e. `candidate`): `application_status = None`
        (not applied, nothing to derive — "available to apply").
      - `status == 'started'`: compute the minimum non-null `price` among
        all started promos in `promociones`. A started promo is `'active'`
        when its `price is None` (missing price -> shown as active, never
        silently discarded) OR its `price == min_price`. Every other started
        promo is `'programmed'`.
      - Ties on the minimum price -> ALL tied promos are marked `'active'`
        (a PM decision, not something this function should pick one for).
      - All-null prices among the started promos -> all `'active'` (no
        minimum to compare against).
      - Comparison spans ALL started promos regardless of `promotion_type`
        (SMART/DEAL/SELLER_CAMPAIGN are compared on price, not per-type).

    Args:
        promociones: A single MLA's promo rows (mutated in place and also
            returned).

    Returns:
        `promociones`, with `application_status` set on each entry.
    """
    started = [promo for promo in promociones if promo.get("status") == "started"]
    if not started:
        for promo in promociones:
            if promo.get("status") != "started":
                promo["application_status"] = "pending" if promo.get("status") == "pending" else None
        return promociones

    prices = [promo.get("price") for promo in started if promo.get("price") is not None]
    min_price = min(prices) if prices else None

    for promo in promociones:
        if promo.get("status") != "started":
            promo["application_status"] = "pending" if promo.get("status") == "pending" else None
            continue
        price = promo.get("price")
        if price is None or (min_price is not None and price == min_price):
            promo["application_status"] = "active"
        else:
            promo["application_status"] = "programmed"

    return promociones
