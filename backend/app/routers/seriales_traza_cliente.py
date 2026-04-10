"""
Seriales — Traza por cliente.

Endpoints:
  GET /traza/cliente/{cust_id}
  GET /traza/cliente-dni/{taxnumber}
  GET /traza/cliente-ml/{nickname}
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.routers.seriales_shared import (
    ClienteInfo,
    LineaPedidoCliente,
    LineaTransaccionCliente,
    PedidoCliente,
    RmaCasoCliente,
    RmaCasoItemCliente,
    RmaErpCliente,
    SerialEnTransaccion,
    TransaccionCliente,
    TrazaClienteResponse,
    construir_nro_documento,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# QUERIES (only used by this module)
# =============================================================================

QUERY_CLIENTE_BY_ID = text("""
    SELECT
        c.cust_id,
        c.cust_name,
        c.cust_name1,
        c.cust_taxnumber,
        tnt.tnt_desc AS tipo_documento,
        fc.fc_desc AS clase_fiscal,
        c.cust_address,
        c.cust_city,
        c.cust_phone1,
        c.cust_cellphone,
        c.cust_email,
        c.cust_mercadolibrenickname,
        c.cust_mercadolibreid,
        COALESCE(c.cust_inactive, false) AS cust_inactive
    FROM tb_customer c
    LEFT JOIN tb_tax_number_type tnt
        ON c.tnt_id = tnt.tnt_id
    LEFT JOIN tb_fiscal_class fc
        ON c.fc_id = fc.fc_id
    WHERE c.cust_id = :cust_id
    LIMIT 1
""")

QUERY_CLIENTE_BY_TAXNUMBER = text("""
    SELECT
        c.cust_id,
        c.cust_name,
        c.cust_name1,
        c.cust_taxnumber,
        tnt.tnt_desc AS tipo_documento,
        fc.fc_desc AS clase_fiscal,
        c.cust_address,
        c.cust_city,
        c.cust_phone1,
        c.cust_cellphone,
        c.cust_email,
        c.cust_mercadolibrenickname,
        c.cust_mercadolibreid,
        COALESCE(c.cust_inactive, false) AS cust_inactive
    FROM tb_customer c
    LEFT JOIN tb_tax_number_type tnt
        ON c.tnt_id = tnt.tnt_id
    LEFT JOIN tb_fiscal_class fc
        ON c.fc_id = fc.fc_id
    WHERE c.cust_taxnumber = :taxnumber
    LIMIT 1
""")

QUERY_CLIENTE_BY_ML_NICKNAME = text("""
    SELECT
        c.cust_id,
        c.cust_name,
        c.cust_name1,
        c.cust_taxnumber,
        tnt.tnt_desc AS tipo_documento,
        fc.fc_desc AS clase_fiscal,
        c.cust_address,
        c.cust_city,
        c.cust_phone1,
        c.cust_cellphone,
        c.cust_email,
        c.cust_mercadolibrenickname,
        c.cust_mercadolibreid,
        COALESCE(c.cust_inactive, false) AS cust_inactive
    FROM tb_customer c
    LEFT JOIN tb_tax_number_type tnt
        ON c.tnt_id = tnt.tnt_id
    LEFT JOIN tb_fiscal_class fc
        ON c.fc_id = fc.fc_id
    WHERE LOWER(c.cust_mercadolibrenickname) = LOWER(:nickname)
    LIMIT 1
""")

QUERY_CLIENTE_FALLBACK_ML = text("""
    SELECT DISTINCT
        moh.cust_id
    FROM tb_mercadolibre_users_data mud
    INNER JOIN tb_mercadolibre_orders_header moh
        ON mud.mluser_id = moh.mluser_id
    WHERE LOWER(mud.nickname) = LOWER(:nickname)
        AND moh.cust_id IS NOT NULL
        AND moh.cust_id > 0
    LIMIT 1
