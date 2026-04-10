"""
Seriales — Traza por factura.

Endpoints:
  GET /traza/factura-detalle/{ct_transaction}
  GET /traza/factura
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.routers.seriales_shared import (
    FacturaDetalleItem,
    FacturaDetalleResponse,
    FacturaInfo,
    RMASerial,
    TrazaFacturaResponse,
    TrazaMLSerialItem,
    _build_movimientos,
    _build_rma,
    _build_rma_by_ct_transaction,
    QUERY_FACTURA_DETALLE,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# QUERIES (only used by this module)
# =============================================================================

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


# =============================================================================
# ENDPOINTS
# =============================================================================


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
