"""
Router para traza de números de serie (módulo RMA)
Permite consultar el historial completo de movimientos de un serial.
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional

from app.core.config import settings
from app.core.database import get_db, get_mlwebhook_engine, SessionLocal
from app.core.deps import get_current_user
from app.models.rma_claim_ml import RmaClaimML
from app.models.rma_claim_ml_message import RmaClaimMLMessage
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)

ML_WEBHOOK_RENDER_URL = "https://ml-webhook.gaussonline.com.ar/api/ml/render"
_HTTPX_TIMEOUT = 10.0  # seconds per request to ML webhook proxy

router = APIRouter(prefix="/seriales", tags=["Seriales"])


# =============================================================================
# SCHEMAS
# =============================================================================


class ArticuloInfo(BaseModel):
    """Info del artículo asociado al serial"""

    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None
    categoria: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MovimientoSerial(BaseModel):
    """Un movimiento del serial (compra, venta, transferencia, etc.)"""

    is_id: int
    ct_transaction: Optional[int] = None  # ID de transacción comercial (para expandir detalle)
    fecha_documento: Optional[str] = None  # Fecha del documento comercial
    fecha_seriado: Optional[str] = None  # Fecha y hora de serialización
    tipo: Optional[str] = None  # PROVEEDOR, CLIENTE, TRANSFERENCIA
    referencia_id: Optional[int] = None  # cust_id o supp_id
    referencia_nombre: Optional[str] = None  # nombre del cliente/proveedor
    nro_documento: Optional[str] = None  # Fc A 00004-0000128762
    dias_a_la_fecha: Optional[int] = None
    estado: Optional[str] = None
    deposito: Optional[str] = None
    deposito_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PedidoSerial(BaseModel):
    """Sale order vinculado al serial"""

    soh_id: int
    bra_id: int
    fecha: Optional[str] = None
    estado: Optional[str] = None
    cust_id: Optional[int] = None
    cliente: Optional[str] = None
    cliente_dni: Optional[str] = None
    cliente_telefono: Optional[str] = None
    cliente_email: Optional[str] = None
    ml_id: Optional[str] = None
    shipping_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class RMAHistorialEstado(BaseModel):
    """Un cambio de estado en el historial del RMA"""

    rmadh_id: int
    fecha: Optional[str] = None
    user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class RMASerial(BaseModel):
    """RMA vinculado al serial"""

    rmah_id: int
    rmad_id: int
    bra_id: int
    match_por: str  # "is_id", "rmad_serial", "rmad_Manual"
    # Header
    fecha_rma: Optional[str] = None
    cust_id: Optional[int] = None
    cliente: Optional[str] = None
    supp_id: Optional[int] = None
    proveedor: Optional[str] = None
    en_proveedor: Optional[bool] = None
    # Detail
    item_id: Optional[int] = None
    item_codigo: Optional[str] = None
    item_descripcion: Optional[str] = None
    rmad_serial: Optional[str] = None
    rmad_Manual: Optional[str] = None
    precio_original: Optional[float] = None
    cantidad: Optional[float] = None
    deposito: Optional[str] = None
    # Etapas
    fecha_recepcion: Optional[str] = None
    nota_recepcion: Optional[str] = None
    fecha_diagnostico: Optional[str] = None
    nota_diagnostico: Optional[str] = None
    fecha_procesamiento: Optional[str] = None
    nota_procesamiento: Optional[str] = None
    fecha_entrega: Optional[str] = None
    nota_entrega: Optional[str] = None
    # Garantía
    garantia: Optional[str] = None
    # Historial de estados
    historial: list[RMAHistorialEstado] = []

    model_config = ConfigDict(from_attributes=True)


class ClaimExpectedResolution(BaseModel):
    """Resolución esperada por un actor del reclamo"""

    player_role: Optional[str] = None  # complainant, respondent, mediator
    expected_resolution: Optional[str] = None  # refund, return_product, change_product, partial_refund
    status: Optional[str] = None  # pending, accepted, rejected
    details: Optional[list] = None  # [{key, value}] — ej: percentage, seller_amount
    date_created: Optional[str] = None
    last_updated: Optional[str] = None


class ClaimReturnShipment(BaseModel):
    """Envío de devolución asociado a un claim"""

    shipment_id: Optional[int] = None
    status: Optional[str] = None  # pending, ready_to_ship, shipped, delivered, cancelled, etc.
    tracking_number: Optional[str] = None
    destination_name: Optional[str] = None  # seller_address, warehouse
    shipment_type: Optional[str] = None  # return, return_from_triage


class ClaimReturn(BaseModel):
    """Devolución asociada a un claim"""

    return_id: Optional[int] = None
    status: Optional[str] = None  # pending, label_generated, shipped, delivered, expired, cancelled...
    subtype: Optional[str] = None  # low_cost, return_partial, return_total
    status_money: Optional[str] = None  # retained, refunded, available
    refund_at: Optional[str] = None  # shipped, delivered, n/a
    shipments: list[ClaimReturnShipment] = []
    date_created: Optional[str] = None
    date_closed: Optional[str] = None


class ClaimChange(BaseModel):
    """Cambio/reemplazo asociado a un claim"""

    change_type: Optional[str] = None  # change, replace
    status: Optional[str] = None
    status_detail: Optional[str] = None
    new_order_ids: Optional[list[int]] = None
    date_created: Optional[str] = None
    last_updated: Optional[str] = None


class ClaimML(BaseModel):
    """Claim de MercadoLibre asociado a una orden"""

    claim_id: Optional[str] = None
    claim_type: Optional[str] = None  # mediations, return, fulfillment, etc.
    claim_stage: Optional[str] = None  # claim, dispute, recontact, stale
    status: Optional[str] = None  # opened, closed
    # Motivo
    reason_id: Optional[str] = None
    reason_category: Optional[str] = None  # PDD, PNR, CS
    reason_detail: Optional[str] = None  # Texto legible del motivo
    # Clasificación
    triage_tags: Optional[list] = None  # ["defective", "repentant", etc.]
    expected_resolutions: Optional[list] = None  # ["return_product", "refund", etc.]
    # Estado de entrega
    fulfilled: Optional[bool] = None
    quantity_type: Optional[str] = None  # total, partial
    claimed_quantity: Optional[int] = None
    # Acciones pendientes
    seller_actions: Optional[list] = None
    mandatory_actions: Optional[list] = None
    nearest_due_date: Optional[str] = None
    action_responsible: Optional[str] = None  # seller, buyer, mediator
    # Detail legible
    detail_title: Optional[str] = None
    detail_description: Optional[str] = None  # Texto largo descriptivo del estado
    detail_problem: Optional[str] = None
    # Resolución (solo si cerrado)
    resolution_reason: Optional[str] = None
    resolution_closed_by: Optional[str] = None
    resolution_coverage: Optional[bool] = None
    # Entidades relacionadas
    related_entities: Optional[list[str]] = None  # ["return", "change", "reviews"]
    # Resoluciones esperadas (detalle de negociación)
    expected_resolutions_detail: Optional[list[ClaimExpectedResolution]] = None
    # Devolución
    claim_return: Optional[ClaimReturn] = None
    # Cambio/reemplazo
    claim_change: Optional[ClaimChange] = None
    # Mensajes
    messages_total: Optional[int] = None
    # Reputación
    affects_reputation: Optional[bool] = None
    has_incentive: Optional[bool] = None  # 48hs para resolver
    # Fechas
    date_created: Optional[str] = None
    last_updated: Optional[str] = None
    # Recurso asociado
    resource_id: Optional[str] = None  # order_id

    model_config = ConfigDict(from_attributes=True)


class TrazaSerialResponse(BaseModel):
    """Respuesta completa de traza de un serial"""

    serial: str
    articulo: Optional[ArticuloInfo] = None
    movimientos: list[MovimientoSerial] = []
    pedidos: list[PedidoSerial] = []
    rma: list[RMASerial] = []
    claims: list[ClaimML] = []

    model_config = ConfigDict(from_attributes=True)


class TrazaMLSerialItem(BaseModel):
    """Traza de un serial individual dentro de una venta ML"""

    serial: str
    articulo: Optional[ArticuloInfo] = None
    movimientos: list[MovimientoSerial] = []
    rma: list[RMASerial] = []

    model_config = ConfigDict(from_attributes=True)


class TrazaMLResponse(BaseModel):
    """Respuesta completa de traza por venta ML"""

    ml_id: str
    busqueda_por: str = "soh_mlid"  # soh_mlid | ml_pack_id | soh_mlguia | mlshippingid
    pedidos: list[PedidoSerial] = []
    seriales: list[TrazaMLSerialItem] = []
    rma_por_factura: list[RMASerial] = []  # RMAs encontrados vía factura (no por serial)
    claims: list[ClaimML] = []

    model_config = ConfigDict(from_attributes=True)


class FacturaInfo(BaseModel):
    """Info de la factura (transacción comercial)"""

    ct_transaction: int
    bra_id: int
    tipo: str  # ct_kindof (A, B, C...)
    punto_venta: int  # ct_pointofsale
    nro_documento: str  # ct_docnumber
    fecha: Optional[str] = None
    total: Optional[float] = None
    cust_id: Optional[int] = None
    cliente: Optional[str] = None
    supp_id: Optional[int] = None
    proveedor: Optional[str] = None
    soh_id: Optional[int] = None  # Pedido vinculado si existe

    model_config = ConfigDict(from_attributes=True)


class TrazaFacturaResponse(BaseModel):
    """Respuesta completa de traza por número de factura"""

    factura: FacturaInfo
    seriales: list[TrazaMLSerialItem] = []
    rma_por_serial: list[RMASerial] = []  # RMAs encontrados vía serial
    rma_por_factura: list[RMASerial] = []  # RMAs encontrados vía línea de factura

    model_config = ConfigDict(from_attributes=True)


class FacturaDetalleItem(BaseModel):
    """Una línea de una factura (item transaction)"""

    it_transaction: int
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    item_desc: Optional[str] = None
    cantidad: Optional[float] = None
    precio_unitario: Optional[float] = None
    precio_sin_otros: Optional[float] = None
    descuento_total: Optional[float] = None
    cancelled: bool = False

    model_config = ConfigDict(from_attributes=True)


class FacturaDetalleResponse(BaseModel):
    """Respuesta del detalle de líneas de una factura"""

    ct_transaction: int
    items: list[FacturaDetalleItem] = []

    model_config = ConfigDict(from_attributes=True)


# ── Customer traza schemas ───────────────────────────────────────


class ClienteInfo(BaseModel):
    """Info del cliente encontrado"""

    cust_id: int
    nombre: str
    nombre_alt: Optional[str] = None
    cuit_dni: Optional[str] = None
    tipo_documento: Optional[str] = None  # "CUIT", "DNI", etc.
    clase_fiscal: Optional[str] = None  # "Resp. Inscripto", etc.
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    telefono: Optional[str] = None
    celular: Optional[str] = None
    email: Optional[str] = None
    ml_nickname: Optional[str] = None
    ml_id: Optional[str] = None
    inactivo: bool = False

    model_config = ConfigDict(from_attributes=True)


class SerialEnTransaccion(BaseModel):
    """Un serial encontrado en una línea de una transacción"""

    is_serial: str
    is_available: bool = False

    model_config = ConfigDict(from_attributes=True)


class LineaTransaccionCliente(BaseModel):
    """Una línea de producto dentro de una transacción del cliente"""

    it_transaction: int
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    item_desc: Optional[str] = None
    cantidad: Optional[float] = None
    precio_unitario: Optional[float] = None
    descuento_total: Optional[float] = None
    cancelled: bool = False
    seriales: list[SerialEnTransaccion] = []

    model_config = ConfigDict(from_attributes=True)


class TransaccionCliente(BaseModel):
    """Una transacción comercial (factura/NC/remito) del cliente"""

    ct_transaction: int
    fecha: Optional[str] = None
    tipo_doc: Optional[str] = None  # df_desc (ej: "Fc A 0005")
    kindof: Optional[str] = None  # A, B, C...
    punto_venta: Optional[int] = None
    nro_documento: Optional[str] = None  # formatted
    total: Optional[float] = None
    supp_id: Optional[int] = None
    proveedor: Optional[str] = None
    soh_id: Optional[int] = None
    lineas: list[LineaTransaccionCliente] = []

    model_config = ConfigDict(from_attributes=True)


class LineaPedidoCliente(BaseModel):
    """Una línea de producto dentro de un pedido (sale order)"""

    sod_id: int
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    item_desc: Optional[str] = None
    cantidad: Optional[float] = None
    precio_unitario: Optional[float] = None
    seriales: list[SerialEnTransaccion] = []

    model_config = ConfigDict(from_attributes=True)


class PedidoCliente(BaseModel):
    """Un pedido (sale order) activo del cliente"""

    soh_id: int
    bra_id: int = 1
    fecha: Optional[str] = None
    fecha_entrega: Optional[str] = None
    estado: Optional[str] = None  # ssos_name
    total: Optional[float] = None
    ml_id: Optional[str] = None
    shipping_id: Optional[int] = None
    observacion: Optional[str] = None
    lineas: list[LineaPedidoCliente] = []

    model_config = ConfigDict(from_attributes=True)


class RmaErpCliente(BaseModel):
    """Un RMA del ERP (GBP) vinculado al cliente"""

    rmah_id: int
    rmad_id: int
    fecha_rma: Optional[str] = None
    item_codigo: Optional[str] = None
    item_descripcion: Optional[str] = None
    serial: Optional[str] = None
    cantidad: Optional[float] = None
    precio_original: Optional[float] = None
    deposito: Optional[str] = None
    proveedor: Optional[str] = None
    en_proveedor: bool = False
    # Etapas
    fecha_recepcion: Optional[str] = None
    fecha_diagnostico: Optional[str] = None
    fecha_procesamiento: Optional[str] = None
    fecha_entrega: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RmaCasoItemCliente(BaseModel):
    """Un item dentro de un caso RMA interno"""

    id: int
    serial_number: Optional[str] = None
    producto_desc: Optional[str] = None
    precio: Optional[float] = None
    estado_recepcion: Optional[str] = None
    causa_devolucion: Optional[str] = None
    apto_venta: Optional[str] = None
    estado_revision: Optional[str] = None
    estado_proceso: Optional[str] = None
    estado_proveedor: Optional[str] = None
    proveedor_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RmaCasoCliente(BaseModel):
    """Un caso RMA interno vinculado al cliente"""

    id: int
    numero_caso: str
    fecha_caso: Optional[str] = None
    estado: Optional[str] = None
    origen: Optional[str] = None
    ml_id: Optional[str] = None
    observaciones: Optional[str] = None
    estado_reclamo_ml: Optional[str] = None
    cobertura_ml: Optional[str] = None
    monto_cubierto: Optional[float] = None
    items: list[RmaCasoItemCliente] = []

    model_config = ConfigDict(from_attributes=True)


class TrazaClienteResponse(BaseModel):
    """Respuesta completa de traza por cliente"""

    busqueda_por: str  # "cust_id", "taxnumber", "ml_nickname", "ml_fallback"
    cliente: ClienteInfo
    transacciones: list[TransaccionCliente] = []
    total_transacciones: int = 0
    pedidos: list[PedidoCliente] = []
    rmas_erp: list[RmaErpCliente] = []
    rmas_internos: list[RmaCasoCliente] = []

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# QUERIES
# =============================================================================

QUERY_TRAZA = text("""
    WITH serial_movimientos AS (
        SELECT
            s.is_id,
            s.item_id,
            s.ct_transaction,
            s.it_transaction,
            s.stor_id,
            s.is_cd,
            s.is_available,
            -- Tipo de documento y número
            ct.ct_kindof,
            ct.ct_pointofsale,
            ct.ct_docnumber,
            ct.ct_date,
            ct.cust_id,
            ct.supp_id,
            ct.df_id,
            -- Document file description
            df.df_desc,
            -- Cliente
            cust.cust_name AS cliente_nombre,
            -- Proveedor
            supp.supp_name AS proveedor_nombre,
            -- Depósito
            stor.stor_desc,
            -- Artículo
            pe.codigo AS item_codigo,
            pe.descripcion AS item_descripcion,
            pe.marca AS item_marca,
            cat.cat_desc AS item_categoria
        FROM tb_item_serials s
        LEFT JOIN tb_commercial_transactions ct
            ON s.ct_transaction = ct.ct_transaction
        LEFT JOIN tb_document_file df
            ON ct.comp_id = df.comp_id
            AND ct.bra_id = df.bra_id
            AND ct.df_id = df.df_id
        LEFT JOIN tb_customer cust
            ON ct.comp_id = cust.comp_id
            AND ct.cust_id = cust.cust_id
        LEFT JOIN tb_supplier supp
            ON ct.comp_id = supp.comp_id
            AND ct.supp_id = supp.supp_id
        LEFT JOIN tb_storage stor
            ON s.comp_id = stor.comp_id
            AND s.stor_id = stor.stor_id
        LEFT JOIN productos_erp pe
            ON s.item_id = pe.item_id
        LEFT JOIN tb_item ti
            ON s.comp_id = ti.comp_id
            AND s.item_id = ti.item_id
        LEFT JOIN tb_category cat
            ON ti.comp_id = cat.comp_id
            AND ti.cat_id = cat.cat_id
        WHERE s.is_serial = :serial
        ORDER BY s.is_cd ASC NULLS LAST, s.is_id ASC
    )
    SELECT * FROM serial_movimientos