""")

QUERY_TRANSACCIONES_CLIENTE = text("""
    SELECT
        ct.ct_transaction,
        ct.ct_date,
        ct.ct_kindof,
        ct.ct_pointofsale,
        ct.ct_docnumber,
        ct.ct_total,
        ct.ct_soh_id,
        ct.supp_id,
        ct.df_id,
        df.df_desc,
        supp.supp_name AS proveedor_nombre
    FROM tb_commercial_transactions ct
    LEFT JOIN tb_document_file df
        ON ct.comp_id = df.comp_id
        AND ct.bra_id = df.bra_id
        AND ct.df_id = df.df_id
    LEFT JOIN tb_supplier supp
        ON ct.comp_id = supp.comp_id
        AND ct.supp_id = supp.supp_id
    WHERE ct.cust_id = :cust_id
        AND COALESCE(ct.ct_iscancelled, false) = false
    ORDER BY ct.ct_date DESC NULLS LAST, ct.ct_transaction DESC
    LIMIT :limit
    OFFSET :offset
""")

QUERY_TRANSACCIONES_CLIENTE_COUNT = text("""
    SELECT COUNT(*) AS total
    FROM tb_commercial_transactions ct
    WHERE ct.cust_id = :cust_id
        AND COALESCE(ct.ct_iscancelled, false) = false
""")

QUERY_LINEAS_TRANSACCION = text("""
    SELECT
        it.it_transaction,
        it.item_id,
        ti.item_code,
        COALESCE(pe.descripcion, ti.item_desc) AS item_desc,
        it.it_qty AS cantidad,
        it.it_price AS precio_unitario,
        it.it_itemdiscounttotal AS descuento_total,
        COALESCE(it.it_cancelled, false) AS cancelled
    FROM tb_item_transactions it
    LEFT JOIN tb_item ti
        ON it.comp_id = ti.comp_id
        AND it.item_id = ti.item_id
    LEFT JOIN productos_erp pe
        ON it.item_id = pe.item_id
    WHERE it.ct_transaction = :ct_transaction
    ORDER BY it.it_order ASC NULLS LAST, it.it_transaction ASC
""")

QUERY_SERIALES_BY_IT_TRANSACTION = text("""
    SELECT
        s.is_serial,
        s.is_available
    FROM tb_item_serials s
    WHERE s.ct_transaction = :ct_transaction
        AND s.it_transaction = :it_transaction
        AND s.is_serial IS NOT NULL
        AND s.is_serial != ''
    ORDER BY s.is_serial
""")

QUERY_PEDIDOS_CLIENTE = text("""
    SELECT
        soh.soh_id,
        soh.bra_id,
        soh.soh_cd,
        soh.soh_deliverydate,
        soh.soh_total,
        soh.soh_mlid,
        soh.mlshippingid,
        soh.soh_observation1,
        soh.ssos_id,
        ssos.ssos_name
    FROM tb_sale_order_header soh
    LEFT JOIN tb_sale_order_status ssos
        ON soh.ssos_id = ssos.ssos_id
    WHERE soh.cust_id = :cust_id
        AND soh.soh_id NOT IN (
            SELECT sot.soh_id
            FROM tb_sale_order_times sot
            WHERE sot.ssot_id = 40
                AND sot.comp_id = soh.comp_id
                AND sot.bra_id = soh.bra_id
        )
    ORDER BY soh.soh_cd DESC NULLS LAST
    LIMIT 50
""")

QUERY_LINEAS_PEDIDO = text("""
    SELECT
        sod.sod_id,
        sod.item_id,
        ti.item_code,
        COALESCE(pe.descripcion, sod.sod_itemdesc, ti.item_desc) AS item_desc,
        sod.sod_qty AS cantidad,
        sod.sod_price AS precio_unitario
    FROM tb_sale_order_detail sod
    LEFT JOIN tb_item ti
        ON sod.comp_id = ti.comp_id
        AND sod.item_id = ti.item_id
    LEFT JOIN productos_erp pe
        ON sod.item_id = pe.item_id
    WHERE sod.soh_id = :soh_id
        AND sod.comp_id = :comp_id
        AND sod.bra_id = :bra_id
    ORDER BY sod.sod_id ASC
