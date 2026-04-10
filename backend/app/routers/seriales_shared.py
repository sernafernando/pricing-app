"""
Seriales — Shared schemas, queries, helpers and builders.

Used by all seriales_* sub-modules.
"""

import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ML_WEBHOOK_RENDER_URL = "https://ml-webhook.gaussonline.com.ar/api/ml/render"
_HTTPX_TIMEOUT = 10.0  # seconds per request to ML webhook proxy
_GBP_TIMEOUT = 10.0


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

    soh_id: Optional[int] = 0
    bra_id: Optional[int] = 0
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
    ml_ids_relacionados: list[str] = []
    shipping_ids_relacionados: list[str] = []
    pack_ids_relacionados: list[str] = []
    discrepancias_identificadores: list[str] = []
    webhook_previews: list[dict] = []
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
# SHARED QUERIES
# =============================================================================

QUERY_TRAZA = text("""
    WITH
    -- 1. Movimiento directo de tb_item_serials (típicamente la COMPRA)
    direct_movimientos AS (
        SELECT
            s.is_id,
            s.item_id,
            s.ct_transaction,
            s.it_transaction,
            s.stor_id,
            s.is_cd,
            s.is_available,
            ct.ct_kindof,
            ct.ct_pointofsale,
            ct.ct_docnumber,
            ct.ct_date,
            ct.cust_id,
            ct.supp_id,
            ct.df_id,
            df.df_desc,
            cust.cust_name AS cliente_nombre,
            supp.supp_name AS proveedor_nombre,
            stor.stor_desc,
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
        WHERE UPPER(s.is_serial) = UPPER(:serial)
    ),
    -- 2. Movimientos adicionales vía tb_item_transaction_serials (típicamente la VENTA)
    --    Vincula is_id → its → it_transaction/ct_transaction
    bridge_movimientos AS (
        SELECT
            s.is_id,
            s.item_id,
            its.ct_transaction,
            its.it_transaction,
            s.stor_id,
            s.is_cd,
            s.is_available,
            ct.ct_kindof,
            ct.ct_pointofsale,
            ct.ct_docnumber,
            ct.ct_date,
            ct.cust_id,
            ct.supp_id,
            ct.df_id,
            df.df_desc,
            cust.cust_name AS cliente_nombre,
            supp.supp_name AS proveedor_nombre,
            stor.stor_desc,
            pe.codigo AS item_codigo,
            pe.descripcion AS item_descripcion,
            pe.marca AS item_marca,
            cat.cat_desc AS item_categoria
        FROM tb_item_serials s
        INNER JOIN tb_item_transaction_serials its
            ON s.comp_id = its.comp_id
            AND s.is_id = its.is_id
        INNER JOIN tb_commercial_transactions ct
            ON its.ct_transaction = ct.ct_transaction
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
        WHERE UPPER(s.is_serial) = UPPER(:serial)
            -- Excluir la misma ct_transaction que ya viene del directo
            AND its.ct_transaction != s.ct_transaction
    ),
    -- 3. Combinar ambos, deduplicar por ct_transaction
    combined AS (
        SELECT * FROM direct_movimientos
        UNION ALL
        SELECT * FROM bridge_movimientos
    ),
    deduped AS (
        SELECT DISTINCT ON (ct_transaction) *
        FROM combined
        ORDER BY ct_transaction, is_id ASC
    )
    SELECT * FROM deduped
    ORDER BY ct_date ASC NULLS LAST, is_id ASC
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
        SELECT s.is_id FROM tb_item_serials s WHERE UPPER(s.is_serial) = UPPER(:serial)
    )
    OR UPPER(d.rmad_serial) = UPPER(:serial)
    OR UPPER(d."rmad_Manual") = UPPER(:serial)
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

QUERY_FACTURA_ITEMS_BY_SOHID = text("""
    SELECT
        ct.ct_transaction,
        ct.ct_kindof,
        ct.ct_pointofsale,
        ct.ct_docnumber,
        ct.ct_date,
        it.it_transaction,
        it.item_id,
        ti.item_code,
        COALESCE(pe.descripcion, ti.item_desc) AS item_desc,
        it.it_price AS precio_unitario
    FROM tb_commercial_transactions ct
    INNER JOIN tb_item_transactions it
        ON it.ct_transaction = ct.ct_transaction
        AND it.comp_id = ct.comp_id
    LEFT JOIN tb_item ti
        ON it.comp_id = ti.comp_id
        AND it.item_id = ti.item_id
    LEFT JOIN productos_erp pe
        ON it.item_id = pe.item_id
    WHERE ct.comp_id = :comp_id
        AND ct.ct_soh_id = :soh_id
    ORDER BY ct.ct_date DESC NULLS LAST, ct.ct_transaction DESC, it.it_transaction DESC
""")


# =============================================================================
# SHARED HELPERS
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
    from datetime import date, datetime

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
# SHARED BUILDERS
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
                dias_a_la_fecha=calcular_dias(ct_date or is_cd),
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
