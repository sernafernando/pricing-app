"""
Seriales — Traza por número de serie.

Endpoint: GET /traza/{serial}
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.routers.seriales_claims import _fetch_claims_by_order_ids
from app.routers.seriales_shared import (
    PedidoSerial,
    TrazaSerialResponse,
    _build_movimientos,
    _build_rma,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# QUERIES (only used by this module)
# =============================================================================

QUERY_PEDIDOS = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        soh.soh_mlid,
        soh.mlshippingid,
        ssos.ssos_name AS estado_nombre
    FROM tb_sale_order_serials sos
    INNER JOIN tb_item_serials s
        ON sos.is_id = s.is_id
        AND sos.comp_id = s.comp_id
        AND sos.bra_id = s.bra_id
    INNER JOIN tb_sale_order_header soh
        ON sos.soh_id = soh.soh_id
        AND sos.comp_id = soh.comp_id
        AND sos.bra_id = soh.bra_id
    LEFT JOIN tb_customer cust
        ON soh.comp_id = cust.comp_id
        AND soh.cust_id = cust.cust_id
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE UPPER(s.is_serial) = UPPER(:serial)
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

# Fallback: buscar pedidos vía bridge table cuando QUERY_PEDIDOS no encuentra nada.
# Cadena: tb_item_serials → tb_item_transaction_serials → tb_item_transactions (mlo_id)
#        → tb_mercadolibre_orders_header (mlo_id) → datos ML directos
# No pasamos por soh porque puede no existir (se archiva).
# Devolvemos las mismas columnas que QUERY_PEDIDOS para reusar el mismo parser de rows.
QUERY_PEDIDOS_VIA_BRIDGE = text("""
    SELECT DISTINCT
        0 AS soh_id,
        s.bra_id,
        mlo.mlo_cd AS soh_cd,
        COALESCE(NULLIF(mlo.cust_id, 0), ct.cust_id, 0) AS cust_id,
        COALESCE(cust_mlo.cust_name, cust_ct.cust_name,
                 TRIM(COALESCE(mlo.mluser_first_name, '') || ' ' || COALESCE(mlo.mluser_last_name, ''))
        ) AS cliente_nombre,
        COALESCE(cust_mlo.cust_taxnumber, cust_ct.cust_taxnumber,
                 mlo.identificationnumber::text
        ) AS cliente_dni,
        COALESCE(cust_mlo.cust_cellphone, cust_mlo.cust_phone1,
                 cust_ct.cust_cellphone, cust_ct.cust_phone1,
                 mlo.mluser_phone, mlo.mluser_receiver_phone
        ) AS cliente_telefono,
        COALESCE(cust_mlo.cust_email, cust_ct.cust_email,
                 mlo.mlo_email
        ) AS cliente_email,
        mlo.mlorder_id AS soh_mlid,
        mlo.mlshippingid::bigint AS mlshippingid,
        mlo.mlo_status AS estado_nombre
    FROM tb_item_serials s
    INNER JOIN tb_item_transaction_serials its
        ON s.comp_id = its.comp_id
        AND s.is_id = its.is_id
    INNER JOIN tb_item_transactions it
        ON its.it_transaction = it.it_transaction
        AND its.comp_id = it.comp_id
    INNER JOIN tb_mercadolibre_orders_header mlo
        ON it.mlo_id = mlo.mlo_id
    LEFT JOIN tb_commercial_transactions ct
        ON its.ct_transaction = ct.ct_transaction
    LEFT JOIN tb_customer cust_mlo
        ON mlo.comp_id = cust_mlo.comp_id
        AND mlo.cust_id = cust_mlo.cust_id
        AND mlo.cust_id IS NOT NULL
        AND mlo.cust_id > 0
    LEFT JOIN tb_customer cust_ct
        ON ct.comp_id = cust_ct.comp_id
        AND ct.cust_id = cust_ct.cust_id
    WHERE UPPER(s.is_serial) = UPPER(:serial)
        AND it.mlo_id IS NOT NULL
        AND it.mlo_id > 0
    ORDER BY mlo.mlo_cd ASC NULLS LAST