""")

QUERY_RMA = text("""
    SELECT
        d.rmah_id,
        d.rmad_id,
        d.bra_id,
        d.comp_id,
        d.is_id,
        d.rmad_serial,
        d."rmad_Manual",
        d.item_id,
        d."rmad_originalPrice",
        d.rmad_qty,
        d.stor_id,
        -- Etapas
        d."rmad_Date_Reception",
        d."rmad_ReceptionNote",
        d."rmad_Date_Diagnostic",
        d."rmad_DiagnosticNote",
        d."rmad_Date_Proc",
        d."rmad_ProcNote",
        d."rmad_Date_Delivery",
        d."rmad_DelioveryNote",
        -- Garantía
        d."rmad_insertWarrantyDetail",
        -- Header
        h.rmah_cd,
        h.cust_id,
        h.supp_id,
        h."rmah_isInSuppplier",
        -- Joins
        cust.cust_name AS cliente_nombre,
        supp.supp_name AS proveedor_nombre,
        stor.stor_desc,
        pe.codigo AS item_codigo,
        pe.descripcion AS item_descripcion
    FROM tb_rma_detail d
    INNER JOIN tb_rma_header h
        ON d.comp_id = h.comp_id
        AND d.rmah_id = h.rmah_id
        AND d.bra_id = h.bra_id
    LEFT JOIN tb_customer cust
        ON h.comp_id = cust.comp_id
        AND h.cust_id = cust.cust_id
    LEFT JOIN tb_supplier supp
        ON h.comp_id = supp.comp_id
        AND h.supp_id = supp.supp_id
    LEFT JOIN tb_storage stor
        ON d.comp_id = stor.comp_id
        AND d.stor_id = stor.stor_id
    LEFT JOIN productos_erp pe
        ON d.item_id = pe.item_id
    WHERE d.is_id IN (
        SELECT s.is_id FROM tb_item_serials s WHERE s.is_serial = :serial
    )
    OR d.rmad_serial = :serial
    OR d."rmad_Manual" = :serial
    ORDER BY h.rmah_cd ASC NULLS LAST, d.rmad_id ASC
""")

QUERY_RMA_HISTORIAL = text("""
    SELECT
        rmadh_id,
        rmadh_cd,
        user_id
    FROM tb_rma_detail_attrib_history
    WHERE comp_id = :comp_id
        AND rmah_id = :rmah_id
        AND rmad_id = :rmad_id
    ORDER BY rmadh_cd ASC NULLS LAST, rmadh_id ASC
""")

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

QUERY_RMA_BY_INVOICE = text("""
    SELECT DISTINCT
        d.rmah_id,
        d.rmad_id,
        d.bra_id,
        d.comp_id,
        d.is_id,
        d.rmad_serial,
        d."rmad_Manual",
        d.item_id,
        d."rmad_originalPrice",
        d.rmad_qty,
        d.stor_id,
        -- Etapas
        d."rmad_Date_Reception",
        d."rmad_ReceptionNote",
        d."rmad_Date_Diagnostic",
        d."rmad_DiagnosticNote",
        d."rmad_Date_Proc",
        d."rmad_ProcNote",
        d."rmad_Date_Delivery",
        d."rmad_DelioveryNote",
        -- Garantía
        d."rmad_insertWarrantyDetail",
        -- Header
        h.rmah_cd,
        h.cust_id,
        h.supp_id,
        h."rmah_isInSuppplier",
        -- Joins
        cust.cust_name AS cliente_nombre,
        supp.supp_name AS proveedor_nombre,
        stor.stor_desc,
        pe.codigo AS item_codigo,
        pe.descripcion AS item_descripcion,
        -- Invoice info
        ct.ct_transaction AS factura_ct_transaction,
        it.it_transaction AS factura_it_transaction
    FROM tb_commercial_transactions ct
    INNER JOIN tb_item_transactions it
        ON ct.ct_transaction = it.ct_transaction
    INNER JOIN tb_rma_detail d
        ON it.it_transaction = d.it_transaction
        AND it.comp_id = d.comp_id
    INNER JOIN tb_rma_header h
        ON d.comp_id = h.comp_id
        AND d.rmah_id = h.rmah_id
        AND d.bra_id = h.bra_id
    LEFT JOIN tb_customer cust
        ON h.comp_id = cust.comp_id
        AND h.cust_id = cust.cust_id
    LEFT JOIN tb_supplier supp
        ON h.comp_id = supp.comp_id
        AND h.supp_id = supp.supp_id
    LEFT JOIN tb_storage stor
        ON d.comp_id = stor.comp_id
        AND d.stor_id = stor.stor_id
    LEFT JOIN productos_erp pe
        ON d.item_id = pe.item_id
    WHERE ct.ct_soh_id = :soh_id
    ORDER BY h.rmah_cd ASC NULLS LAST, d.rmad_id ASC
