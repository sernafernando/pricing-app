"""
Router para traza de números de serie (módulo RMA)
Permite consultar el historial completo de movimientos de un serial.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, ConfigDict
from typing import Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario

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


class TrazaSerialResponse(BaseModel):
    """Respuesta completa de traza de un serial"""

    serial: str
    articulo: Optional[ArticuloInfo] = None
    movimientos: list[MovimientoSerial] = []
    pedidos: list[PedidoSerial] = []
    rma: list[RMASerial] = []

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
    busqueda_por: str = "soh_mlid"  # "soh_mlid" o "mlshippingid"
    pedidos: list[PedidoSerial] = []
    seriales: list[TrazaMLSerialItem] = []
    rma_por_factura: list[RMASerial] = []  # RMAs encontrados vía factura (no por serial)

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

    return TrazaSerialResponse(
        serial=serial,
        articulo=articulo,
        movimientos=movimientos,
        pedidos=pedidos,
        rma=rma_list,
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
        busqueda_por = "soh_mlid"
        result_pedidos = db.execute(QUERY_PEDIDOS_BY_MLID, {"ml_id": ml_id})
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

        # Fallback final: buscar como soh_mlid
        if not pedidos_rows:
            busqueda_por = "soh_mlid"
            result_pedidos = db.execute(QUERY_PEDIDOS_BY_MLID, {"ml_id": ml_id})
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

    return TrazaMLResponse(
        ml_id=ml_id,
        busqueda_por=busqueda_por,
        pedidos=pedidos,
        seriales=seriales_list,
        rma_por_factura=rma_por_factura,
    )
