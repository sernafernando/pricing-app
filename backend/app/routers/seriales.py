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
    ml_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TrazaSerialResponse(BaseModel):
    """Respuesta completa de traza de un serial"""

    serial: str
    articulo: Optional[ArticuloInfo] = None
    movimientos: list[MovimientoSerial] = []
    pedidos: list[PedidoSerial] = []

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

QUERY_PEDIDOS = text("""
    SELECT DISTINCT
        soh.soh_id,
        soh.bra_id,
        soh.soh_cd,
        soh.cust_id,
        cust.cust_name AS cliente_nombre,
        soh.soh_mlid,
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
    """Construye el número de documento legible (ej: Fc A 00004-0000128762)"""
    df_desc = row.get("df_desc") or ""
    doc_number = row.get("ct_docnumber") or ""
    if df_desc or doc_number:
        return f"{df_desc} {doc_number}".strip() or None
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
# ENDPOINTS
# =============================================================================


@router.get("/traza/{serial}", response_model=TrazaSerialResponse)
def traza_serial(
    serial: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TrazaSerialResponse:
    """
    Obtiene la traza completa de un número de serie.
    Devuelve artículo, movimientos (compras/ventas/transferencias) y pedidos vinculados.
    """
    # 1. Buscar movimientos del serial
    result_movimientos = db.execute(QUERY_TRAZA, {"serial": serial})
    rows = [dict(row._mapping) for row in result_movimientos]

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el serial: {serial}",
        )

    # 2. Extraer info del artículo (del primer movimiento)
    first = rows[0]
    articulo = None
    if first.get("item_id"):
        articulo = ArticuloInfo(
            item_id=first["item_id"],
            codigo=first.get("item_codigo") or "",
            descripcion=first.get("item_descripcion") or "",
            marca=first.get("item_marca"),
            categoria=first.get("item_categoria"),
        )

    # 3. Construir movimientos
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

    # 4. Buscar pedidos vinculados
    result_pedidos = db.execute(QUERY_PEDIDOS, {"serial": serial})
    pedidos_rows = [dict(row._mapping) for row in result_pedidos]

    pedidos = []
    for row in pedidos_rows:
        fecha = row.get("soh_cd")
        pedidos.append(
            PedidoSerial(
                soh_id=row["soh_id"],
                bra_id=row["bra_id"],
                fecha=str(fecha) if fecha else None,
                estado=row.get("estado_nombre"),
                cust_id=row.get("cust_id"),
                cliente=row.get("cliente_nombre"),
                ml_id=row.get("soh_mlid"),
            )
        )

    return TrazaSerialResponse(
        serial=serial,
        articulo=articulo,
        movimientos=movimientos,
        pedidos=pedidos,
    )