""")

QUERY_FACTURA = text("""
    SELECT
        ct.ct_transaction,
        ct.comp_id,
        ct.bra_id,
        ct.ct_kindof,
        ct.ct_pointofsale,
        ct.ct_docnumber,
        ct.ct_date,
        ct.ct_total,
        ct.cust_id,
        ct.supp_id,
        ct.ct_soh_id,
        -- Joins
        cust.cust_name AS cliente_nombre,
        supp.supp_name AS proveedor_nombre
    FROM tb_commercial_transactions ct
    LEFT JOIN tb_customer cust
        ON ct.comp_id = cust.comp_id
        AND ct.cust_id = cust.cust_id
    LEFT JOIN tb_supplier supp
        ON ct.comp_id = supp.comp_id
        AND ct.supp_id = supp.supp_id
    WHERE ct.ct_kindof = :kindof
        AND ct.ct_pointofsale = :pointofsale
        AND ct.ct_docnumber = :docnumber
    ORDER BY ct.ct_date DESC NULLS LAST
    LIMIT 1
""")

QUERY_SERIALES_BY_FACTURA = text("""
    SELECT DISTINCT
        s.is_serial
    FROM tb_item_serials s
    WHERE s.ct_transaction = :ct_transaction
        AND s.is_serial IS NOT NULL
        AND s.is_serial != ''
    ORDER BY s.is_serial
""")

QUERY_RMA_BY_CT_TRANSACTION = text("""
    SELECT DISTINCT
        d.rmah_id,
        d.rmad_id,
        d.bra_id,
        d.comp_id,
        d.is_id,
        d.rmad_serial,
        d."rmad_Manual",
        d.item_id,
        d."rmad_originalPrice",
        d.rmad_qty,
        d.stor_id,
        -- Etapas
        d."rmad_Date_Reception",
        d."rmad_ReceptionNote",
        d."rmad_Date_Diagnostic",
        d."rmad_DiagnosticNote",
        d."rmad_Date_Proc",
        d."rmad_ProcNote",
        d."rmad_Date_Delivery",
        d."rmad_DelioveryNote",
        -- Garantía
        d."rmad_insertWarrantyDetail",
        -- Header
        h.rmah_cd,
        h.cust_id,
        h.supp_id,
        h."rmah_isInSuppplier",
        -- Joins
        cust.cust_name AS cliente_nombre,
        supp.supp_name AS proveedor_nombre,
        stor.stor_desc,
        pe.codigo AS item_codigo,
        pe.descripcion AS item_descripcion
    FROM tb_item_transactions it
    INNER JOIN tb_rma_detail d
        ON it.it_transaction = d.it_transaction
        AND it.comp_id = d.comp_id
    INNER JOIN tb_rma_header h
        ON d.comp_id = h.comp_id
        AND d.rmah_id = h.rmah_id
        AND d.bra_id = h.bra_id
    LEFT JOIN tb_customer cust
        ON h.comp_id = cust.comp_id
        AND h.cust_id = cust.cust_id
    LEFT JOIN tb_supplier supp
        ON h.comp_id = supp.comp_id
        AND h.supp_id = supp.supp_id
    LEFT JOIN tb_storage stor
        ON d.comp_id = stor.comp_id
        AND d.stor_id = stor.stor_id
    LEFT JOIN productos_erp pe
        ON d.item_id = pe.item_id
    WHERE it.ct_transaction = :ct_transaction
    ORDER BY h.rmah_cd ASC NULLS LAST, d.rmad_id ASC
""")

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
    WHERE s.is_serial = :serial
    ORDER BY soh.soh_cd ASC NULLS LAST
""")

