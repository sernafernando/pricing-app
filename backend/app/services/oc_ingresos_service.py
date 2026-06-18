"""
oc_ingresos_service — OC candidate listing and per-depot breakdown.

Slice 1 functions:
  - get_oc_candidatas: returns pending OC candidates for a pedido's supplier.
  - get_orden_compra_detalle: returns line-by-depot breakdown of the linked OC.

The candidatas criterion (CRITERION-PENDIENTE, verified 2026-06-18):
  bool_and(COALESCE(d.pod_isprocessed, FALSE)) = FALSE
  i.e. the OC has at least one unprocessed line.

ERP tables (tb_purchase_order_*) are READ-ONLY throughout.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.pedido_compra import PedidoCompra
from app.schemas.oc_ingreso import (
    OCCandidataResponse,
    OrdenCompraDetalleResponse,
    OrdenCompraLineaResponse,
)

logger = get_logger("services.oc_ingresos_service")


def _obtener_pedido_o_404(session: Session, pedido_id: int) -> PedidoCompra:
    pedido = session.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PedidoCompra id={pedido_id} no encontrado.",
        )
    return pedido


def get_oc_candidatas(
    session: Session,
    *,
    pedido_id: int,
) -> List[OCCandidataResponse]:
    """
    Returns pending OC candidates for the pedido's supplier.

    Resolves supp_id from proveedores. If NULL, returns [] with a WARNING.
    Applies CRITERION-PENDIENTE: OC has at least one unprocessed line.
    Excludes OCs already linked to a different pedido.

    Raw text() query — mirrors the module's existing pattern.
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)

    supp_id = session.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": pedido.proveedor_id},
    ).scalar_one_or_none()

    if supp_id is None:
        logger.warning(
            "oc-candidatas: proveedor_id=%s sin supp_id ERP → lista vacía",
            pedido.proveedor_id,
        )
        return []

    # NOTE: The HAVING clause uses MIN(CASE...) instead of bool_and() to stay
    # compatible with SQLite (used in tests). On PostgreSQL, both are equivalent
    # for this use case. The canonical criterion is:
    #   bool_and(COALESCE(pod_isprocessed, FALSE)) = FALSE
    # IMPORTANT: pod_isprocessed is a real BOOLEAN in PostgreSQL, so the COALESCE
    # default and the comparison MUST use boolean literals (FALSE/TRUE), not 0/1.
    # COALESCE(boolean, 0) raises DatatypeMismatch on PostgreSQL even though it
    # works on SQLite (where booleans are stored as integers) — the test DB does
    # NOT catch this.
    stmt = text(
        """
        SELECT h.comp_id, h.bra_id, h.poh_id, h.poh_total, h.poh_cd,
               SUM(d.pod_qty)                                             AS qty_total,
               SUM(CASE WHEN COALESCE(d.pod_isprocessed, FALSE) = FALSE THEN 1 ELSE 0 END) AS lineas_pendientes
        FROM tb_purchase_order_header h
        JOIN tb_purchase_order_detail d
          ON d.comp_id = h.comp_id AND d.bra_id = h.bra_id AND d.poh_id = h.poh_id
        WHERE h.supp_id = :supp_id
          AND NOT EXISTS (
              SELECT 1 FROM pedidos_compra p
              WHERE p.oc_poh_id  = h.poh_id
                AND p.oc_comp_id = h.comp_id
                AND p.oc_bra_id  = h.bra_id
                AND p.id <> :pedido_id
          )
        GROUP BY h.comp_id, h.bra_id, h.poh_id, h.poh_total, h.poh_cd
        HAVING MIN(CASE WHEN COALESCE(d.pod_isprocessed, FALSE) = TRUE THEN 1 ELSE 0 END) = 0
        ORDER BY h.poh_cd DESC NULLS LAST
        LIMIT 100
        """
    )
    rows = session.execute(stmt, {"supp_id": int(supp_id), "pedido_id": pedido.id}).all()

    return [
        OCCandidataResponse(
            oc_comp_id=int(row[0]),
            oc_bra_id=int(row[1]),
            oc_poh_id=int(row[2]),
            poh_total=Decimal(str(row[3] or 0)),
            poh_cd=str(row[4]) if row[4] is not None else None,
            qty_total=Decimal(str(row[5] or 0)),
            lineas_pendientes=int(row[6] or 0),
        )
        for row in rows
    ]


def get_orden_compra_detalle(
    session: Session,
    *,
    pedido_id: int,
) -> OrdenCompraDetalleResponse:
    """
    Returns the per-depot line breakdown for the OC linked to the pedido.

    Reads live from tb_purchase_order_detail JOIN tb_storage (read-only).
    In Slice 1, saldo_pendiente = pod_qty - COALESCE(pod_confirmedqty, 0)
    (recibido_pricing always 0 — pedido_compra_ingresos not yet created).

    Raises:
        HTTPException 404 — pedido not found.
        HTTPException 409 — pedido has no linked OC.
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)
    if pedido.oc_poh_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pedido id={pedido.id} has no linked OC.",
        )

    stmt = text(
        """
        SELECT d.pod_id, d.item_id, d.stor_id, s.stor_desc,
               d.pod_qty, d.pod_confirmedqty, d.pod_price,
               p.descripcion AS item_nombre
        FROM tb_purchase_order_detail d
        LEFT JOIN tb_storage s
          ON s.comp_id = d.comp_id AND s.stor_id = d.stor_id
        LEFT JOIN productos_erp p
          ON p.item_id = d.item_id
        WHERE d.comp_id = :comp AND d.bra_id = :bra AND d.poh_id = :poh
        ORDER BY d.pod_id
        """
    )
    rows = session.execute(
        stmt,
        {
            "comp": pedido.oc_comp_id,
            "bra": pedido.oc_bra_id,
            "poh": pedido.oc_poh_id,
        },
    ).all()

    lines: List[OrdenCompraLineaResponse] = []
    for row in rows:
        pod_qty = Decimal(str(row[4] or 0))
        pod_confirmedqty = Decimal(str(row[5] or 0))
        # In Slice 1 there are no ingresos yet; recibido_pricing = 0.
        saldo_pendiente = pod_qty - pod_confirmedqty
        item_id = int(row[1]) if row[1] is not None else None
        # item_nombre: resolved via LEFT JOIN; NULL if phantom item → use str(item_id)
        raw_nombre = row[7]
        item_nombre = raw_nombre if raw_nombre is not None else (str(item_id) if item_id is not None else None)
        lines.append(
            OrdenCompraLineaResponse(
                pod_id=int(row[0]),
                item_id=item_id,
                item_nombre=item_nombre,
                stor_id=int(row[2]) if row[2] is not None else None,
                deposito_nombre=row[3],
                pod_qty=pod_qty,
                pod_confirmedqty=pod_confirmedqty,
                saldo_pendiente=saldo_pendiente,
                pod_price=Decimal(str(row[6] or 0)) if row[6] is not None else None,
            )
        )

    return OrdenCompraDetalleResponse(
        oc_comp_id=pedido.oc_comp_id,
        oc_bra_id=pedido.oc_bra_id,
        oc_poh_id=pedido.oc_poh_id,
        lines=lines,
    )