""")

QUERY_SERIALES_PEDIDO = text("""
    SELECT
        s.is_serial,
        s.is_available
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

QUERY_RMA_BY_CUSTOMER = text("""
    SELECT
        d.rmah_id,
        d.rmad_id,
        d.rmad_serial,
        d."rmad_Manual",
        d.item_id,
        d."rmad_originalPrice",
        d.rmad_qty,
        d."rmad_Date_Reception",
        d."rmad_Date_Diagnostic",
        d."rmad_Date_Proc",
        d."rmad_Date_Delivery",
        h.rmah_cd,
        h."rmah_isInSuppplier",
        supp.supp_name AS proveedor_nombre,
        stor.stor_desc,
        pe.codigo AS item_codigo,
        pe.descripcion AS item_descripcion
    FROM tb_rma_detail d
    INNER JOIN tb_rma_header h
        ON d.comp_id = h.comp_id
        AND d.rmah_id = h.rmah_id
        AND d.bra_id = h.bra_id
    LEFT JOIN tb_supplier supp
        ON h.comp_id = supp.comp_id
        AND h.supp_id = supp.supp_id
    LEFT JOIN tb_storage stor
        ON d.comp_id = stor.comp_id
        AND d.stor_id = stor.stor_id
    LEFT JOIN productos_erp pe
        ON d.item_id = pe.item_id
    WHERE h.cust_id = :cust_id
    ORDER BY h.rmah_cd DESC NULLS LAST, d.rmad_id DESC
    LIMIT 100
""")

QUERY_RMA_CASOS_BY_CUSTOMER = text("""
    SELECT
        c.id,
        c.numero_caso,
        c.fecha_caso,
        c.estado,
        c.origen,
        c.ml_id,
        c.observaciones,
        c.monto_cubierto,
        eml.valor AS estado_reclamo_ml_valor,
        cml.valor AS cobertura_ml_valor
    FROM rma_casos c
    LEFT JOIN rma_seguimiento_opciones eml
        ON c.estado_reclamo_ml_id = eml.id
    LEFT JOIN rma_seguimiento_opciones cml
        ON c.cobertura_ml_id = cml.id
    WHERE c.cust_id = :cust_id
    ORDER BY c.created_at DESC NULLS LAST
    LIMIT 50
""")

QUERY_RMA_CASO_ITEMS = text("""
    SELECT
        i.id,
        i.serial_number,
        i.producto_desc,
        i.precio,
        i.proveedor_nombre,
        i.observaciones,
        er.valor AS estado_recepcion_valor,
        cd.valor AS causa_devolucion_valor,
        av.valor AS apto_venta_valor,
        rev.valor AS estado_revision_valor,
        ep.valor AS estado_proceso_valor,
        esp.valor AS estado_proveedor_valor
    FROM rma_caso_items i
    LEFT JOIN rma_seguimiento_opciones er ON i.estado_recepcion_id = er.id
    LEFT JOIN rma_seguimiento_opciones cd ON i.causa_devolucion_id = cd.id
    LEFT JOIN rma_seguimiento_opciones av ON i.apto_venta_id = av.id
    LEFT JOIN rma_seguimiento_opciones rev ON i.estado_revision_id = rev.id
    LEFT JOIN rma_seguimiento_opciones ep ON i.estado_proceso_id = ep.id
    LEFT JOIN rma_seguimiento_opciones esp ON i.estado_proveedor_id = esp.id
    WHERE i.caso_id = :caso_id
    ORDER BY i.id ASC
""")


# =============================================================================
# BUILDERS (only used by this module)
# =============================================================================


def _build_cliente_info(row: dict) -> ClienteInfo:
    """Construye ClienteInfo desde un row de tb_customer."""
    return ClienteInfo(
        cust_id=row["cust_id"],
        nombre=row.get("cust_name") or "",
        nombre_alt=row.get("cust_name1"),
        cuit_dni=row.get("cust_taxnumber"),
        tipo_documento=row.get("tipo_documento"),
        clase_fiscal=row.get("clase_fiscal"),
        direccion=row.get("cust_address"),
        ciudad=row.get("cust_city"),
        telefono=row.get("cust_phone1"),
        celular=row.get("cust_cellphone"),
        email=row.get("cust_email"),
        ml_nickname=row.get("cust_mercadolibrenickname"),
        ml_id=row.get("cust_mercadolibreid"),
        inactivo=bool(row.get("cust_inactive", False)),
    )