QUERY_FACTURA_DETALLE = text("""
    SELECT
        it.it_transaction,
        it.item_id,
        ti.item_code,
        COALESCE(pe.descripcion, ti.item_desc) AS item_desc,
        it.it_qty AS cantidad,
        it.it_price AS precio_unitario,
        it.it_pricewithoothers AS precio_sin_otros,
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


# ── Customer traza queries ───────────────────────────────────────

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


# ── Sale order (pedidos) queries ─────────────────────────────────

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


# ── RMA by customer queries ─────────────────────────────────────

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
# HELPERS
# =============================================================================


def determinar_tipo(row: dict) -> str:
    """Determina el tipo de movimiento basado en la transacción comercial"""
    if row.get("supp_id") and row["supp_id"] > 0:
        return "PROVEEDOR"
    if row.get("cust_id") and row["cust_id"] > 0:
        return "CLIENTE"
    # Si no tiene ni cliente ni proveedor, es transferencia interna
    if row.get("ct_transaction"):
        return "TRANSFERENCIA"
    return "DESCONOCIDO"


def construir_nro_documento(row: dict) -> Optional[str]:
    """Construye el número de documento legible (ej: Fc A 0004-462445)"""
    df_desc = row.get("df_desc") or ""
    kind = row.get("ct_kindof") or ""
    pv = row.get("ct_pointofsale")
    doc_number = row.get("ct_docnumber") or ""

    pv_str = str(pv).zfill(4) if pv is not None else ""

    if df_desc:
        # df_desc ya incluye tipo y a veces PV (ej: "01.Fc A 0005")
        if pv_str and doc_number:
            return f"{df_desc}-{doc_number}".strip()
        return f"{df_desc} {doc_number}".strip() or None
    if kind and doc_number:
        prefix = f"{kind} {pv_str}-" if pv_str else f"{kind} "
        return f"{prefix}{doc_number}".strip()
    if doc_number:
        return f"{pv_str}-{doc_number}" if pv_str else doc_number
    return None


def calcular_dias(fecha: object) -> Optional[int]:
    """Calcula días desde la fecha hasta hoy. Acepta datetime, date o string ISO."""
    if not fecha:
        return None
    from datetime import datetime, date

    try:
        if isinstance(fecha, datetime):
            return (date.today() - fecha.date()).days
        if isinstance(fecha, date):
            return (date.today() - fecha).days
        # String fallback
        parsed = datetime.fromisoformat(str(fecha).replace("Z", "+00:00"))
        return (date.today() - parsed.date()).days
    except (ValueError, TypeError):
        return None


# =============================================================================
# BUILDERS (lógica reutilizable entre endpoints)
# =============================================================================


def _build_movimientos(db: Session, serial: str) -> tuple[list[MovimientoSerial], Optional[ArticuloInfo]]:
    """Busca movimientos de un serial y extrae info del artículo."""
    result = db.execute(QUERY_TRAZA, {"serial": serial})
    rows = [dict(row._mapping) for row in result]

    articulo = None
    if rows:
        first = rows[0]
        if first.get("item_id"):
            articulo = ArticuloInfo(
                item_id=first["item_id"],
                codigo=first.get("item_codigo") or "",
                descripcion=first.get("item_descripcion") or "",
                marca=first.get("item_marca"),
                categoria=first.get("item_categoria"),
            )

    movimientos = []
    for row in rows:
        tipo = determinar_tipo(row)
        ref_id = None
        ref_nombre = None

        if tipo == "PROVEEDOR":
            ref_id = row.get("supp_id")
            ref_nombre = row.get("proveedor_nombre")
        elif tipo == "CLIENTE":
            ref_id = row.get("cust_id")
            ref_nombre = row.get("cliente_nombre")

        ct_date = row.get("ct_date")
        is_cd = row.get("is_cd")
        estado = "Disponible" if row.get("is_available") else "No Disponible"

        movimientos.append(
            MovimientoSerial(
                is_id=row["is_id"],
                ct_transaction=row.get("ct_transaction"),
                fecha_documento=str(ct_date) if ct_date else None,
                fecha_seriado=str(is_cd) if is_cd else None,
                tipo=tipo,
                referencia_id=ref_id,
                referencia_nombre=ref_nombre,
                nro_documento=construir_nro_documento(row),
                dias_a_la_fecha=calcular_dias(is_cd or ct_date),
                estado=estado,
                deposito=row.get("stor_desc"),
                deposito_id=row.get("stor_id"),
            )
        )

    return movimientos, articulo


def _build_rma(
    db: Session, serial: str, articulo: Optional[ArticuloInfo] = None
) -> tuple[list[RMASerial], Optional[ArticuloInfo]]:
    """Busca RMAs vinculados a un serial (por is_id, rmad_serial o rmad_Manual)."""
    result_rma = db.execute(QUERY_RMA, {"serial": serial})
    rma_rows = [dict(row._mapping) for row in result_rma]

    rma_list = []
    for row in rma_rows:
        match_por = "is_id"
        if row.get("rmad_serial") == serial:
            match_por = "rmad_serial"
        elif row.get("rmad_Manual") == serial:
            match_por = "rmad_Manual"

        if articulo is None and row.get("item_id"):
            articulo = ArticuloInfo(
                item_id=row["item_id"],
                codigo=row.get("item_codigo") or "",
                descripcion=row.get("item_descripcion") or "",
            )

        historial = []
        if row.get("comp_id") and row.get("rmah_id") and row.get("rmad_id"):
            result_hist = db.execute(
                QUERY_RMA_HISTORIAL,
                {
                    "comp_id": row["comp_id"],
                    "rmah_id": row["rmah_id"],
                    "rmad_id": row["rmad_id"],
                },
            )
            for h in result_hist:
                h_dict = dict(h._mapping)
                fecha_h = h_dict.get("rmadh_cd")
                historial.append(
                    RMAHistorialEstado(
                        rmadh_id=h_dict["rmadh_id"],
                        fecha=str(fecha_h) if fecha_h else None,
                        user_id=h_dict.get("user_id"),
                    )
                )

        fecha_rma = row.get("rmah_cd")
        fecha_rec = row.get("rmad_Date_Reception")
        fecha_diag = row.get("rmad_Date_Diagnostic")
        fecha_proc = row.get("rmad_Date_Proc")
        fecha_ent = row.get("rmad_Date_Delivery")
        precio = row.get("rmad_originalPrice")
        qty = row.get("rmad_qty")

        rma_list.append(
            RMASerial(
                rmah_id=row["rmah_id"],
                rmad_id=row["rmad_id"],
                bra_id=row["bra_id"],
                match_por=match_por,
                fecha_rma=str(fecha_rma) if fecha_rma else None,
                cust_id=row.get("cust_id"),
                cliente=row.get("cliente_nombre"),
                supp_id=row.get("supp_id"),
                proveedor=row.get("proveedor_nombre"),
                en_proveedor=row.get("rmah_isInSuppplier"),
                item_id=row.get("item_id"),
                item_codigo=row.get("item_codigo"),
                item_descripcion=row.get("item_descripcion"),
                rmad_serial=row.get("rmad_serial"),
                rmad_Manual=row.get("rmad_Manual"),
                precio_original=float(precio) if precio else None,
                cantidad=float(qty) if qty else None,
                deposito=row.get("stor_desc"),
                fecha_recepcion=str(fecha_rec) if fecha_rec else None,
                nota_recepcion=row.get("rmad_ReceptionNote"),
                fecha_diagnostico=str(fecha_diag) if fecha_diag else None,
                nota_diagnostico=row.get("rmad_DiagnosticNote"),
                fecha_procesamiento=str(fecha_proc) if fecha_proc else None,
                nota_procesamiento=row.get("rmad_ProcNote"),
                fecha_entrega=str(fecha_ent) if fecha_ent else None,
                nota_entrega=row.get("rmad_DelioveryNote"),
                garantia=row.get("rmad_insertWarrantyDetail"),
                historial=historial,
            )
        )

    return rma_list, articulo


def _build_rma_by_invoice(
    db: Session,
    soh_ids: list[int],
    exclude_rmad_ids: set[tuple[int, int, int]] | None = None,
) -> list[RMASerial]:
    """
    Busca RMAs vinculados a pedidos vía cadena de factura:
    sale_order_header (soh_id) → commercial_transactions (ct_soh_id)
    → item_transactions (ct_transaction) → rma_detail (it_transaction)

    exclude_rmad_ids: set de (comp_id, rmad_id, bra_id) ya encontrados por serial,
    para deduplicar.
    """
    if not soh_ids:
        return []

    if exclude_rmad_ids is None:
        exclude_rmad_ids = set()

    rma_list: list[RMASerial] = []

    for soh_id in soh_ids:
        result = db.execute(QUERY_RMA_BY_INVOICE, {"soh_id": soh_id})
        rows = [dict(row._mapping) for row in result]

        for row in rows:
            # Deduplicar contra los ya encontrados por serial
            rma_key: tuple[int, int, int] = (
                int(row.get("comp_id") or 0),
                int(row["rmad_id"]),
                int(row["bra_id"]),
            )
            if rma_key in exclude_rmad_ids:
                continue
            exclude_rmad_ids.add(rma_key)

            # Historial de atributos
            historial: list[RMAHistorialEstado] = []
            if row.get("comp_id") and row.get("rmah_id") and row.get("rmad_id"):
                result_hist = db.execute(
                    QUERY_RMA_HISTORIAL,
                    {
                        "comp_id": row["comp_id"],
                        "rmah_id": row["rmah_id"],
                        "rmad_id": row["rmad_id"],
                    },
                )
                for h in result_hist:
                    h_dict = dict(h._mapping)
                    fecha_h = h_dict.get("rmadh_cd")
                    historial.append(
                        RMAHistorialEstado(
                            rmadh_id=h_dict["rmadh_id"],
                            fecha=str(fecha_h) if fecha_h else None,
                            user_id=h_dict.get("user_id"),
                        )
                    )

            fecha_rma = row.get("rmah_cd")
            fecha_rec = row.get("rmad_Date_Reception")
            fecha_diag = row.get("rmad_Date_Diagnostic")
            fecha_proc = row.get("rmad_Date_Proc")
            fecha_ent = row.get("rmad_Date_Delivery")
            precio = row.get("rmad_originalPrice")
            qty = row.get("rmad_qty")

            rma_list.append(
                RMASerial(
                    rmah_id=row["rmah_id"],
                    rmad_id=row["rmad_id"],
                    bra_id=row["bra_id"],
                    match_por="it_transaction",
                    fecha_rma=str(fecha_rma) if fecha_rma else None,
                    cust_id=row.get("cust_id"),
                    cliente=row.get("cliente_nombre"),
                    supp_id=row.get("supp_id"),
                    proveedor=row.get("proveedor_nombre"),
                    en_proveedor=row.get("rmah_isInSuppplier"),
                    item_id=row.get("item_id"),
                    item_codigo=row.get("item_codigo"),
                    item_descripcion=row.get("item_descripcion"),
                    rmad_serial=row.get("rmad_serial"),
                    rmad_Manual=row.get("rmad_Manual"),
                    precio_original=float(precio) if precio else None,
                    cantidad=float(qty) if qty else None,
                    deposito=row.get("stor_desc"),
                    fecha_recepcion=str(fecha_rec) if fecha_rec else None,
                    nota_recepcion=row.get("rmad_ReceptionNote"),
                    fecha_diagnostico=str(fecha_diag) if fecha_diag else None,
                    nota_diagnostico=row.get("rmad_DiagnosticNote"),
                    fecha_procesamiento=str(fecha_proc) if fecha_proc else None,
                    nota_procesamiento=row.get("rmad_ProcNote"),
                    fecha_entrega=str(fecha_ent) if fecha_ent else None,
                    nota_entrega=row.get("rmad_DelioveryNote"),
                    garantia=row.get("rmad_insertWarrantyDetail"),
                    historial=historial,
                )
            )

    return rma_list


def _build_rma_by_ct_transaction(
    db: Session,
    ct_transaction: int,
    exclude_rmad_ids: set[tuple[int, int, int]] | None = None,
) -> list[RMASerial]:
    """
    Busca RMAs vinculados a una factura vía cadena:
    commercial_transactions (ct_transaction) → item_transactions → rma_detail (it_transaction)

    exclude_rmad_ids: set de (comp_id, rmad_id, bra_id) ya encontrados por serial,
    para deduplicar.
    """
    if exclude_rmad_ids is None:
        exclude_rmad_ids = set()

    rma_list: list[RMASerial] = []
    result = db.execute(QUERY_RMA_BY_CT_TRANSACTION, {"ct_transaction": ct_transaction})
    rows = [dict(row._mapping) for row in result]

    for row in rows:
        rma_key: tuple[int, int, int] = (
            int(row.get("comp_id") or 0),
            int(row["rmad_id"]),
            int(row["bra_id"]),
        )
        if rma_key in exclude_rmad_ids:
            continue
        exclude_rmad_ids.add(rma_key)

        historial: list[RMAHistorialEstado] = []
        if row.get("comp_id") and row.get("rmah_id") and row.get("rmad_id"):
            result_hist = db.execute(
                QUERY_RMA_HISTORIAL,
                {
                    "comp_id": row["comp_id"],
                    "rmah_id": row["rmah_id"],
                    "rmad_id": row["rmad_id"],
                },
            )
            for h in result_hist:
                h_dict = dict(h._mapping)
                fecha_h = h_dict.get("rmadh_cd")
                historial.append(
                    RMAHistorialEstado(
                        rmadh_id=h_dict["rmadh_id"],
                        fecha=str(fecha_h) if fecha_h else None,
                        user_id=h_dict.get("user_id"),
                    )
                )

        fecha_rma = row.get("rmah_cd")
        fecha_rec = row.get("rmad_Date_Reception")
        fecha_diag = row.get("rmad_Date_Diagnostic")
        fecha_proc = row.get("rmad_Date_Proc")
        fecha_ent = row.get("rmad_Date_Delivery")
        precio = row.get("rmad_originalPrice")
        qty = row.get("rmad_qty")

        rma_list.append(
            RMASerial(
                rmah_id=row["rmah_id"],
                rmad_id=row["rmad_id"],
                bra_id=row["bra_id"],
                match_por="it_transaction",
                fecha_rma=str(fecha_rma) if fecha_rma else None,
                cust_id=row.get("cust_id"),
                cliente=row.get("cliente_nombre"),
                supp_id=row.get("supp_id"),
                proveedor=row.get("proveedor_nombre"),
                en_proveedor=row.get("rmah_isInSuppplier"),
                item_id=row.get("item_id"),
                item_codigo=row.get("item_codigo"),
                item_descripcion=row.get("item_descripcion"),
                rmad_serial=row.get("rmad_serial"),
                rmad_Manual=row.get("rmad_Manual"),
                precio_original=float(precio) if precio else None,
                cantidad=float(qty) if qty else None,
                deposito=row.get("stor_desc"),
                fecha_recepcion=str(fecha_rec) if fecha_rec else None,
                nota_recepcion=row.get("rmad_ReceptionNote"),
                fecha_diagnostico=str(fecha_diag) if fecha_diag else None,
                nota_diagnostico=row.get("rmad_DiagnosticNote"),
                fecha_procesamiento=str(fecha_proc) if fecha_proc else None,
                nota_procesamiento=row.get("rmad_ProcNote"),
                fecha_entrega=str(fecha_ent) if fecha_ent else None,
                nota_entrega=row.get("rmad_DelioveryNote"),
                garantia=row.get("rmad_insertWarrantyDetail"),
                historial=historial,
            )
        )

    return rma_list


# =============================================================================
# CUSTOMER TRAZA BUILDERS
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


@router.get(
    "/traza/factura-detalle/{ct_transaction}",
    response_model=FacturaDetalleResponse,
)
def traza_factura_detalle(
    ct_transaction: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FacturaDetalleResponse:
    """
    Devuelve las líneas de producto (item transactions) de una transacción comercial.
    Usado para expandir el detalle de un movimiento en la traza de seriales.
    """
    result = db.execute(QUERY_FACTURA_DETALLE, {"ct_transaction": ct_transaction})
    rows = [dict(row._mapping) for row in result]

    items = []
    for row in rows:
        qty = row.get("cantidad")
        precio = row.get("precio_unitario")
        precio_sin = row.get("precio_sin_otros")
        descuento = row.get("descuento_total")
        items.append(
            FacturaDetalleItem(
                it_transaction=row["it_transaction"],
                item_id=row.get("item_id"),
                item_code=row.get("item_code"),
                item_desc=row.get("item_desc"),
                cantidad=float(qty) if qty is not None else None,
                precio_unitario=float(precio) if precio is not None else None,
                precio_sin_otros=float(precio_sin) if precio_sin is not None else None,
                descuento_total=float(descuento) if descuento is not None else None,
                cancelled=bool(row.get("cancelled", False)),
            )
        )

    return FacturaDetalleResponse(ct_transaction=ct_transaction, items=items)


@router.get("/traza/factura", response_model=TrazaFacturaResponse)
def traza_factura(
    tipo: str,
    punto_venta: int,
    nro_documento: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaFacturaResponse:
    """
    Obtiene la traza completa a partir de un número de factura.
    Parámetros: tipo (letra A/B/C), punto_venta (0004), nro_documento.
    El punto de venta identifica unívocamente la sucursal.
    Busca seriales y RMAs vinculados a la factura, con y sin serial.
    """
    # 1. Buscar la factura
    result = db.execute(
        QUERY_FACTURA,
        {
            "kindof": tipo.upper().strip(),
            "pointofsale": punto_venta,
            "docnumber": nro_documento.strip(),
        },
    )
    factura_row = result.fetchone()

    if not factura_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"No se encontró la factura: {tipo} {str(punto_venta).zfill(4)}-{nro_documento}"),
        )

    frow = dict(factura_row._mapping)
    ct_date = frow.get("ct_date")
    ct_total = frow.get("ct_total")

    factura = FacturaInfo(
        ct_transaction=frow["ct_transaction"],
        bra_id=frow["bra_id"],
        tipo=frow.get("ct_kindof") or tipo,
        punto_venta=frow.get("ct_pointofsale") or punto_venta,
        nro_documento=frow.get("ct_docnumber") or nro_documento,
        fecha=str(ct_date) if ct_date else None,
        total=float(ct_total) if ct_total else None,
        cust_id=frow.get("cust_id"),
        cliente=frow.get("cliente_nombre"),
        supp_id=frow.get("supp_id"),
        proveedor=frow.get("proveedor_nombre"),
        soh_id=frow.get("ct_soh_id"),
    )

    # 2. Buscar seriales vinculados a esta factura
    result_seriales = db.execute(
        QUERY_SERIALES_BY_FACTURA,
        {"ct_transaction": frow["ct_transaction"]},
    )

    seriales_vistos: set[str] = set()
    seriales_list: list[TrazaMLSerialItem] = []
    rma_ids_por_serial: set[tuple[int, int, int]] = set()
    all_rma_por_serial: list[RMASerial] = []

    for serial_row in result_seriales:
        serial = dict(serial_row._mapping)["is_serial"]
        if serial in seriales_vistos:
            continue
        seriales_vistos.add(serial)

        movimientos, articulo = _build_movimientos(db, serial)
        rma_list, articulo = _build_rma(db, serial, articulo)

        # Trackear RMAs por serial para deduplicar
        factura_comp_id: int = frow.get("comp_id") or 0
        for rma in rma_list:
            rma_ids_por_serial.add((factura_comp_id, rma.rmad_id, rma.bra_id))

        all_rma_por_serial.extend(rma_list)

        seriales_list.append(
            TrazaMLSerialItem(
                serial=serial,
                articulo=articulo,
                movimientos=movimientos,
                rma=rma_list,
            )
        )

    # 3. Buscar RMAs vía línea de factura (para productos sin serial)
    # Cadena: ct_transaction → item_transactions → rma_detail (it_transaction)
    rma_por_factura = _build_rma_by_ct_transaction(db, frow["ct_transaction"], exclude_rmad_ids=rma_ids_por_serial)

    return TrazaFacturaResponse(
        factura=factura,
        seriales=seriales_list,
        rma_por_serial=all_rma_por_serial,
        rma_por_factura=rma_por_factura,
    )


# =============================================================================
# CLAIMS ML — 4-step lookup with local cache:
#   1. Local DB (rma_claims_ml) → cached data, instant
#   2. Webhook DB (ml_previews) → enriched extra_data from webhook service
#   3. Webhook DB (ml_previews) → raw extra_data → enrich via HTTP
#   4. ML API search → for claims that never arrived as webhooks
#
# ALL enriched data is saved to rma_claims_ml after fetching.
# =============================================================================

# Fallback stale threshold: only used when ml_previews DB is unavailable.
# Normally, staleness is determined by comparing ml_previews.last_updated
# against rma_claims_ml.updated_at (webhook-driven invalidation).
_CACHE_STALE_HOURS_FALLBACK = 24


def _build_claim_from_db_cache(row: RmaClaimML) -> ClaimML:
    """Build ClaimML from a locally cached RmaClaimML record."""
    # Rebuild sub-models from JSONB
    expected_res_detail = None
    if row.expected_resolutions_detail:
        expected_res_detail = [
            ClaimExpectedResolution(
                player_role=r.get("player_role"),
                expected_resolution=r.get("expected_resolution"),
                status=r.get("status"),
                details=r.get("details"),
                date_created=r.get("date_created"),
                last_updated=r.get("last_updated"),
            )
            for r in row.expected_resolutions_detail
        ]

    claim_return = None
    if row.return_data:
        rd = row.return_data
        shipments = [
            ClaimReturnShipment(
                shipment_id=s.get("shipment_id"),
                status=s.get("status"),
                tracking_number=s.get("tracking_number"),
                destination_name=s.get("destination_name"),
                shipment_type=s.get("shipment_type"),
            )
            for s in (rd.get("shipments") or [])
        ]
        claim_return = ClaimReturn(
            return_id=rd.get("return_id"),
            status=rd.get("status"),
            subtype=rd.get("subtype"),
            status_money=rd.get("status_money"),
            refund_at=rd.get("refund_at"),
            shipments=shipments,
            date_created=rd.get("date_created"),
            date_closed=rd.get("date_closed"),
        )

    claim_change = None
    if row.change_data:
        cd = row.change_data
        claim_change = ClaimChange(
            change_type=cd.get("change_type"),
            status=cd.get("status"),
            status_detail=cd.get("status_detail"),
            new_order_ids=cd.get("new_order_ids"),
            date_created=cd.get("date_created"),
            last_updated=cd.get("last_updated"),
        )

    return ClaimML(
        claim_id=str(row.claim_id),
        claim_type=row.claim_type,
        claim_stage=row.claim_stage,
        status=row.status,
        reason_id=row.reason_id,
        reason_category=row.reason_category,
        reason_detail=row.reason_detail or row.reason_name,
        triage_tags=row.triage_tags,
        expected_resolutions=row.expected_resolutions,
        fulfilled=row.fulfilled,
        quantity_type=row.quantity_type,
        claimed_quantity=row.claimed_quantity,
        seller_actions=row.seller_actions,
        mandatory_actions=row.mandatory_actions,
        nearest_due_date=row.nearest_due_date,
        action_responsible=row.action_responsible,
        detail_title=row.detail_title,
        detail_description=row.detail_description,
        detail_problem=row.detail_problem,
        resolution_reason=row.resolution_reason,
        resolution_closed_by=row.resolution_closed_by,
        resolution_coverage=row.resolution_coverage,
        related_entities=row.related_entities,
        expected_resolutions_detail=expected_res_detail,
        claim_return=claim_return,
        claim_change=claim_change,
        messages_total=row.messages_total,
        affects_reputation=row.affects_reputation,
        has_incentive=row.has_incentive,
        date_created=row.ml_date_created,
        last_updated=row.ml_last_updated,
        resource_id=str(row.resource_id) if row.resource_id else None,
    )


def _is_cache_stale_by_time(row: RmaClaimML) -> bool:
    """
    Fallback staleness check (time-based). Only used when ml_previews
    DB is unavailable. Normally we compare against ml_previews.last_updated.
    """
    if row.status == "closed":
        return False
    if not row.updated_at:
        return True
    now = datetime.now(timezone.utc)
    updated = row.updated_at.replace(tzinfo=timezone.utc) if row.updated_at.tzinfo is None else row.updated_at
    return (now - updated).total_seconds() > _CACHE_STALE_HOURS_FALLBACK * 3600


def _build_claim_from_enriched_extra(
    ed: dict, status_override: Optional[str] = None, title_fallback: Optional[str] = None
) -> ClaimML:
    """Build ClaimML from extra_data that was enriched by the webhook service."""
    return ClaimML(
        claim_id=str(ed.get("claim_id", "")),
        claim_type=ed.get("claim_type"),
        claim_stage=ed.get("claim_stage"),
        status=status_override or ed.get("status"),
        reason_id=ed.get("reason_id"),
        reason_category=ed.get("reason_category"),
        reason_detail=ed.get("reason_detail") or title_fallback,
        triage_tags=ed.get("triage_tags"),
        expected_resolutions=ed.get("expected_resolutions"),
        fulfilled=ed.get("fulfilled"),
        quantity_type=ed.get("quantity_type"),
        claimed_quantity=ed.get("claimed_quantity"),
        seller_actions=ed.get("seller_actions"),
        mandatory_actions=ed.get("mandatory_actions"),
        nearest_due_date=ed.get("nearest_due_date"),
        action_responsible=ed.get("action_responsible"),
        detail_title=ed.get("detail_title"),
        detail_problem=ed.get("detail_problem"),
        resolution_reason=ed.get("resolution_reason"),
        resolution_closed_by=ed.get("resolution_closed_by"),
        resolution_coverage=ed.get("resolution_coverage"),
        date_created=ed.get("date_created"),
        last_updated=ed.get("last_updated"),
        resource_id=str(ed.get("resource_id", "")),
    )


def _build_claim_from_ml_api(
    claim_data: dict,
    detail_data: Optional[dict] = None,
    reason_data: Optional[dict] = None,
    expected_res_data: Optional[list] = None,
    return_data: Optional[dict] = None,
    change_data: Optional[dict] = None,
    messages_data: Optional[dict] = None,
    affects_rep_data: Optional[dict] = None,
) -> ClaimML:
    """
    Build ClaimML from raw ML API data (up to 7+ endpoints combined).
    - claim_data: from /claims/{id}
    - detail_data: from /claims/{id}/detail
    - reason_data: from /claims/reasons/{reason_id}
    - expected_res_data: from /claims/{id}/expected-resolutions
    - return_data: from /v2/claims/{id}/returns
    - change_data: from /v1/claims/{id}/changes
    - messages_data: from /claims/{id}/messages
    - affects_rep_data: from /claims/{id}/affects-reputation
    """
    # Extract players info
    seller_actions: list[str] = []
    mandatory_actions: list[str] = []
    nearest_due_date: Optional[str] = None
    for player in claim_data.get("players") or []:
        if player.get("role") == "respondent":
            for action in player.get("available_actions") or []:
                action_name = action.get("action")
                if action_name:
                    seller_actions.append(action_name)
                if action.get("mandatory"):
                    if action_name:
                        mandatory_actions.append(action_name)
                    if action.get("due_date") and not nearest_due_date:
                        nearest_due_date = action["due_date"]

    # Resolution
    resolution = claim_data.get("resolution") or {}

    # Reason details (from /reasons/{id} endpoint)
    reason_settings = (reason_data or {}).get("settings") or {}
    triage_tags = reason_settings.get("rules_engine_triage")
    expected_resolutions = reason_settings.get("expected_resolutions")
    reason_detail = (reason_data or {}).get("detail")
    reason_name = (reason_data or {}).get("name")

    # Detail (from /claims/{id}/detail endpoint)
    det = detail_data or {}

    # Related entities — ML returns either ["return", "change"] or
    # [{"entity_type": "return", "entity_id": 123}] depending on the endpoint
    related_entities: Optional[list[str]] = None
    raw_related = claim_data.get("related_entities") or []
    if raw_related:
        parsed: list[str] = []
        for e in raw_related:
            if isinstance(e, str):
                parsed.append(e)
            elif isinstance(e, dict) and e.get("entity_type"):
                parsed.append(e["entity_type"])
        related_entities = parsed or None

    # Expected resolutions detail (from /expected-resolutions endpoint)
    exp_res_detail: Optional[list[ClaimExpectedResolution]] = None
    if expected_res_data:
        exp_res_detail = [
            ClaimExpectedResolution(
                player_role=r.get("player_role"),
                expected_resolution=r.get("expected_resolution"),
                status=r.get("status"),
                details=r.get("details"),
                date_created=r.get("date_created"),
                last_updated=r.get("last_updated"),
            )
            for r in expected_res_data
        ]

    # Return (from /v2/claims/{id}/returns endpoint)
    claim_return: Optional[ClaimReturn] = None
    if return_data and return_data.get("id"):
        shipments = [
            ClaimReturnShipment(
                shipment_id=s.get("id"),
                status=s.get("status"),
                tracking_number=s.get("tracking_number"),
                destination_name=s.get("destination", {}).get("name")
                if isinstance(s.get("destination"), dict)
                else s.get("destination_name"),
                shipment_type=s.get("type"),
            )
            for s in (return_data.get("shipments") or [])
        ]
        claim_return = ClaimReturn(
            return_id=return_data.get("id"),
            status=return_data.get("status"),
            subtype=return_data.get("subtype"),
            status_money=return_data.get("status_money"),
            refund_at=return_data.get("refund_at"),
            shipments=shipments,
            date_created=return_data.get("date_created"),
            date_closed=return_data.get("date_closed"),
        )

    # Change (from /v1/claims/{id}/changes endpoint)
    claim_change: Optional[ClaimChange] = None
    if change_data and (change_data.get("change_type") or change_data.get("status")):
        new_order_ids = None
        if change_data.get("new_items"):
            new_order_ids = [item.get("order_id") for item in change_data["new_items"] if item.get("order_id")]
        claim_change = ClaimChange(
            change_type=change_data.get("change_type"),
            status=change_data.get("status"),
            status_detail=change_data.get("status_detail"),
            new_order_ids=new_order_ids,
            date_created=change_data.get("date_created"),
            last_updated=change_data.get("last_updated"),
        )

    # Messages count (from /messages endpoint)
    # NOTE: ML may return a list directly OR a dict with {paging, data}.
    messages_total: Optional[int] = None
    if messages_data is not None:
        if isinstance(messages_data, list):
            messages_total = len(messages_data)
        else:
            paging = messages_data.get("paging") or {}
            messages_total = paging.get("total")
            if messages_total is None:
                messages_total = len(messages_data.get("data") or [])

    # Affects reputation (from /affects-reputation endpoint)
    # NOTE: ML may return bool (True/False) OR string ("affected"/"not_affected").
    affects_reputation: Optional[bool] = None
    has_incentive: Optional[bool] = None
    if affects_rep_data is not None:
        raw_ar = affects_rep_data.get("affects_reputation")
        if isinstance(raw_ar, bool):
            affects_reputation = raw_ar
        elif isinstance(raw_ar, str):
            affects_reputation = raw_ar.lower() in ("affected", "true")
        raw_hi = affects_rep_data.get("has_incentive")
        if isinstance(raw_hi, bool):
            has_incentive = raw_hi
        elif isinstance(raw_hi, str):
            has_incentive = raw_hi.lower() in ("true", "yes")
        # else: remains None

    return ClaimML(
        claim_id=str(claim_data.get("id", "")),
        claim_type=claim_data.get("type"),
        claim_stage=claim_data.get("stage"),
        status=claim_data.get("status"),
        reason_id=claim_data.get("reason_id"),
        reason_category=(claim_data.get("reason_id") or "")[:3] or None,
        reason_detail=reason_detail or det.get("problem") or reason_name,
        triage_tags=triage_tags,
        expected_resolutions=expected_resolutions,
        fulfilled=claim_data.get("fulfilled"),
        quantity_type=claim_data.get("quantity_type"),
        claimed_quantity=claim_data.get("claimed_quantity"),
        seller_actions=seller_actions or None,
        mandatory_actions=mandatory_actions or None,
        nearest_due_date=nearest_due_date or det.get("due_date"),
        action_responsible=det.get("action_responsible"),
        detail_title=det.get("title"),
        detail_description=det.get("description"),
        detail_problem=det.get("problem"),
        resolution_reason=resolution.get("reason"),
        resolution_closed_by=resolution.get("closed_by"),
        resolution_coverage=resolution.get("applied_coverage"),
        related_entities=related_entities,
        expected_resolutions_detail=exp_res_detail,
        claim_return=claim_return,
        claim_change=claim_change,
        messages_total=messages_total,
        affects_reputation=affects_reputation,
        has_incentive=has_incentive,
        date_created=claim_data.get("date_created"),
        last_updated=claim_data.get("last_updated"),
        resource_id=str(claim_data.get("resource_id", "")),
    )


def _fetch_all_ml_endpoints(
    client: httpx.Client, claim_id: str, claim_data: dict
) -> tuple[
    Optional[dict],  # detail_data
    Optional[dict],  # reason_data
    Optional[list],  # expected_res_data
    Optional[dict],  # return_data
    Optional[dict],  # change_data
    Optional[dict],  # messages_data
    Optional[dict],  # affects_rep_data
]:
    """
    Fetch all secondary ML endpoints for a claim. Each call is
    wrapped in try/except so one failure doesn't block the rest.
    """
    detail_data = None
    reason_data = None
    expected_res_data = None
    return_data = None
    change_data = None
    messages_data = None
    affects_rep_data = None

    # 1. /claims/{id}/detail
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={"resource": f"/post-purchase/v1/claims/{claim_id}/detail", "format": "json"},
        )
        if r.status_code == 200:
            detail_data = r.json()
    except Exception:
        pass

    # 2. /claims/reasons/{reason_id}
    reason_id = claim_data.get("reason_id")
    if reason_id:
        try:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": f"/post-purchase/v1/claims/reasons/{reason_id}", "format": "json"},
            )
            if r.status_code == 200:
                reason_data = r.json()
        except Exception:
            pass

    # 3. /claims/{id}/expected-resolutions
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={"resource": f"/post-purchase/v1/claims/{claim_id}/expected-resolutions", "format": "json"},
        )
        if r.status_code == 200:
            data = r.json()
            # API returns array or object with data key
            if isinstance(data, list):
                expected_res_data = data
            elif isinstance(data, dict) and "data" in data:
                expected_res_data = data["data"]
    except Exception:
        pass

    # 4. /v2/claims/{id}/returns (only if related_entities indicates return)
    related = claim_data.get("related_entities") or []
    has_return = any((e == "return" if isinstance(e, str) else e.get("entity_type") == "return") for e in related)
    if has_return:
        try:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": f"/post-purchase/v2/claims/{claim_id}/returns", "format": "json"},
            )
            if r.status_code == 200:
                return_data = r.json()
        except Exception:
            pass

    # 5. /v1/claims/{id}/changes (only if related_entities indicates change)
    has_change = any((e == "change" if isinstance(e, str) else e.get("entity_type") == "change") for e in related)
    if has_change:
        try:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": f"/post-purchase/v1/claims/{claim_id}/changes", "format": "json"},
            )
            if r.status_code == 200:
                change_data = r.json()
        except Exception:
            pass

    # 6. /claims/{id}/messages (fetch all — cached in rma_claims_ml_messages)
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={
                "resource": f"/post-purchase/v1/claims/{claim_id}/messages",
                "format": "json",
            },
        )
        if r.status_code == 200:
            messages_data = r.json()
    except Exception:
        pass

    # 7. /claims/{id}/affects-reputation
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={"resource": f"/post-purchase/v1/claims/{claim_id}/affects-reputation", "format": "json"},
        )
        if r.status_code == 200:
            affects_rep_data = r.json()
    except Exception:
        pass

    return (
        detail_data,
        reason_data,
        expected_res_data,
        return_data,
        change_data,
        messages_data,
        affects_rep_data,
    )


def _save_claim_to_cache(
    claim: ClaimML,
    raw_claim: Optional[dict] = None,
    raw_detail: Optional[dict] = None,
    raw_reason: Optional[dict] = None,
    return_data: Optional[dict] = None,
    change_data: Optional[dict] = None,
    expected_res_data: Optional[list] = None,
    messages_data: Optional[dict] = None,
    affects_rep_data: Optional[dict] = None,
) -> None:
    """
    Upsert a ClaimML + raw data into the rma_claims_ml local cache table.
    Uses a separate session so it doesn't interfere with the request's session.
    """
    try:
        session = SessionLocal()
        try:
            claim_id_int = int(claim.claim_id) if claim.claim_id else None
            if not claim_id_int:
                return

            existing = session.query(RmaClaimML).filter(RmaClaimML.claim_id == claim_id_int).first()

            # Build return_data JSONB for storage
            return_jsonb = None
            if claim.claim_return:
                cr = claim.claim_return
                return_jsonb = {
                    "return_id": cr.return_id,
                    "status": cr.status,
                    "subtype": cr.subtype,
                    "status_money": cr.status_money,
                    "refund_at": cr.refund_at,
                    "shipments": [
                        {
                            "shipment_id": s.shipment_id,
                            "status": s.status,
                            "tracking_number": s.tracking_number,
                            "destination_name": s.destination_name,
                            "shipment_type": s.shipment_type,
                        }
                        for s in (cr.shipments or [])
                    ],
                    "date_created": cr.date_created,
                    "date_closed": cr.date_closed,
                }

            # Build change_data JSONB
            change_jsonb = None
            if claim.claim_change:
                cc = claim.claim_change
                change_jsonb = {
                    "change_type": cc.change_type,
                    "status": cc.status,
                    "status_detail": cc.status_detail,
                    "new_order_ids": cc.new_order_ids,
                    "date_created": cc.date_created,
                    "last_updated": cc.last_updated,
                }

            # Build expected_resolutions_detail JSONB
            exp_res_jsonb = None
            if claim.expected_resolutions_detail:
                exp_res_jsonb = [
                    {
                        "player_role": r.player_role,
                        "expected_resolution": r.expected_resolution,
                        "status": r.status,
                        "details": r.details,
                        "date_created": r.date_created,
                        "last_updated": r.last_updated,
                    }
                    for r in claim.expected_resolutions_detail
                ]

            values = {
                "resource_id": int(claim.resource_id) if claim.resource_id and claim.resource_id.isdigit() else None,
                "claim_type": claim.claim_type,
                "claim_stage": claim.claim_stage,
                "status": claim.status,
                "reason_id": claim.reason_id,
                "reason_category": claim.reason_category,
                "reason_detail": claim.reason_detail,
                "reason_name": claim.reason_detail,
                "triage_tags": claim.triage_tags,
                "expected_resolutions": claim.expected_resolutions,
                "detail_title": claim.detail_title,
                "detail_description": claim.detail_description,
                "detail_problem": claim.detail_problem,
                "fulfilled": claim.fulfilled,
                "quantity_type": claim.quantity_type,
                "claimed_quantity": claim.claimed_quantity,
                "seller_actions": claim.seller_actions,
                "mandatory_actions": claim.mandatory_actions,
                "nearest_due_date": claim.nearest_due_date,
                "action_responsible": claim.action_responsible,
                "resolution_reason": claim.resolution_reason,
                "resolution_closed_by": claim.resolution_closed_by,
                "resolution_coverage": claim.resolution_coverage,
                "related_entities": claim.related_entities,
                "expected_resolutions_detail": exp_res_jsonb,
                "return_data": return_jsonb,
                "change_data": change_jsonb,
                "messages_total": claim.messages_total,
                "affects_reputation": claim.affects_reputation,
                "has_incentive": claim.has_incentive,
                "ml_date_created": claim.date_created,
                "ml_last_updated": claim.last_updated,
                "raw_claim": raw_claim,
                "raw_detail": raw_detail,
                "raw_reason": raw_reason,
            }

            if existing:
                for key, val in values.items():
                    setattr(existing, key, val)
            else:
                row = RmaClaimML(claim_id=claim_id_int, **values)
                session.add(row)

            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Failed to save claim %s to cache", claim.claim_id, exc_info=True)
        finally:
            session.close()
    except Exception:
        logger.warning("Failed to create session for claim cache", exc_info=True)


def _save_messages_to_cache(claim_id: str, messages_data: Optional[dict | list]) -> None:
    """
    Save messages from /claims/{id}/messages into rma_claims_ml_messages.
    Only saves messages not already in the DB (by claim_id + ml_date_created).
    ML may return a list directly OR a dict with {paging, data}.
    """
    if not messages_data:
        return
    if isinstance(messages_data, list):
        messages = messages_data
    else:
        messages = messages_data.get("data") or []
    if not messages:
        return

    try:
        claim_id_int = int(claim_id)
        session = SessionLocal()
        try:
            # Get existing message dates to avoid duplicates
            existing_dates = {
                row.ml_date_created
                for row in session.query(RmaClaimMLMessage.ml_date_created)
                .filter(RmaClaimMLMessage.claim_id == claim_id_int)
                .all()
            }

            for msg in messages:
                msg_date = msg.get("date_created")
                if msg_date in existing_dates:
                    continue

                row = RmaClaimMLMessage(
                    claim_id=claim_id_int,
                    sender_role=msg.get("sender_role"),
                    receiver_role=msg.get("receiver_role"),
                    message=msg.get("message"),
                    status=msg.get("status"),
                    stage=msg.get("stage"),
                    attachments=msg.get("attachments"),
                    message_moderation=msg.get("message_moderation"),
                    date_read=msg.get("date_read"),
                    ml_date_created=msg_date,
                )
                session.add(row)

            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Failed to save messages for claim %s", claim_id, exc_info=True)
        finally:
            session.close()
    except Exception:
        logger.warning("Failed to create session for messages cache", exc_info=True)


def _enrich_claim_via_http(claim_id: str) -> Optional[ClaimML]:
    """
    Enrich a single claim by calling 7+ ML API endpoints via webhook proxy.
    Saves ALL data to rma_claims_ml cache after fetching.
    Returns ClaimML or None if the base API call fails.
    """
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            # 1. Claim base data (required — if this fails, abort)
            r1 = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={
                    "resource": f"/post-purchase/v1/claims/{claim_id}",
                    "format": "json",
                },
            )
            if r1.status_code != 200:
                logger.warning("[claims] Base claim %s returned status %s", claim_id, r1.status_code)
                return None
            claim_data = r1.json()
            logger.info("[claims] Fetched base claim %s (status=%s)", claim_id, claim_data.get("status"))

            # 2-7. All secondary endpoints
            (
                detail_data,
                reason_data,
                expected_res_data,
                return_data,
                change_data,
                messages_data,
                affects_rep_data,
            ) = _fetch_all_ml_endpoints(client, claim_id, claim_data)

            # Build the ClaimML schema
            claim = _build_claim_from_ml_api(
                claim_data,
                detail_data=detail_data,
                reason_data=reason_data,
                expected_res_data=expected_res_data,
                return_data=return_data,
                change_data=change_data,
                messages_data=messages_data,
                affects_rep_data=affects_rep_data,
            )
            logger.info("[claims] Built ClaimML %s OK", claim_id)

            # Save to local cache (fire-and-forget: uses its own session)
            _save_claim_to_cache(
                claim,
                raw_claim=claim_data,
                raw_detail=detail_data,
                raw_reason=reason_data,
                return_data=return_data,
                change_data=change_data,
                expected_res_data=expected_res_data,
                messages_data=messages_data,
                affects_rep_data=affects_rep_data,
            )

            # Save messages to cache (only if we got messages)
            if messages_data:
                has_messages = (isinstance(messages_data, list) and len(messages_data) > 0) or (
                    isinstance(messages_data, dict) and messages_data.get("data")
                )
                if has_messages:
                    _save_messages_to_cache(claim_id, messages_data)

            return claim
    except Exception:
        logger.warning("[claims] EXCEPTION enriching claim %s", claim_id, exc_info=True)
        return None


def _search_claims_via_api(order_ids: list[str], exclude_claim_ids: set[str]) -> list[ClaimML]:
    """
    Search for claims via ML API (through webhook proxy) by order_id.
    Skips claims already found in the DB (by claim_id).
    Returns list of ClaimML.
    """
    claims: list[ClaimML] = []
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            for order_id in order_ids:
                try:
                    r = client.get(
                        ML_WEBHOOK_RENDER_URL,
                        params={
                            "resource": f"/post-purchase/v1/claims/search?order_id={order_id}",
                            "format": "json",
                        },
                    )
                    if r.status_code != 200:
                        continue
                    search_data = r.json()
                    for claim_data in search_data.get("data") or []:
                        cid = str(claim_data.get("id", ""))
                        if cid in exclude_claim_ids:
                            continue
                        exclude_claim_ids.add(cid)
                        # Enrich with ALL endpoints (saves to cache internally)
                        enriched = _enrich_claim_via_http(cid)
                        if enriched:
                            claims.append(enriched)
                except Exception:
                    logger.debug(
                        "Failed to search claims for order %s",
                        order_id,
                        exc_info=True,
                    )
                    continue
    except Exception:
        logger.warning("Failed to create HTTP client for claims search", exc_info=True)
    return claims


def _fetch_claims_by_order_ids(order_ids: list[str]) -> list[ClaimML]:
    """
    Busca claims de MercadoLibre por order IDs con invalidación por webhook.

    Flujo:
    1. Cargar cache local (rma_claims_ml) → indexar por claim_id
    2. Consultar webhook DB (ml_previews) → para cada claim:
       a. Si NO está en cache → enriquecer vía HTTP y guardar
       b. Si está en cache pero ml_previews.last_updated > cache.updated_at
          → el webhook recibió un cambio → re-enriquecer vía HTTP
       c. Si está en cache y es más reciente que ml_previews → usar cache
    3. Claims en cache que NO aparecieron en ml_previews:
       - Cerrados → usar cache (nunca cambian)
       - Abiertos → fallback por tiempo (24hs) en caso de que la webhook DB
         no tenga el registro (raro pero posible)
    4. Search ML API → para claims que no están en ninguna DB

    Silencioso: si algún paso falla, continúa con el siguiente.
    """
    if not order_ids:
        return []

    logger.info("[claims] _fetch_claims_by_order_ids called with order_ids=%s", order_ids)

    claims: list[ClaimML] = []
    seen_claim_ids: set[str] = set()
    # Cache rows indexed by claim_id (str) for comparison in Step 2
    cache_by_claim_id: dict[str, RmaClaimML] = {}
    # Track which cached claims were checked against ml_previews
    cache_checked_via_webhook: set[str] = set()

    # ── Step 1: Load local cache (rma_claims_ml) ────────────────────────────
    try:
        session = SessionLocal()
        try:
            order_id_ints = []
            for oid in order_ids:
                try:
                    order_id_ints.append(int(oid))
                except (ValueError, TypeError):
                    continue

            if order_id_ints:
                cached_rows = session.query(RmaClaimML).filter(RmaClaimML.resource_id.in_(order_id_ints)).all()
                for row in cached_rows:
                    cid = str(row.claim_id)
                    cache_by_claim_id[cid] = row
        except Exception:
            logger.warning("Failed to read claims from local cache", exc_info=True)
        finally:
            session.close()
    except Exception:
        logger.warning("Failed to create session for claims cache read", exc_info=True)

    # ── Step 2: Webhook DB (ml_previews) — invalidation source ──────────────
    webhook_db_available = False
    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        p.resource,
                        p.status,
                        p.title,
                        p.extra_data,
                        p.last_updated
                    FROM ml_previews p
                    WHERE p.resource LIKE '/post-purchase/v1/claims/%'
                      AND p.resource NOT LIKE '%/detail'
                      AND p.resource NOT LIKE '%/reasons/%'
                      AND p.resource NOT LIKE '%/search%'
                      AND p.resource NOT LIKE '%/actions-history'
                      AND p.resource NOT LIKE '%/status-history'
                      AND (p.extra_data->>'resource_id')::text = ANY(:order_ids)
                    ORDER BY p.last_updated DESC
                """),
                {"order_ids": order_ids},
            ).fetchall()

        webhook_db_available = True

        for row in rows:
            resource, db_status, title, extra, webhook_last_updated = row
            ed = extra or {}

            # Extract claim_id
            claim_id = str(ed.get("claim_id", ""))
            if not claim_id:
                parts = resource.rstrip("/").split("/")
                claim_id = parts[-1] if parts[-1].isdigit() else ""

            if not claim_id or claim_id in seen_claim_ids:
                continue
            seen_claim_ids.add(claim_id)
            cache_checked_via_webhook.add(claim_id)

            cached_row = cache_by_claim_id.get(claim_id)

            if cached_row:
                # Compare timestamps: did webhook receive an update after our cache?
                cache_updated = cached_row.updated_at
                if cache_updated and cache_updated.tzinfo is None:
                    cache_updated = cache_updated.replace(tzinfo=timezone.utc)
                wh_updated = webhook_last_updated
                if wh_updated and hasattr(wh_updated, "tzinfo") and wh_updated.tzinfo is None:
                    wh_updated = wh_updated.replace(tzinfo=timezone.utc)

                if wh_updated and cache_updated and wh_updated <= cache_updated:
                    # Cache is up-to-date — use it
                    claims.append(_build_claim_from_db_cache(cached_row))
                    continue

                # Webhook is newer → re-enrich via HTTP
                enriched = _enrich_claim_via_http(claim_id)
                if enriched:
                    claims.append(enriched)
                else:
                    # HTTP failed — use stale cache as fallback
                    claims.append(_build_claim_from_db_cache(cached_row))
                continue

            # Not in cache at all — enrich from scratch
            if ed.get("claim_id") and ed.get("triage_tags"):
                # Webhook has enriched data — use it and save to cache
                built = _build_claim_from_enriched_extra(ed, status_override=db_status, title_fallback=title)
                claims.append(built)
                _save_claim_to_cache(built)
                continue

            # Incomplete data — full HTTP enrich (saves to cache internally)
            enriched = _enrich_claim_via_http(claim_id)
            if enriched:
                claims.append(enriched)

    except RuntimeError:
        # ML_WEBHOOK_DB_URL not configured — skip webhook DB
        pass
    except Exception:
        logger.warning("Failed to fetch claims from webhook DB", exc_info=True)

    # ── Step 3: Cached claims NOT seen in ml_previews ───────────────────────
    for cid, cached_row in cache_by_claim_id.items():
        if cid in seen_claim_ids:
            continue
        seen_claim_ids.add(cid)

        if not webhook_db_available and _is_cache_stale_by_time(cached_row):
            # Webhook DB unavailable — time-based fallback for open claims
            enriched = _enrich_claim_via_http(cid)
            if enriched:
                claims.append(enriched)
            else:
                claims.append(_build_claim_from_db_cache(cached_row))
        else:
            # Webhook DB was available but claim wasn't there, or cache is fresh
            claims.append(_build_claim_from_db_cache(cached_row))

    # ── Step 4: Search ML API for claims not found anywhere ─────────────────
    api_claims = _search_claims_via_api(order_ids, seen_claim_ids)
    claims.extend(api_claims)

    return claims


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
    # 1. Movimientos y artículo
    movimientos, articulo = _build_movimientos(db, serial)

    # 2. Pedidos vinculados
    result_pedidos = db.execute(QUERY_PEDIDOS, {"serial": serial})
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
        for row in (dict(r._mapping) for r in result_pedidos)
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

    # 3. Buscar RMAs vía factura (para productos no seriados o RMAs sin serial)
    # Cadena: soh_id → commercial_transactions → item_transactions → rma_detail
    soh_ids = [row["soh_id"] for row in pedidos_rows]
    rma_por_factura = _build_rma_by_invoice(db, soh_ids, exclude_rmad_ids=rma_ids_por_serial)

    # 4. Claims de ML (por order_id de los pedidos)
    ml_order_ids = [p.ml_id for p in pedidos if p.ml_id]
    claims = _fetch_claims_by_order_ids(ml_order_ids)

    return TrazaMLResponse(
        ml_id=ml_id,
        busqueda_por=busqueda_por,
        pedidos=pedidos,
        seriales=seriales_list,
        rma_por_factura=rma_por_factura,
        claims=claims,
    )