""")

# Fallback 2: buscar pedidos por cust_id del movimiento de venta → soh / sohh.
# Para ventas ML que no se facturaron (no hay ct_transaction pero sí soh con mlo_id).
# Usa cust_id extraído del movimiento CLIENTE del serial.
QUERY_PEDIDOS_VIA_CUSTID_SOH = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
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
    WHERE soh.cust_id = :cust_id
    ORDER BY soh.soh_cd DESC
    LIMIT 5
""")

QUERY_PEDIDOS_VIA_CUSTID_SOHH = text("""
    SELECT DISTINCT
        sohh.soh_id,
        sohh.bra_id,
        sohh.soh_cd,
        sohh.cust_id,
        cust.cust_name AS cliente_nombre,
        cust.cust_taxnumber AS cliente_dni,
        COALESCE(cust.cust_cellphone, cust.cust_phone1) AS cliente_telefono,
        cust.cust_email AS cliente_email,
        sohh.soh_mlid,
        NULL::bigint AS mlshippingid,
        NULL AS estado_nombre
    FROM tb_sale_order_header_history sohh
    LEFT JOIN tb_customer cust
        ON sohh.comp_id = cust.comp_id
        AND sohh.cust_id = cust.cust_id
    WHERE sohh.cust_id = :cust_id
    ORDER BY sohh.soh_cd DESC
    LIMIT 5
""")


# =============================================================================
# ENDPOINT
# =============================================================================


@router.get("/traza/{serial}", response_model=TrazaSerialResponse)
def traza_serial(
    serial: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaSerialResponse:
    """
    Obtiene la traza completa de un número de serie.
    Devuelve artículo, movimientos (compras/ventas/transferencias),
    pedidos vinculados y RMAs.
    """
    # Normalizar serial a uppercase (GBP los guarda en mayúsculas)
    serial = serial.strip().upper()

    # 1. Movimientos y artículo
    movimientos, articulo = _build_movimientos(db, serial)

    # 2. Pedidos vinculados — cadena de fallbacks
    # 2a. Directo por sale_order_serials (el ideal)
    result_pedidos = db.execute(QUERY_PEDIDOS, {"serial": serial})
    pedidos_rows = [dict(r._mapping) for r in result_pedidos]

    # 2b. Fallback: bridge → it.mlo_id → mlo (cuando hay factura pero no sale_order_serial)
    if not pedidos_rows:
        result_bridge = db.execute(QUERY_PEDIDOS_VIA_BRIDGE, {"serial": serial})
        pedidos_rows = [dict(r._mapping) for r in result_bridge]

    # 2c. Fallback: cust_id del movimiento CLIENTE → soh / sohh
    #     Para ventas ML sin facturar (no hay ct_transaction pero sí pedido)
    if not pedidos_rows and movimientos:
        venta_cust_ids = [
            m.referencia_id for m in movimientos if m.tipo == "CLIENTE" and m.referencia_id and m.referencia_id > 0
        ]
        for cust_id in venta_cust_ids:
            if pedidos_rows:
                break
            # Primero en soh
            result_soh = db.execute(QUERY_PEDIDOS_VIA_CUSTID_SOH, {"cust_id": cust_id})
            pedidos_rows = [dict(r._mapping) for r in result_soh]
            # Si no, en sohh (history)
            if not pedidos_rows:
                result_sohh = db.execute(QUERY_PEDIDOS_VIA_CUSTID_SOHH, {"cust_id": cust_id})
                pedidos_rows = [dict(r._mapping) for r in result_sohh]

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
            shipping_id=row.get("mlshippingid"),
        )
        for row in pedidos_rows
    ]

    # 3. RMAs
    rma_list, articulo = _build_rma(db, serial, articulo)

    if not movimientos and not pedidos and not rma_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el serial: {serial}",
        )

    # 4. Claims de ML (por order_id de los pedidos)
    ml_order_ids = [p.ml_id for p in pedidos if p.ml_id]
    claims = _fetch_claims_by_order_ids(ml_order_ids)

    return TrazaSerialResponse(
        serial=serial,
        articulo=articulo,
        movimientos=movimientos,
        pedidos=pedidos,
        rma=rma_list,
        claims=claims,
    )