def _find_cliente_by_ml_nickname(db: Session, nickname: str) -> tuple[Optional[ClienteInfo], str]:
    """
    Busca cliente por ML nickname:
    1. Primero en tb_customer.cust_mercadolibrenickname
    2. Fallback: tb_mercadolibre_users_data.nickname → orders → cust_id → tb_customer
    Retorna (cliente_info, busqueda_por)
    """
    # Paso 1: Búsqueda directa en tb_customer
    result = db.execute(QUERY_CLIENTE_BY_ML_NICKNAME, {"nickname": nickname})
    row = result.fetchone()
    if row:
        return _build_cliente_info(dict(row._mapping)), "ml_nickname"

    # Paso 2: Fallback vía tabla de usuarios ML
    result_fb = db.execute(QUERY_CLIENTE_FALLBACK_ML, {"nickname": nickname})
    fb_row = result_fb.fetchone()
    if fb_row:
        cust_id = dict(fb_row._mapping)["cust_id"]
        result_cust = db.execute(QUERY_CLIENTE_BY_ID, {"cust_id": cust_id})
        cust_row = result_cust.fetchone()
        if cust_row:
            return _build_cliente_info(dict(cust_row._mapping)), "ml_fallback"

    return None, "ml_nickname"


def _build_rmas_erp_cliente(db: Session, cust_id: int) -> list[RmaErpCliente]:
    """
    Obtiene los RMAs del ERP (GBP) vinculados al cliente por cust_id.
    Devuelve hasta 100 registros ordenados por fecha desc.
    """
    result = db.execute(QUERY_RMA_BY_CUSTOMER, {"cust_id": cust_id})
    rows = [dict(r._mapping) for r in result]

    rmas: list[RmaErpCliente] = []
    for row in rows:
        serial = row.get("rmad_serial") or row.get("rmad_Manual") or None
        precio = row.get("rmad_originalPrice")
        qty = row.get("rmad_qty")
        fecha_rma = row.get("rmah_cd")

        rmas.append(
            RmaErpCliente(
                rmah_id=row["rmah_id"],
                rmad_id=row["rmad_id"],
                fecha_rma=str(fecha_rma) if fecha_rma else None,
                item_codigo=row.get("item_codigo"),
                item_descripcion=row.get("item_descripcion"),
                serial=serial,
                cantidad=float(qty) if qty is not None else None,
                precio_original=float(precio) if precio is not None else None,
                deposito=row.get("stor_desc"),
                proveedor=row.get("proveedor_nombre"),
                en_proveedor=bool(row.get("rmah_isInSuppplier", False)),
                fecha_recepcion=(str(row["rmad_Date_Reception"]) if row.get("rmad_Date_Reception") else None),
                fecha_diagnostico=(str(row["rmad_Date_Diagnostic"]) if row.get("rmad_Date_Diagnostic") else None),
                fecha_procesamiento=(str(row["rmad_Date_Proc"]) if row.get("rmad_Date_Proc") else None),
                fecha_entrega=(str(row["rmad_Date_Delivery"]) if row.get("rmad_Date_Delivery") else None),
            )
        )

    return rmas


