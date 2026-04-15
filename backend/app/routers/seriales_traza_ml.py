"""
Seriales — Traza por venta MercadoLibre.

Endpoint: GET /traza/ml/{ml_id}
"""

import logging
from collections.abc import Iterable
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, get_mlwebhook_engine
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.routers.seriales_claims import _fetch_claims_by_order_ids
from app.routers.seriales_shared import (
    ArticuloInfo,
    MovimientoSerial,
    PedidoSerial,
    TrazaMLResponse,
    TrazaMLSerialItem,
    _build_movimientos,
    _build_rma,
    _build_rma_by_invoice,
    _GBP_TIMEOUT,
    QUERY_FACTURA_ITEMS_BY_SOHID,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# QUERIES (only used by this module)
# =============================================================================

QUERY_PEDIDOS_BY_MLID = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.comp_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        ssos.ssos_name AS estado_nombre
    FROM tb_sale_order_header soh
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE soh.soh_mlid = :ml_id
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

QUERY_PEDIDOS_BY_MLGUIA = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.comp_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        soh.soh_mlguia AS shipping_id_real,
        ssos.ssos_name AS estado_nombre
    FROM tb_sale_order_header soh
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE soh.soh_mlguia = :shipping_id
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

QUERY_PEDIDOS_BY_SHIPPINGID = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.comp_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        ship.mlshippingid AS shipping_id_real,
        ssos.ssos_name AS estado_nombre
    FROM tb_mercadolibre_orders_shipping ship
    INNER JOIN tb_sale_order_header soh
        ON ship.mlo_id = soh.mlo_id
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE ship.mlshippingid = :shipping_id
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

QUERY_PEDIDOS_BY_PACKID = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.comp_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        ssos.ssos_name AS estado_nombre
    FROM tb_mercadolibre_orders_header mlo
    INNER JOIN tb_sale_order_header soh
        ON mlo.mlo_id = soh.mlo_id
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE mlo.ml_pack_id = :pack_id
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

# Fallback directo a mlo cuando soh fue archivado.
# No pasa por soh ni sohh — trae datos directamente de mercadolibre_orders_header.
# Usa datos del buyer de ML (mluser_*) como fallback cuando cust_id es NULL/0.
QUERY_PEDIDOS_BY_MLO_DIRECT = text("""
    SELECT DISTINCT
        0 AS soh_id,
        COALESCE(mlo.mlbra_id, 45) AS bra_id,
        mlo.comp_id,
        mlo.mlo_cd AS soh_cd,
        COALESCE(NULLIF(mlo.cust_id, 0), 0) AS cust_id,
        COALESCE(cust.cust_name,
                 TRIM(COALESCE(mlo.mluser_first_name, '') || ' ' || COALESCE(mlo.mluser_last_name, ''))
        ) AS cliente_nombre,
        COALESCE(cust.cust_taxnumber,
                 mlo.identificationnumber::text
        ) AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1,
                 mlo.mluser_phone, mlo.mluser_receiver_phone
        ) AS cliente_telefono,
        COALESCE(cust.cust_email, mlo.mlo_email) AS cliente_email,
        mlo.mlorder_id AS soh_mlid,
        mlo.mlshippingid::bigint AS mlshippingid,
        mlo.mlo_status AS estado_nombre
    FROM tb_mercadolibre_orders_header mlo
    LEFT JOIN tb_customer cust
        ON mlo.comp_id = cust.comp_id
        AND mlo.cust_id = cust.cust_id
        AND mlo.cust_id IS NOT NULL
        AND mlo.cust_id > 0
    WHERE mlo.mlorder_id = :ml_id
    ORDER BY mlo.mlo_cd ASC NULLS LAST
""")

# Same but searching by pack_id directly in mlo
QUERY_PEDIDOS_BY_MLO_PACKID_DIRECT = text("""
    SELECT DISTINCT
        0 AS soh_id,
        COALESCE(mlo.mlbra_id, 45) AS bra_id,
        mlo.comp_id,
        mlo.mlo_cd AS soh_cd,
        COALESCE(NULLIF(mlo.cust_id, 0), 0) AS cust_id,
        COALESCE(cust.cust_name,
                 TRIM(COALESCE(mlo.mluser_first_name, '') || ' ' || COALESCE(mlo.mluser_last_name, ''))
        ) AS cliente_nombre,
        COALESCE(cust.cust_taxnumber,
                 mlo.identificationnumber::text
        ) AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1,
                 mlo.mluser_phone, mlo.mluser_receiver_phone
        ) AS cliente_telefono,
        COALESCE(cust.cust_email, mlo.mlo_email) AS cliente_email,
        mlo.mlorder_id AS soh_mlid,
        mlo.mlshippingid::bigint AS mlshippingid,
        mlo.mlo_status AS estado_nombre
    FROM tb_mercadolibre_orders_header mlo
    LEFT JOIN tb_customer cust
        ON mlo.comp_id = cust.comp_id
        AND mlo.cust_id = cust.cust_id
        AND mlo.cust_id IS NOT NULL
        AND mlo.cust_id > 0
    WHERE mlo.ml_pack_id = :pack_id
    ORDER BY mlo.mlo_cd ASC NULLS LAST
""")

# Same but searching by shipping_id directly in mlo
QUERY_PEDIDOS_BY_MLO_SHIPPINGID_DIRECT = text("""
    SELECT DISTINCT
        0 AS soh_id,
        COALESCE(mlo.mlbra_id, 45) AS bra_id,
        mlo.comp_id,
        mlo.mlo_cd AS soh_cd,
        COALESCE(NULLIF(mlo.cust_id, 0), 0) AS cust_id,
        COALESCE(cust.cust_name,
                 TRIM(COALESCE(mlo.mluser_first_name, '') || ' ' || COALESCE(mlo.mluser_last_name, ''))
        ) AS cliente_nombre,
        COALESCE(cust.cust_taxnumber,
                 mlo.identificationnumber::text
        ) AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1,
                 mlo.mluser_phone, mlo.mluser_receiver_phone
        ) AS cliente_telefono,
        COALESCE(cust.cust_email, mlo.mlo_email) AS cliente_email,
        mlo.mlorder_id AS soh_mlid,
        mlo.mlshippingid::bigint AS mlshippingid,
        mlo.mlo_status AS estado_nombre
    FROM tb_mercadolibre_orders_header mlo
    LEFT JOIN tb_customer cust
        ON mlo.comp_id = cust.comp_id
        AND mlo.cust_id = cust.cust_id
        AND mlo.cust_id IS NOT NULL
        AND mlo.cust_id > 0
    WHERE mlo.mlshippingid = :shipping_id
    ORDER BY mlo.mlo_cd ASC NULLS LAST
""")

QUERY_PEDIDOS_BY_SOHID = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.comp_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        soh.soh_mlguia AS shipping_id_real,
        ssos.ssos_name AS estado_nombre
    FROM tb_sale_order_header soh
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE soh.soh_id = :soh_id
      AND (:bra_id IS NULL OR soh.bra_id = :bra_id)
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

QUERY_PEDIDOS_BY_MLOID = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.comp_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        ssos.ssos_name AS estado_nombre
    FROM tb_sale_order_header soh
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE soh.mlo_id = :mlo_id
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

QUERY_MLO_CANDIDATES_BY_INPUT = text("""
    SELECT DISTINCT
        mlo.mlo_id,
        mlo.ml_pack_id,
        mlo.mlshippingid,
        mlo.mlorder_id,
        mlo.ml_id
    FROM tb_mercadolibre_orders_header mlo
    WHERE mlo.ml_pack_id = :value
       OR mlo.mlorder_id = :value
       OR mlo.ml_id = :value

    UNION

    SELECT DISTINCT
        ship.mlo_id,
        mlo.ml_pack_id,
        COALESCE(ship.mlshippingid, mlo.mlshippingid) AS mlshippingid,
        mlo.mlorder_id,
        mlo.ml_id
    FROM tb_mercadolibre_orders_shipping ship
    LEFT JOIN tb_mercadolibre_orders_header mlo
        ON mlo.mlo_id = ship.mlo_id
    WHERE ship.mlshippingid = :value
""")

QUERY_PEDIDOS_HISTORY_BY_MLOID = text("""
    WITH sohh_latest AS (
        SELECT
            sohh.comp_id,
            sohh.bra_id,
            sohh.soh_id,
            sohh.soh_cd,
            sohh.cust_id,
            sohh.soh_mlid,
            sohh.soh_mlguia,
            sohh.mlo_id,
            sohh.ssos_id,
            sohh.sohh_id,
            ROW_NUMBER() OVER (
                PARTITION BY sohh.comp_id, sohh.bra_id, sohh.soh_id
                ORDER BY sohh.sohh_id DESC
            ) AS rn
        FROM tb_sale_order_header_history sohh
        WHERE sohh.mlo_id = :mlo_id
    )
    SELECT DISTINCT
        s.soh_id,
        s.bra_id,
        s.comp_id,
        s.soh_cd,
        s.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        s.soh_mlid,
        COALESCE(ship.mlshippingid, mlo.mlshippingid, s.soh_mlguia) AS mlshippingid,
        s.soh_mlguia AS shipping_id_real,
        mlo.ml_pack_id,
        ssos.ssos_name AS estado_nombre
    FROM sohh_latest s
    LEFT JOIN tb_mercadolibre_orders_header mlo
        ON mlo.mlo_id = s.mlo_id
    LEFT JOIN tb_mercadolibre_orders_shipping ship
        ON ship.mlo_id = s.mlo_id
    LEFT JOIN tb_customer cust
        ON s.comp_id = cust.comp_id
        AND s.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON s.ssos_id = ssos.ssos_id
    WHERE s.rn = 1
    ORDER BY s.soh_cd ASC NULLS LAST
""")

QUERY_SERIALES_BY_PEDIDO = text("""
    SELECT DISTINCT
        s.is_serial
    FROM tb_sale_order_serials sos
    INNER JOIN tb_item_serials s
        ON sos.is_id = s.is_id
        AND sos.comp_id = s.comp_id
    WHERE sos.soh_id = :soh_id
        AND sos.comp_id = :comp_id
        AND sos.bra_id = :bra_id
        AND s.is_serial IS NOT NULL
        AND s.is_serial != ''
    ORDER BY s.is_serial
""")


# =============================================================================
# HELPERS (only used by this module)
# =============================================================================


def _as_rows(data: object) -> list[dict]:
    """Normaliza payloads del gbp-parser a una lista de dicts."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    if isinstance(data, dict):
        candidates: list[object] = []
        for key in ("data", "rows", "result", "results"):
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(value)
        if candidates:
            return [row for row in candidates if isinstance(row, dict)]

    return []


def _pick_str(source: dict, keys: Iterable[str]) -> Optional[str]:
    """Toma el primer valor string no vacío de un set de keys."""
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def _pick_int(source: dict, keys: Iterable[str]) -> Optional[int]:
    """Toma el primer valor int válido de un set de keys."""
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _fetch_pedidos_rows_from_gbp_fallback(db: Session, ml_id: str) -> list[dict]:
    """
    Fallback final para búsqueda por ML ID.

    Consulta gbp-parser directo y, con IDs devueltos, reintenta contra DB local
    para mantener el mismo shape de respuesta de Traza.
    """
    gbp_url = settings.GBP_PARSER_URL
    if not gbp_url:
        return []

    try:
        with httpx.Client(timeout=_GBP_TIMEOUT) as client:
            response = client.get(gbp_url, params={"strScriptLabel": "mlidToSheets", "mlID": ml_id})
            response.raise_for_status()
            gbp_rows = _as_rows(response.json())
    except Exception:
        logger.warning("[traza_ml] fallback GBP mlidToSheets failed for ml_id=%s", ml_id, exc_info=True)
        return []

    pedidos_rows: list[dict] = []
    seen_keys: set[tuple[int, int]] = set()

    def append_rows(rows: list[dict]) -> None:
        for row in rows:
            key = (int(row["soh_id"]), int(row["bra_id"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pedidos_rows.append(row)

    for gbp_row in gbp_rows:
        soh_id = _pick_int(gbp_row, ("soh_id", "sohID", "sohId"))
        bra_id = _pick_int(gbp_row, ("bra_id", "braID", "braId"))
        mlo_id = _pick_int(gbp_row, ("mlo_id", "mloID", "mloId"))
        shipping_id = _pick_str(gbp_row, ("mlshippingid", "MLShippingID", "shipping_id", "shippingId"))
        ml_id_value = _pick_str(gbp_row, ("soh_mlid", "soh_MLId", "ml_id", "mlID"))

        if soh_id is not None:
            result = db.execute(QUERY_PEDIDOS_BY_SOHID, {"soh_id": soh_id, "bra_id": bra_id})
            append_rows([dict(row._mapping) for row in result])

        if mlo_id is not None:
            result = db.execute(QUERY_PEDIDOS_BY_MLOID, {"mlo_id": mlo_id})
            append_rows([dict(row._mapping) for row in result])

        if shipping_id:
            result = db.execute(QUERY_PEDIDOS_BY_SHIPPINGID, {"shipping_id": shipping_id})
            append_rows([dict(row._mapping) for row in result])

        if ml_id_value:
            result = db.execute(QUERY_PEDIDOS_BY_MLID, {"ml_id": ml_id_value})
            append_rows([dict(row._mapping) for row in result])

    return pedidos_rows


def _fetch_pedidos_rows_from_history_fallback(
    db: Session,
    ml_id: str,
) -> tuple[list[dict], set[str], set[str], set[str]]:
    """Fallback de traza ML usando historial (sohh) cuando no existe SOH actual."""
    rows_candidates = db.execute(QUERY_MLO_CANDIDATES_BY_INPUT, {"value": ml_id}).fetchall()

    mlo_ids: set[int] = set()
    ml_ids: set[str] = set()
    shipping_ids: set[str] = set()
    pack_ids: set[str] = set()

    for row in rows_candidates:
        mapped = dict(row._mapping)

        mlo_id = mapped.get("mlo_id")
        if mlo_id is not None:
            try:
                mlo_ids.add(int(mlo_id))
            except (TypeError, ValueError):
                pass

        for key in ("mlorder_id", "ml_id"):
            value = mapped.get(key)
            if value:
                ml_ids.add(str(value))

        value_shipping = mapped.get("mlshippingid")
        if value_shipping:
            shipping_ids.add(str(value_shipping))

        value_pack = mapped.get("ml_pack_id")
        if value_pack:
            pack_ids.add(str(value_pack))

    pedidos_rows: list[dict] = []
    seen_keys: set[tuple[int, int, int]] = set()
    for mlo_id in mlo_ids:
        result = db.execute(QUERY_PEDIDOS_HISTORY_BY_MLOID, {"mlo_id": mlo_id})
        for row in result:
            mapped = dict(row._mapping)
            key = (
                int(mapped["comp_id"]),
                int(mapped["bra_id"]),
                int(mapped["soh_id"]),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pedidos_rows.append(mapped)

            if mapped.get("soh_mlid"):
                ml_ids.add(str(mapped["soh_mlid"]))
            if mapped.get("shipping_id_real"):
                shipping_ids.add(str(mapped["shipping_id_real"]))
            if mapped.get("mlshippingid"):
                shipping_ids.add(str(mapped["mlshippingid"]))
            if mapped.get("ml_pack_id"):
                pack_ids.add(str(mapped["ml_pack_id"]))

    return pedidos_rows, ml_ids, shipping_ids, pack_ids


def _fetch_webhook_previews(
    order_ids: list[str],
    pack_ids: list[str],
    shipping_ids: list[str],
) -> list[dict]:
    """Trae previews crudos de webhook DB para order/pack/shipping relacionados."""
    previews: list[dict] = []
    seen: set[str] = set()

    def _append_rows(rows: list[tuple]) -> None:
        for row in rows:
            resource, status_value, title, extra_data, last_updated = row
            if resource in seen:
                continue
            seen.add(resource)
            previews.append(
                {
                    "resource": resource,
                    "status": status_value,
                    "title": title,
                    "extra_data": extra_data,
                    "last_updated": str(last_updated) if last_updated else None,
                }
            )

    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            # order_id en extra_data.resource_id + resources que lo incluyan
            for order_id in order_ids:
                rows = conn.execute(
                    text(
                        """
                        SELECT resource, status, title, extra_data, last_updated
                        FROM ml_previews
                        WHERE (
                            (extra_data->>'resource_id')::text = :order_id
                            OR resource LIKE :resource_like
                        )
                        ORDER BY last_updated DESC
                        LIMIT 200
                        """
                    ),
                    {
                        "order_id": order_id,
                        "resource_like": f"%{order_id}%",
                    },
                ).fetchall()
                _append_rows(rows)

            # pack_id
            for pack_id in pack_ids:
                rows = conn.execute(
                    text(
                        """
                        SELECT resource, status, title, extra_data, last_updated
                        FROM ml_previews
                        WHERE resource LIKE :resource_like
                        ORDER BY last_updated DESC
                        LIMIT 200
                        """
                    ),
                    {"resource_like": f"%{pack_id}%"},
                ).fetchall()
                _append_rows(rows)

            # shipping_id
            for shipping_id in shipping_ids:
                rows = conn.execute(
                    text(
                        """
                        SELECT resource, status, title, extra_data, last_updated
                        FROM ml_previews
                        WHERE resource LIKE :resource_like
                        ORDER BY last_updated DESC
                        LIMIT 200
                        """
                    ),
                    {"resource_like": f"%{shipping_id}%"},
                ).fetchall()
                _append_rows(rows)
    except RuntimeError:
        # ML_WEBHOOK_DB_URL no configurada
        return []
    except Exception:
        logger.warning("[traza_ml] failed to fetch webhook previews", exc_info=True)
        return []

    previews.sort(key=lambda x: x.get("last_updated") or "", reverse=True)
    return previews


def _build_non_serial_items_from_invoice(
    db: Session,
    pedidos_rows: list[dict],
    existing_serials: set[str],
) -> list[TrazaMLSerialItem]:
    """Arma items para RMA desde factura cuando no hay seriales en la traza."""
    extra_items: list[TrazaMLSerialItem] = []
    seen_it: set[int] = set()

    for pedido_row in pedidos_rows:
        soh_id = pedido_row.get("soh_id")
        comp_id = pedido_row.get("comp_id")
        if soh_id is None or comp_id is None:
            continue

        result = db.execute(
            QUERY_FACTURA_ITEMS_BY_SOHID,
            {
                "soh_id": soh_id,
                "comp_id": comp_id,
            },
        )

        for row in result:
            mapped = dict(row._mapping)
            it_transaction = mapped.get("it_transaction")
            if it_transaction is None:
                continue
            it_transaction_int = int(it_transaction)
            if it_transaction_int in seen_it:
                continue
            seen_it.add(it_transaction_int)

            item_id = mapped.get("item_id")
            if item_id is None:
                continue
            item_id_int = int(item_id)

            item_code = mapped.get("item_code")
            item_desc = mapped.get("item_desc")
            ct_transaction = mapped.get("ct_transaction")
            ct_kindof = mapped.get("ct_kindof")
            ct_pointofsale = mapped.get("ct_pointofsale")
            ct_docnumber = mapped.get("ct_docnumber")
            ct_date = mapped.get("ct_date")

            nro_documento = None
            if ct_kindof and ct_pointofsale is not None and ct_docnumber is not None:
                nro_documento = f"{ct_kindof} {ct_pointofsale}-{ct_docnumber}"

            articulo = ArticuloInfo(
                item_id=item_id_int,
                codigo=str(item_code) if item_code else str(item_id_int),
                descripcion=str(item_desc) if item_desc else f"Item {item_id_int}",
            )

            movimiento = MovimientoSerial(
                is_id=0,
                ct_transaction=int(ct_transaction) if ct_transaction is not None else None,
                fecha_documento=str(ct_date) if ct_date else None,
                tipo="CLIENTE",
                nro_documento=nro_documento,
            )

            extra_items.append(
                TrazaMLSerialItem(
                    serial="",
                    articulo=articulo,
                    movimientos=[movimiento],
                    rma=[],
                )
            )

    # Deduplicar por item_id cuando no hay serial
    dedup: dict[int, TrazaMLSerialItem] = {}
    for item in extra_items:
        if not item.articulo:
            continue
        dedup[item.articulo.item_id] = item

    return list(dedup.values())


# =============================================================================
# ENDPOINT
# =============================================================================


@router.get("/traza/ml/{ml_id}", response_model=TrazaMLResponse)
def traza_ml(
    ml_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaMLResponse:
    """
    Obtiene la traza completa de una venta de MercadoLibre.
    Si el número empieza con '2000' busca por soh_mlid (nro de venta ML).
    Si no, busca por mlshippingid (nro de envío).
    Luego trae los seriales vinculados a cada pedido, y para cada serial
    trae movimientos y RMAs. También busca RMAs vía factura.
    """
    # 1. Determinar tipo de búsqueda y buscar pedidos
    # Si empieza con 2000 → nro de venta ML (soh_mlid)
    # Si no y es numérico → soh_mlguia → shipping table → soh_mlid (fallbacks)
    # Si no es numérico → buscar como soh_mlid
    detected_ml_ids: set[str] = set()
    detected_shipping_ids: set[str] = set()
    detected_pack_ids: set[str] = set()
    discrepancias_identificadores: list[str] = []

    if ml_id.startswith("2000"):
        # Buscar por order_id (soh_mlid) primero
        busqueda_por = "soh_mlid"
        result_pedidos = db.execute(QUERY_PEDIDOS_BY_MLID, {"ml_id": ml_id})
        pedidos_rows = [dict(row._mapping) for row in result_pedidos]

        # Fallback: puede ser un pack_id (ML muestra pack_id en la UI de ventas)
        if not pedidos_rows:
            busqueda_por = "ml_pack_id"
            result_pedidos = db.execute(QUERY_PEDIDOS_BY_PACKID, {"pack_id": ml_id})
            pedidos_rows = [dict(row._mapping) for row in result_pedidos]
    elif ml_id.isdigit():
        # Intentar soh_mlguia primero (campo directo en el pedido)
        busqueda_por = "soh_mlguia"
        result_pedidos = db.execute(QUERY_PEDIDOS_BY_MLGUIA, {"shipping_id": ml_id})
        pedidos_rows = [dict(row._mapping) for row in result_pedidos]

        # Fallback: buscar en tabla de shipping por mlo_id
        if not pedidos_rows:
            busqueda_por = "mlshippingid"
            result_pedidos = db.execute(QUERY_PEDIDOS_BY_SHIPPINGID, {"shipping_id": ml_id})
            pedidos_rows = [dict(row._mapping) for row in result_pedidos]

        # Fallback: buscar como soh_mlid
        if not pedidos_rows:
            busqueda_por = "soh_mlid"
            result_pedidos = db.execute(QUERY_PEDIDOS_BY_MLID, {"ml_id": ml_id})
            pedidos_rows = [dict(row._mapping) for row in result_pedidos]

        # Fallback final: buscar como pack_id
        if not pedidos_rows:
            busqueda_por = "ml_pack_id"
            result_pedidos = db.execute(QUERY_PEDIDOS_BY_PACKID, {"pack_id": ml_id})
            pedidos_rows = [dict(row._mapping) for row in result_pedidos]
    else:
        busqueda_por = "soh_mlid"
        result_pedidos = db.execute(QUERY_PEDIDOS_BY_MLID, {"ml_id": ml_id})
        pedidos_rows = [dict(row._mapping) for row in result_pedidos]

    # Fallback: buscar directo en mlo (sin pasar por soh que se archiva)
    if not pedidos_rows:
        if ml_id.startswith("2000"):
            result_mlo = db.execute(QUERY_PEDIDOS_BY_MLO_DIRECT, {"ml_id": ml_id})
            pedidos_rows = [dict(r._mapping) for r in result_mlo]
            if not pedidos_rows:
                result_mlo = db.execute(QUERY_PEDIDOS_BY_MLO_PACKID_DIRECT, {"pack_id": ml_id})
                pedidos_rows = [dict(r._mapping) for r in result_mlo]
        elif ml_id.isdigit():
            result_mlo = db.execute(QUERY_PEDIDOS_BY_MLO_SHIPPINGID_DIRECT, {"shipping_id": ml_id})
            pedidos_rows = [dict(r._mapping) for r in result_mlo]
            if not pedidos_rows:
                result_mlo = db.execute(QUERY_PEDIDOS_BY_MLO_DIRECT, {"ml_id": ml_id})
                pedidos_rows = [dict(r._mapping) for r in result_mlo]
        else:
            result_mlo = db.execute(QUERY_PEDIDOS_BY_MLO_DIRECT, {"ml_id": ml_id})
            pedidos_rows = [dict(r._mapping) for r in result_mlo]
        if pedidos_rows:
            busqueda_por = f"{busqueda_por}_fallback_mlo_direct"

    if not pedidos_rows:
        pedidos_rows = _fetch_pedidos_rows_from_gbp_fallback(db, ml_id)
        if pedidos_rows:
            busqueda_por = f"{busqueda_por}_fallback_gbp"

    if not pedidos_rows:
        (
            pedidos_rows,
            detected_ml_ids,
            detected_shipping_ids,
            detected_pack_ids,
        ) = _fetch_pedidos_rows_from_history_fallback(db, ml_id)
        if pedidos_rows:
            busqueda_por = f"{busqueda_por}_fallback_sohh"

    if not pedidos_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró la venta ML ni envío: {ml_id}",
        )

    pedidos = [
        PedidoSerial(
            soh_id=row["soh_id"],
            bra_id=row["bra_id"],
            fecha=str(row["soh_cd"]) if row.get("soh_cd") else None,
            estado=row.get("estado_nombre"),
            cust_id=row.get("cust_id"),
            cliente=row.get("cliente_nombre"),
            cliente_dni=row.get("cliente_dni"),
            cliente_telefono=row.get("cliente_telefono"),
            cliente_email=row.get("cliente_email"),
            ml_id=row.get("soh_mlid"),
            shipping_id=row.get("shipping_id_real") or row.get("mlshippingid"),
        )
        for row in pedidos_rows
    ]

    detected_ml_ids.update({p.ml_id for p in pedidos if p.ml_id})
    detected_shipping_ids.update({str(p.shipping_id) for p in pedidos if p.shipping_id is not None})

    if detected_ml_ids and ml_id not in detected_ml_ids:
        discrepancias_identificadores.append(
            f"ml_id buscado={ml_id} no coincide con ml_id detectados={sorted(detected_ml_ids)}"
        )

    if detected_shipping_ids and ml_id in detected_pack_ids:
        discrepancias_identificadores.append(
            "el valor buscado coincide con pack_id; shipping/order pueden ser distintos"
        )

    # 2. Para cada pedido, buscar seriales vinculados
    seriales_vistos: set[str] = set()
    seriales_list: list[TrazaMLSerialItem] = []
    # Trackear RMAs ya encontrados por serial para deduplicar contra factura
    rma_ids_por_serial: set[tuple[int, int, int]] = set()

    for pedido_row in pedidos_rows:
        result_seriales = db.execute(
            QUERY_SERIALES_BY_PEDIDO,
            {
                "soh_id": pedido_row["soh_id"],
                "comp_id": pedido_row["comp_id"],
                "bra_id": pedido_row["bra_id"],
            },
        )

        for serial_row in result_seriales:
            serial = dict(serial_row._mapping)["is_serial"]
            if serial in seriales_vistos:
                continue
            seriales_vistos.add(serial)

            # Traza completa de este serial
            movimientos, articulo = _build_movimientos(db, serial)
            rma_list, articulo = _build_rma(db, serial, articulo)

            # Registrar RMAs encontrados por serial para deduplicar después
            comp_id: int = pedido_row["comp_id"]
            for rma in rma_list:
                rma_ids_por_serial.add((comp_id, rma.rmad_id, rma.bra_id))

            seriales_list.append(
                TrazaMLSerialItem(
                    serial=serial,
                    articulo=articulo,
                    movimientos=movimientos,
                    rma=rma_list,
                )
            )

    # 2b. Ítems sin serial (fallback por factura) para poder crear RMA igual
    seriales_presentes = {item.serial for item in seriales_list if item.serial}
    seriales_no_seriados = _build_non_serial_items_from_invoice(db, pedidos_rows, seriales_presentes)
    seriales_list.extend(seriales_no_seriados)

    # 3. Buscar RMAs vía factura (para productos no seriados o RMAs sin serial)
    # Cadena: soh_id → commercial_transactions → item_transactions → rma_detail
    soh_ids = [row["soh_id"] for row in pedidos_rows]
    rma_por_factura = _build_rma_by_invoice(db, soh_ids, exclude_rmad_ids=rma_ids_por_serial)

    # 4. Claims de ML (por order_id detectados + input si parece order_id)
    ml_order_ids_lookup: set[str] = {p.ml_id for p in pedidos if p.ml_id}
    ml_order_ids_lookup.update(detected_ml_ids)
    if ml_id.startswith("2000"):
        ml_order_ids_lookup.add(ml_id)

    claims = _fetch_claims_by_order_ids(sorted(ml_order_ids_lookup))

    # 5. Snapshot crudo de webhook DB (order/pack/shipping)
    webhook_previews = _fetch_webhook_previews(
        order_ids=sorted(ml_order_ids_lookup),
        pack_ids=sorted(detected_pack_ids),
        shipping_ids=sorted(detected_shipping_ids),
    )

    return TrazaMLResponse(
        ml_id=ml_id,
        busqueda_por=busqueda_por,
        ml_ids_relacionados=sorted(detected_ml_ids),
        shipping_ids_relacionados=sorted(detected_shipping_ids),
        pack_ids_relacionados=sorted(detected_pack_ids),
        discrepancias_identificadores=discrepancias_identificadores,
        webhook_previews=webhook_previews,
        pedidos=pedidos,
        seriales=seriales_list,
        rma_por_factura=rma_por_factura,
        claims=claims,
    )
