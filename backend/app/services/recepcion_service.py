"""
recepcion_service — business logic for goods reception (recepcion de mercaderia).

Responsibilities:
  - computar_saldos: derive per-line balances from ERP + pricing-app ingresos.
  - registrar_ingresos: atomic multi-line receipt batch for CON-OC pedidos.
  - confirmar_pedido_sin_oc: receipt confirmation for SIN-OC pedidos (sentinel row).
  - recalcular_estado: state machine transition after a receipt batch.
  - get_eventos_recepcion: list reception events for a pedido.

ERP tables (tb_purchase_order_*, productos_erp) are READ-ONLY throughout.
All writes target only: pedidos_compra (estado), pedido_compra_ingresos (INSERT),
compras_eventos (INSERT).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.usuario import Usuario
from app.schemas.recepcion import (
    ConfirmarPedidoRequest,
    ConfirmarPedidoResponse,
    EventoRecepcionItem,
    EventosRecepcionResponse,
    IngresoCreadoResponse,
    IngresoLinea,
    RegistrarIngresosRequest,
    RegistrarIngresosResponse,
    SaldoLineaResponse,
    SaldoPostIngreso,
    SaldosResponse,
)

logger = get_logger("services.recepcion_service")

# Permission constant — used by the router to avoid hardcoded strings.
PERMISO_RECEPCION: str = "deposito.recibir_mercaderia"

# States that accept incoming receipt operations.
_ESTADOS_RECEPTIVOS: frozenset[str] = frozenset({"pagado", "con_faltantes"})


# ──────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────


def _validar_estado_receptivo(pedido: PedidoCompra) -> None:
    """Raise 409 if the pedido cannot accept a receipt operation.

    Allowed entry states: 'pagado', 'con_faltantes'.
    'recibido' raises a distinct 409 (terminal state).
    All other states raise a generic 409.
    """
    if pedido.estado == "recibido":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido already fully received",
        )
    if pedido.estado not in _ESTADOS_RECEPTIVOS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pedido not in a receivable state (estado='{pedido.estado}')",
        )


def _emit_evento(
    session: Session,
    *,
    pedido: PedidoCompra,
    user: Usuario,
    tipo: str,
    payload: dict[str, Any],
) -> None:
    """Append a CompraEvento record inside the current transaction."""
    evento = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        tipo=tipo,
        usuario_id=user.id,
        payload=payload,
    )
    session.add(evento)


# ──────────────────────────────────────────────────────────────────────────
# RD-A.6 — computar_saldos + recalcular_estado
# ──────────────────────────────────────────────────────────────────────────


def computar_saldos(session: Session, pedido: PedidoCompra) -> SaldosResponse:
    """Compute per-line balances for a pedido.

    Formula per OC line:
        saldo = pod_qty - COALESCE(pod_confirmedqty, 0) - Σ cantidad_recibida(pricing-app)

    If the pedido has no linked OC, returns SaldosResponse with lineas=[].
    Does NOT enforce the receptive-state guard (the endpoint does that before calling).

    ERP tables are read-only: no INSERT/UPDATE/DELETE issued here.
    """
    if pedido.oc_poh_id is None:
        return SaldosResponse(
            pedido_id=pedido.id,
            tiene_oc=False,
            estado=pedido.estado,
            requiere_envio=bool(pedido.requiere_envio),
            lineas=[],
        )

    # Query A — OC lines from ERP + storage name + item name
    # IMPORTANT: pod_isprocessed is BOOLEAN in PostgreSQL; COALESCE with FALSE literal
    # (not 0/1) to avoid DatatypeMismatch in production.
    stmt_lineas = text(
        """
        SELECT d.pod_id,
               d.item_id,
               d.stor_id,
               s.stor_desc,
               d.pod_qty,
               COALESCE(d.pod_confirmedqty, 0) AS pod_confirmedqty,
               p.descripcion AS item_nombre,
               p.codigo AS item_code
        FROM tb_purchase_order_detail d
        LEFT JOIN tb_storage s
          ON s.comp_id = d.comp_id AND s.stor_id = d.stor_id
        LEFT JOIN productos_erp p
          ON p.item_id = d.item_id
        WHERE d.comp_id = :comp AND d.bra_id = :bra AND d.poh_id = :poh
        ORDER BY d.pod_id
        """
    )
    oc_rows = session.execute(
        stmt_lineas,
        {"comp": pedido.oc_comp_id, "bra": pedido.oc_bra_id, "poh": pedido.oc_poh_id},
    ).all()

    # Query B — accumulated ingresos from pricing-app (pod_id IS NOT NULL guard)
    stmt_ingresos = text(
        """
        SELECT pod_id, COALESCE(SUM(cantidad_recibida), 0) AS recibido_pricing
        FROM pedido_compra_ingresos
        WHERE pedido_id = :pedido_id AND pod_id IS NOT NULL
        GROUP BY pod_id
        """
    )
    ingreso_rows = session.execute(stmt_ingresos, {"pedido_id": pedido.id}).all()
    recibido_by_pod: dict[int, Decimal] = {int(r[0]): Decimal(str(r[1])) for r in ingreso_rows}

    lineas: list[SaldoLineaResponse] = []
    for row in oc_rows:
        pod_id = int(row[0])
        item_id = int(row[1]) if row[1] is not None else None
        stor_id = int(row[2]) if row[2] is not None else None
        deposito_nombre: str | None = row[3]
        pod_qty = Decimal(str(row[4] or 0))
        pod_confirmedqty = Decimal(str(row[5] or 0))
        raw_nombre: str | None = row[6]
        item_code: str | None = row[7]
        # Phantom item fallback: if no match in productos_erp, use str(item_id)
        item_nombre = raw_nombre if raw_nombre is not None else (str(item_id) if item_id is not None else None)

        recibido_pricing = recibido_by_pod.get(pod_id, Decimal("0"))
        saldo_pendiente = pod_qty - pod_confirmedqty - recibido_pricing

        lineas.append(
            SaldoLineaResponse(
                pod_id=pod_id,
                item_id=item_id,
                item_code=item_code,
                item_nombre=item_nombre,
                stor_id=stor_id,
                deposito_nombre=deposito_nombre,
                pod_qty=pod_qty,
                cantidad_recibida_total=recibido_pricing,
                saldo_pendiente=saldo_pendiente,
            )
        )

    return SaldosResponse(
        pedido_id=pedido.id,
        tiene_oc=True,
        estado=pedido.estado,
        requiere_envio=bool(pedido.requiere_envio),
        lineas=lineas,
    )


def recalcular_estado(
    session: Session,
    pedido: PedidoCompra,
    oc_lineas_saldos: list[dict[str, Any]],
) -> str:
    """Transition pedido.estado based on remaining balances after a receipt batch.

    Args:
        oc_lineas_saldos: list of dicts with keys 'pod_id' and 'saldo' (Decimal).

    Returns:
        The new estado string ('recibido' or 'con_faltantes').
    """
    all_zero = all(Decimal(str(l["saldo"])) <= Decimal("0") for l in oc_lineas_saldos)
    nuevo_estado = "recibido" if all_zero else "con_faltantes"
    pedido.estado = nuevo_estado
    return nuevo_estado


# ──────────────────────────────────────────────────────────────────────────
# RD-A.7 — registrar_ingresos
# ──────────────────────────────────────────────────────────────────────────


def registrar_ingresos(
    session: Session,
    pedido: PedidoCompra,
    user: Usuario,
    request: RegistrarIngresosRequest,
) -> RegistrarIngresosResponse:
    """Register a receipt batch (tanda) for a CON-OC pedido.

    Steps:
      1. State guard: pedido must be in a receptive state.
      2. OC guard: pedido must have a linked OC.
      3. Filter lines with cantidad_recibida > 0 (silently ignore zeros).
      4. Compute pre-insert saldos for all lines in the batch.
      5. Over-receipt check for ALL lines before any INSERT (atomic).
      6. INSERT one PedidoCompraIngreso per non-zero line.
      7. Recompute estado (recalcular_estado across ALL OC lines).
      8. Emit compras_evento.

    Raises:
        HTTPException 409 — pedido already received / not receptive / no OC / over-receipt.
        HTTPException 422 — pod_id not found in OC (invalid line reference).
    """
    _validar_estado_receptivo(pedido)

    if pedido.oc_poh_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido has no linked OC",
        )

    # Step 3 — filter non-zero lines
    lineas_validas: list[IngresoLinea] = [l for l in request.lineas if l.cantidad_recibida > Decimal("0")]
    if not lineas_validas:
        # All zeros: treat as a no-op returning current saldos without state change.
        saldos_resp = computar_saldos(session, pedido)
        return RegistrarIngresosResponse(
            pedido_id=pedido.id,
            estado_nuevo=pedido.estado,
            ingresos_creados=[],
            saldos=[SaldoPostIngreso(pod_id=l.pod_id, saldo_pendiente=l.saldo_pendiente) for l in saldos_resp.lineas],
        )

    # Step 4 — pre-insert saldos (current state before this batch)
    pre_saldos_resp = computar_saldos(session, pedido)
    saldo_by_pod: dict[int, Decimal] = {l.pod_id: l.saldo_pendiente for l in pre_saldos_resp.lineas}

    # Step 5 — over-receipt check (fail BEFORE any INSERT)
    for linea in lineas_validas:
        saldo_actual = saldo_by_pod.get(linea.pod_id)
        if saldo_actual is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"pod_id {linea.pod_id} not found in linked OC",
            )
        if linea.cantidad_recibida > saldo_actual:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Over-receipt: pod_id {linea.pod_id} — "
                    f"saldo pendiente es {saldo_actual}, solicitado {linea.cantidad_recibida}"
                ),
            )

    # Fetch pod detail rows to snapshot item_id, stor_id
    stmt_pod = text(
        """
        SELECT pod_id, item_id, stor_id
        FROM tb_purchase_order_detail
        WHERE comp_id = :comp AND bra_id = :bra AND poh_id = :poh
          AND pod_id IN :pod_ids
        """
    ).bindparams(bindparam("pod_ids", expanding=True))
    pod_rows = session.execute(
        stmt_pod,
        {
            "comp": pedido.oc_comp_id,
            "bra": pedido.oc_bra_id,
            "poh": pedido.oc_poh_id,
            "pod_ids": [linea.pod_id for linea in lineas_validas],
        },
    ).all()
    pod_detail: dict[int, dict[str, Any]] = {
        int(r[0]): {"item_id": int(r[1]) if r[1] else None, "stor_id": int(r[2]) if r[2] else None} for r in pod_rows
    }

    # Step 6 — INSERT one row per non-zero line
    ingresos_creados: list[PedidoCompraIngreso] = []
    for linea in lineas_validas:
        detail = pod_detail.get(linea.pod_id, {})
        ingreso = PedidoCompraIngreso(
            pedido_id=pedido.id,
            oc_comp_id=pedido.oc_comp_id,
            oc_bra_id=pedido.oc_bra_id,
            oc_poh_id=pedido.oc_poh_id,
            pod_id=linea.pod_id,
            item_id=detail.get("item_id"),
            stor_id=detail.get("stor_id"),
            cantidad_recibida=linea.cantidad_recibida,
            usuario_id=user.id,
            observaciones=request.observaciones,
        )
        session.add(ingreso)
        ingresos_creados.append(ingreso)
    session.flush()  # get IDs without committing

    # Step 7 — recompute saldos AFTER inserts to determine transition
    post_saldos_resp = computar_saldos(session, pedido)
    post_saldo_by_pod: dict[int, Decimal] = {l.pod_id: l.saldo_pendiente for l in post_saldos_resp.lineas}
    saldos_lista = [{"pod_id": pod_id, "saldo": saldo} for pod_id, saldo in post_saldo_by_pod.items()]
    nuevo_estado = recalcular_estado(session, pedido, saldos_lista)
    session.flush()  # persist estado update so callers see the new value

    # Step 8 — emit event
    if nuevo_estado == "recibido":
        tipo_evento = "recepcion_registrada"
        lineas_payload = [
            {
                "pod_id": l.pod_id,
                "item_id": l.item_id,
                "cantidad_recibida": float(
                    next(
                        (x.cantidad_recibida for x in lineas_validas if x.pod_id == l.pod_id),
                        Decimal("0"),
                    )
                ),
                "saldo_pendiente": float(l.saldo_pendiente),
            }
            for l in post_saldos_resp.lineas
        ]
    else:
        # recepcion_con_faltantes — include ALL OC lines (even unreceived)
        tipo_evento = "recepcion_con_faltantes"
        recibido_en_tanda: dict[int, Decimal] = {l.pod_id: l.cantidad_recibida for l in lineas_validas}
        lineas_payload = [
            {
                "pod_id": l.pod_id,
                "item_id": l.item_id,
                "cantidad_recibida": float(recibido_en_tanda.get(l.pod_id, Decimal("0"))),
                "saldo_pendiente": float(l.saldo_pendiente),
            }
            for l in post_saldos_resp.lineas
        ]

    _emit_evento(
        session,
        pedido=pedido,
        user=user,
        tipo=tipo_evento,
        payload={
            "modo": "con_oc",
            "lineas": lineas_payload,
            "requiere_envio": bool(pedido.requiere_envio),
            "retiro_generado": False,
        },
    )

    return RegistrarIngresosResponse(
        pedido_id=pedido.id,
        estado_nuevo=nuevo_estado,
        ingresos_creados=[
            IngresoCreadoResponse(
                id=ing.id,
                pod_id=ing.pod_id,
                cantidad_recibida=ing.cantidad_recibida,
            )
            for ing in ingresos_creados
        ],
        saldos=[SaldoPostIngreso(pod_id=l.pod_id, saldo_pendiente=l.saldo_pendiente) for l in post_saldos_resp.lineas],
    )


# ──────────────────────────────────────────────────────────────────────────
# RD-A.8 — confirmar_pedido_sin_oc
# ──────────────────────────────────────────────────────────────────────────


def confirmar_pedido_sin_oc(
    session: Session,
    pedido: PedidoCompra,
    user: Usuario,
    request: ConfirmarPedidoRequest,
) -> ConfirmarPedidoResponse:
    """Confirm reception at pedido level for SIN-OC pedidos.

    Writes a single sentinel row in pedido_compra_ingresos (pod_id=NULL,
    cantidad_recibida=1) for uniform WHO/WHEN auditing. The partial index
    ix_pci_pod excludes this row from saldo calculations.

    Raises:
        HTTPException 409 — pedido has OC linked (use /recepcion/ingresos instead).
        HTTPException 409 — pedido not in a receptive state.
    """
    if pedido.oc_poh_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido has OC linked. Use /recepcion/ingresos instead.",
        )

    _validar_estado_receptivo(pedido)

    # Sentinel row — pod_id=NULL marks SIN-OC confirmations
    sentinel = PedidoCompraIngreso(
        pedido_id=pedido.id,
        pod_id=None,
        oc_comp_id=None,
        oc_bra_id=None,
        oc_poh_id=None,
        item_id=None,
        stor_id=None,
        cantidad_recibida=Decimal("1"),
        usuario_id=user.id,
        observaciones=request.observaciones,
    )
    session.add(sentinel)

    nuevo_estado = "recibido" if request.completo else "con_faltantes"
    pedido.estado = nuevo_estado

    tipo_evento = "recepcion_registrada" if request.completo else "recepcion_con_faltantes"
    _emit_evento(
        session,
        pedido=pedido,
        user=user,
        tipo=tipo_evento,
        payload={
            "modo": "sin_oc",
            "completo": request.completo,
            "observaciones": request.observaciones,
            "requiere_envio": bool(pedido.requiere_envio),
            "retiro_generado": False,
        },
    )

    session.flush()

    return ConfirmarPedidoResponse(
        pedido_id=pedido.id,
        estado_nuevo=nuevo_estado,
    )


# ──────────────────────────────────────────────────────────────────────────
# RD-A.9 — get_eventos_recepcion
# ──────────────────────────────────────────────────────────────────────────


def get_eventos_recepcion(
    session: Session,
    pedido_id: int,
) -> EventosRecepcionResponse:
    """Return all reception events for a pedido, ordered newest-first.

    Filters compras_eventos by:
      entidad_tipo = 'pedido_compra'
      entidad_id   = pedido_id
      tipo         IN ('recepcion_registrada', 'recepcion_con_faltantes')
    """
    eventos = (
        session.query(CompraEvento)
        .filter(
            CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
            CompraEvento.entidad_id == pedido_id,
            CompraEvento.tipo.in_(["recepcion_registrada", "recepcion_con_faltantes"]),
        )
        .order_by(CompraEvento.id.desc())
        .all()
    )

    items: list[EventoRecepcionItem] = []
    for e in eventos:
        usuario_nombre: str | None = None
        if e.usuario is not None:
            usuario_nombre = getattr(e.usuario, "nombre", None) or getattr(e.usuario, "email", None)
        items.append(
            EventoRecepcionItem(
                id=e.id,
                tipo=e.tipo,
                created_at=e.created_at,
                usuario_nombre=usuario_nombre,
                payload=e.payload,
            )
        )

    return EventosRecepcionResponse(pedido_id=pedido_id, eventos=items)