def _build_rmas_internos_cliente(db: Session, cust_id: int) -> list[RmaCasoCliente]:
    """
    Obtiene los casos RMA internos (rma_casos) vinculados al cliente.
    Para cada caso, carga sus items con los estados resueltos desde rma_seguimiento_opciones.
    """
    result = db.execute(QUERY_RMA_CASOS_BY_CUSTOMER, {"cust_id": cust_id})
    rows = [dict(r._mapping) for r in result]

    casos: list[RmaCasoCliente] = []
    for row in rows:
        caso_id = row["id"]
        fecha = row.get("fecha_caso")
        monto = row.get("monto_cubierto")

        # Items del caso
        result_items = db.execute(QUERY_RMA_CASO_ITEMS, {"caso_id": caso_id})
        items_rows = [dict(ir._mapping) for ir in result_items]

        items: list[RmaCasoItemCliente] = []
        for ir in items_rows:
            precio_item = ir.get("precio")
            items.append(
                RmaCasoItemCliente(
                    id=ir["id"],
                    serial_number=ir.get("serial_number"),
                    producto_desc=ir.get("producto_desc"),
                    precio=float(precio_item) if precio_item is not None else None,
                    estado_recepcion=ir.get("estado_recepcion_valor"),
                    causa_devolucion=ir.get("causa_devolucion_valor"),
                    apto_venta=ir.get("apto_venta_valor"),
                    estado_revision=ir.get("estado_revision_valor"),
                    estado_proceso=ir.get("estado_proceso_valor"),
                    estado_proveedor=ir.get("estado_proveedor_valor"),
                    proveedor_nombre=ir.get("proveedor_nombre"),
                )
            )

        casos.append(
            RmaCasoCliente(
                id=caso_id,
                numero_caso=row.get("numero_caso", ""),
                fecha_caso=str(fecha) if fecha else None,
                estado=row.get("estado"),
                origen=row.get("origen"),
                ml_id=row.get("ml_id"),
                observaciones=row.get("observaciones"),
                estado_reclamo_ml=row.get("estado_reclamo_ml_valor"),
                cobertura_ml=row.get("cobertura_ml_valor"),
                monto_cubierto=float(monto) if monto is not None else None,
                items=items,
            )
        )

    return casos


def _build_pedidos_cliente(db: Session, cust_id: int) -> list[PedidoCliente]:
    """
    Obtiene los pedidos activos (sale orders no cerrados) de un cliente.
    Un pedido se considera cerrado si tiene un registro en tb_sale_order_times
    con ssot_id = 40 (Cierre del Pedido).
    Incluye líneas de detalle y seriales por pedido.
    """
    result = db.execute(QUERY_PEDIDOS_CLIENTE, {"cust_id": cust_id})
    soh_rows = [dict(row._mapping) for row in result]

    pedidos: list[PedidoCliente] = []
    for soh in soh_rows:
        soh_id = soh["soh_id"]
        bra_id = soh.get("bra_id", 1)
        comp_id = 1  # Single-company app

        # Líneas del pedido
        result_lineas = db.execute(
            QUERY_LINEAS_PEDIDO,
            {"soh_id": soh_id, "comp_id": comp_id, "bra_id": bra_id},
        )
        lineas_rows = [dict(r._mapping) for r in result_lineas]

        # Seriales del pedido (a nivel pedido, no por línea)
        result_seriales = db.execute(
            QUERY_SERIALES_PEDIDO,
            {"soh_id": soh_id, "comp_id": comp_id, "bra_id": bra_id},
        )
        seriales_pedido = [
            SerialEnTransaccion(
                is_serial=dict(sr._mapping)["is_serial"],
                is_available=bool(dict(sr._mapping).get("is_available", False)),
            )
            for sr in result_seriales
        ]

        lineas: list[LineaPedidoCliente] = []
        for lr in lineas_rows:
            qty = lr.get("cantidad")
            precio = lr.get("precio_unitario")

            lineas.append(
                LineaPedidoCliente(
                    sod_id=lr["sod_id"],
                    item_id=lr.get("item_id"),
                    item_code=lr.get("item_code"),
                    item_desc=lr.get("item_desc"),
                    cantidad=float(qty) if qty is not None else None,
                    precio_unitario=float(precio) if precio is not None else None,
                    seriales=[],  # seriales are at pedido level via tb_sale_order_serials
                )
            )

        soh_total = soh.get("soh_total")
        soh_cd = soh.get("soh_cd")
        soh_dd = soh.get("soh_deliverydate")
        mlshipping = soh.get("mlshippingid")

        pedidos.append(
            PedidoCliente(
                soh_id=soh_id,
                bra_id=bra_id,
                fecha=str(soh_cd) if soh_cd else None,
                fecha_entrega=str(soh_dd) if soh_dd else None,
                estado=soh.get("ssos_name"),
                total=float(soh_total) if soh_total is not None else None,
                ml_id=soh.get("soh_mlid"),
                shipping_id=int(mlshipping) if mlshipping else None,
                observacion=soh.get("soh_observation1"),
                lineas=lineas,
            )
        )

        # Attach seriales to the first matching linea or keep at pedido level
        # For simplicity, we put all seriales on the pedido's first line or distribute
        # Actually: seriales come from tb_sale_order_serials which is at pedido level,
        # not per-line. We'll attach them as a flat list on the first line that has items.
        if seriales_pedido and lineas:
            lineas[0].seriales = seriales_pedido

    return pedidos