# ── Claim messages ──────────────────────────────────────────────────────────


class ClaimMessageResponse(BaseModel):
    """Mensaje individual de un reclamo ML."""

    id: int
    claim_id: int
    sender_role: Optional[str] = None
    receiver_role: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    attachments: Optional[list] = None
    date_read: Optional[str] = None
    ml_date_created: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


@router.get(
    "/claims/{claim_id}/messages",
    response_model=list[ClaimMessageResponse],
)
def get_claim_messages(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[ClaimMessageResponse]:
    """
    Devuelve los mensajes cacheados de un reclamo de ML.
    Si no hay mensajes en cache, intenta fetchearlos de la API de ML,
    los guarda en cache y los devuelve.
    """
    # 1. Try local cache first
    rows = (
        db.query(RmaClaimMLMessage)
        .filter(RmaClaimMLMessage.claim_id == claim_id)
        .order_by(RmaClaimMLMessage.ml_date_created.asc())
        .all()
    )
    if rows:
        return rows

    # 2. Fetch from ML API and save to cache
    claim_id_str = str(claim_id)
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={
                    "resource": f"/post-purchase/v1/claims/{claim_id_str}/messages",
                    "format": "json",
                },
            )
            if r.status_code == 200:
                messages_data = r.json()
                _save_messages_to_cache(claim_id_str, messages_data)

                # Re-query after save
                rows = (
                    db.query(RmaClaimMLMessage)
                    .filter(RmaClaimMLMessage.claim_id == claim_id)
                    .order_by(RmaClaimMLMessage.ml_date_created.asc())
                    .all()
                )
                return rows
    except Exception:
        logger.warning(
            "[claims] Failed to fetch messages for claim %s",
            claim_id,
            exc_info=True,
        )

    return []