def _build_transacciones_cliente(
    db: Session, cust_id: int, limit: int = 50, offset: int = 0
) -> tuple[list[TransaccionCliente], int]:
    """
    Obtiene las transacciones comerciales de un cliente con sus líneas y seriales.
    Retorna (transacciones, total_count).
    """
    # Total count
    count_result = db.execute(QUERY_TRANSACCIONES_CLIENTE_COUNT, {"cust_id": cust_id})
    total = count_result.scalar() or 0

    # Transacciones paginadas
    result = db.execute(
        QUERY_TRANSACCIONES_CLIENTE,
        {"cust_id": cust_id, "limit": limit, "offset": offset},
    )
    ct_rows = [dict(row._mapping) for row in result]

    transacciones: list[TransaccionCliente] = []
    for ct_row in ct_rows:
        ct_id = ct_row["ct_transaction"]
        ct_date = ct_row.get("ct_date")
        ct_total = ct_row.get("ct_total")

        # Líneas de esta transacción
        result_lineas = db.execute(QUERY_LINEAS_TRANSACCION, {"ct_transaction": ct_id})
        lineas_rows = [dict(r._mapping) for r in result_lineas]

        lineas: list[LineaTransaccionCliente] = []
        for lr in lineas_rows:
            qty = lr.get("cantidad")
            precio = lr.get("precio_unitario")
            descuento = lr.get("descuento_total")

            # Seriales de esta línea
            result_seriales = db.execute(
                QUERY_SERIALES_BY_IT_TRANSACTION,
                {
                    "ct_transaction": ct_id,
                    "it_transaction": lr["it_transaction"],
                },
            )
            seriales = [
                SerialEnTransaccion(
                    is_serial=dict(sr._mapping)["is_serial"],
                    is_available=bool(dict(sr._mapping).get("is_available", False)),
                )
                for sr in result_seriales
            ]

            lineas.append(
                LineaTransaccionCliente(
                    it_transaction=lr["it_transaction"],
                    item_id=lr.get("item_id"),
                    item_code=lr.get("item_code"),
                    item_desc=lr.get("item_desc"),
                    cantidad=float(qty) if qty is not None else None,
                    precio_unitario=float(precio) if precio is not None else None,
                    descuento_total=float(descuento) if descuento is not None else None,
                    cancelled=bool(lr.get("cancelled", False)),
                    seriales=seriales,
                )
            )

        transacciones.append(
            TransaccionCliente(
                ct_transaction=ct_id,
                fecha=str(ct_date) if ct_date else None,
                tipo_doc=ct_row.get("df_desc"),
                kindof=ct_row.get("ct_kindof"),
                punto_venta=ct_row.get("ct_pointofsale"),
                nro_documento=construir_nro_documento(ct_row),
                total=float(ct_total) if ct_total is not None else None,
                supp_id=ct_row.get("supp_id"),
                proveedor=ct_row.get("proveedor_nombre"),
                soh_id=ct_row.get("ct_soh_id"),
                lineas=lineas,
            )
        )

    return transacciones, total


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/traza/cliente/{cust_id}", response_model=TrazaClienteResponse)
def traza_cliente(
    cust_id: int,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaClienteResponse:
    """
    Obtiene la traza de transacciones por # de cliente (cust_id).
    Devuelve info del cliente + sus transacciones con líneas y seriales.
    Paginado: page (1-indexed), page_size (default 50).
    """
    result = db.execute(QUERY_CLIENTE_BY_ID, {"cust_id": cust_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el cliente #{cust_id}",
        )

    cliente = _build_cliente_info(dict(row._mapping))
    offset = (max(page, 1) - 1) * page_size
    transacciones, total = _build_transacciones_cliente(db, cust_id, limit=page_size, offset=offset)
    pedidos = _build_pedidos_cliente(db, cust_id)
    rmas_erp = _build_rmas_erp_cliente(db, cust_id)
    rmas_internos = _build_rmas_internos_cliente(db, cust_id)

    return TrazaClienteResponse(
        busqueda_por="cust_id",
        cliente=cliente,
        transacciones=transacciones,
        total_transacciones=total,
        pedidos=pedidos,
        rmas_erp=rmas_erp,
        rmas_internos=rmas_internos,
    )


@router.get("/traza/cliente-dni/{taxnumber}", response_model=TrazaClienteResponse)
def traza_cliente_dni(
    taxnumber: str,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaClienteResponse:
    """
    Obtiene la traza de transacciones por DNI/CUIT del cliente.
    Busca en tb_customer.cust_taxnumber (match exacto).
    Paginado: page (1-indexed), page_size (default 50).
    """
    # Limpiar el taxnumber: sacar guiones para normalizar
    clean_tax = taxnumber.strip().replace("-", "")
    result = db.execute(QUERY_CLIENTE_BY_TAXNUMBER, {"taxnumber": clean_tax})
    row = result.fetchone()

    if not row:
        # Intentar con el valor original (por si está guardado con guiones)
        result = db.execute(QUERY_CLIENTE_BY_TAXNUMBER, {"taxnumber": taxnumber.strip()})
        row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró cliente con DNI/CUIT: {taxnumber}",
        )

    row_dict = dict(row._mapping)
    cid = row_dict["cust_id"]
    cliente = _build_cliente_info(row_dict)
    offset = (max(page, 1) - 1) * page_size
    transacciones, total = _build_transacciones_cliente(db, cid, limit=page_size, offset=offset)
    pedidos = _build_pedidos_cliente(db, cid)
    rmas_erp = _build_rmas_erp_cliente(db, cid)
    rmas_internos = _build_rmas_internos_cliente(db, cid)

    return TrazaClienteResponse(
        busqueda_por="taxnumber",
        cliente=cliente,
        transacciones=transacciones,
        total_transacciones=total,
        pedidos=pedidos,
        rmas_erp=rmas_erp,
        rmas_internos=rmas_internos,
    )


@router.get("/traza/cliente-ml/{nickname}", response_model=TrazaClienteResponse)
def traza_cliente_ml(
    nickname: str,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaClienteResponse:
    """
    Obtiene la traza de transacciones por usuario de MercadoLibre.
    1. Busca en tb_customer.cust_mercadolibrenickname (match exacto case-insensitive).
    2. Fallback: busca en tb_mercadolibre_users_data.nickname → orders → cust_id.
    Paginado: page (1-indexed), page_size (default 50).
    """
    cliente, busqueda_por = _find_cliente_by_ml_nickname(db, nickname.strip())

    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró cliente con usuario ML: {nickname}",
        )

    cid = cliente.cust_id
    offset = (max(page, 1) - 1) * page_size
    transacciones, total = _build_transacciones_cliente(db, cid, limit=page_size, offset=offset)
    pedidos = _build_pedidos_cliente(db, cid)
    rmas_erp = _build_rmas_erp_cliente(db, cid)
    rmas_internos = _build_rmas_internos_cliente(db, cid)

    return TrazaClienteResponse(
        busqueda_por=busqueda_por,
        cliente=cliente,
        transacciones=transacciones,
        total_transacciones=total,
        pedidos=pedidos,
        rmas_erp=rmas_erp,
        rmas_internos=rmas_internos,
    )