# ── Order (pack) messages — mensajería posventa ────────────────────────────


QUERY_PACK_ID_BY_ORDER = text("""
    SELECT mlo.ml_pack_id
    FROM tb_sale_order_header soh
    INNER JOIN tb_mercadolibre_orders_header mlo
        ON soh.mlo_id = mlo.mlo_id
    WHERE soh.soh_mlid = :order_id
    LIMIT 1
""")


class OrderMessageResponse(BaseModel):
    """Mensaje de la conversación posventa (mensajería de packs)."""

    message_id: Optional[str] = None
    from_user_id: Optional[int] = None
    to_user_id: Optional[int] = None
    text: Optional[str] = None
    status: Optional[str] = None
    date_created: Optional[str] = None
    date_read: Optional[str] = None
    attachments: Optional[list] = None
    is_seller: bool = False


@router.get(
    "/orders/{order_id}/messages",
    response_model=list[OrderMessageResponse],
)
def get_order_messages(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[OrderMessageResponse]:
    """
    Devuelve los mensajes de la conversación posventa (mensajería de packs).
    Busca el pack_id asociado al order_id y fetchea de la API de ML.
    Si el order no pertenece a un pack, usa order_id como pack_id.
    """
    seller_id = settings.ML_USER_ID
    if not seller_id:
        return []

    # 1. Buscar pack_id en la DB
    row = db.execute(QUERY_PACK_ID_BY_ORDER, {"order_id": order_id}).first()
    pack_id = str(row.ml_pack_id) if row and row.ml_pack_id else order_id

    # 2. Fetch de la API de ML
    seller_id_str = str(seller_id)
    resource = f"/messages/packs/{pack_id}/sellers/{seller_id_str}?tag=post_sale&mark_as_read=false"
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": resource, "format": "json"},
            )
            if r.status_code != 200:
                logger.warning(
                    "[order-msgs] Failed to fetch pack %s messages: %s",
                    pack_id,
                    r.status_code,
                )
                return []

            data = r.json()

            # ML returns {paging, messages, conversation_status, ...}
            raw_messages = data.get("messages") or []
            seller_id_int = int(seller_id_str)

            result: list[OrderMessageResponse] = []
            for msg in raw_messages:
                from_uid = msg.get("from", {}).get("user_id")
                to_uid = msg.get("to", {}).get("user_id")

                # Extract text — can be string or dict with "plain"
                msg_text = msg.get("text")
                if isinstance(msg_text, dict):
                    msg_text = msg_text.get("plain", "")

                dates = msg.get("message_date") or {}

                result.append(
                    OrderMessageResponse(
                        message_id=msg.get("id"),
                        from_user_id=from_uid,
                        to_user_id=to_uid,
                        text=msg_text,
                        status=msg.get("status"),
                        date_created=dates.get("created") or dates.get("received"),
                        date_read=dates.get("read"),
                        attachments=msg.get("message_attachments"),
                        is_seller=(from_uid == seller_id_int),
                    )
                )
            return result
    except Exception:
        logger.warning(
            "[order-msgs] Exception fetching messages for order %s (pack %s)",
            order_id,
            pack_id,
            exc_info=True,
        )

    return []


# ── ML attachment proxy ─────────────────────────────────────────────────────

# Map file extensions to MIME types
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


@router.get("/ml-attachment")
def get_ml_attachment(
    id: str = Query(..., description="Attachment key from ML message_attachments"),
    current_user: Usuario = Depends(get_current_user),
) -> Response:
    """
    Proxy para descargar adjuntos de mensajes de ML.
    Fetchea /messages/attachments/{id}?tag=post_sale&site_id=MLA
    y devuelve el binario con el content-type correcto.
    Usa query param para evitar que nginx/CDN intercepte la extensión como archivo estático.
    """
    attachment_id = id
    resource = f"/messages/attachments/{attachment_id}?tag=post_sale&site_id=MLA"
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": resource, "format": "json"},
            )
            if r.status_code != 200:
                raise HTTPException(
                    status_code=r.status_code,
                    detail=f"ML returned {r.status_code}",
                )

            # Determine content type from ML response or file extension
            content_type = r.headers.get("content-type", "application/octet-stream")
            if "json" in content_type or "text/html" in content_type:
                # Proxy returned an error page or JSON error, not the file
                # Try to guess from extension
                ext = ""
                for e in _EXT_TO_MIME:
                    if attachment_id.lower().endswith(e):
                        ext = e
                        break
                content_type = _EXT_TO_MIME.get(ext, "application/octet-stream")

            return Response(
                content=r.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": f'inline; filename="{attachment_id.split("/")[-1]}"',
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "[ml-attachment] Failed to fetch attachment %s",
            attachment_id,
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail="Failed to fetch attachment")
