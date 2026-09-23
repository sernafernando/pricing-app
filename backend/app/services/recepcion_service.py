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

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.pedido_compra_oc import triples_for_pedido
from app.models.usuario import Usuario
from app.schemas.recepcion import (
    ConfirmarPedidoRequest,
    ConfirmarPedidoResponse,
    DeshacerRecibidoResponse,
    EventoRecepcionItem,
    EventosRecepcionResponse,
    IngresoCreadoResponse,
    IngresoLinea,
    RegistrarIngresosRequest,
    RegistrarIngresosResponse,
    ResolverFaltantesResponse,
    SaldoLineaResponse,
    SaldoPostIngreso,
    SaldosResponse,
)

logger = get_logger("services.recepcion_service")

# Permission constant — used by the router to avoid hardcoded strings.
PERMISO_RECEPCION: str = "deposito.recibir_mercaderia"

# States from which the ARRIVAL step is valid — the entry gate of both reception
# paths. 'pagado' and 'en_cuenta_corriente' are logistically equivalent here: the
# goods may physically arrive either way, only the payment settlement differs (a
# pedido marked as cuenta corriente keeps its OP `pendiente` and settles
# independently via pagado_en). PUBLIC on purpose: the router MUST derive its
# CON-OC/SIN-OC dispatch from here instead of re-typing the pair. This exact pair
# had been hand-copied in three places (SIN-OC arrival, CON-OC arrival, router
# dispatch) and the SIN-OC one was never updated when 'en_cuenta_corriente'
# landed — that drift is what made a SIN-OC pedido in cuenta corriente impossible
# to receive (409).
ESTADOS_ARRIBO: frozenset[str] = frozenset({"pagado", "en_cuenta_corriente"})

# States that accept incoming receipt operations = ARRIVAL states plus the CONTROL
# states. 'recibido' is the intermediate state after arrival (D-CONOC) and
# 'con_faltantes' still admits a further control pass. Derived from ESTADOS_ARRIBO
# so the arrival pair is spelled out in exactly one place.
_ESTADOS_RECEPTIVOS: frozenset[str] = ESTADOS_ARRIBO | {"recibido", "con_faltantes"}

# Read access to saldos = receptive states PLUS 'controlado'. 'controlado' is
# terminal (no receipt may be registered) but its saldos stay queryable for
# audit/traceability (REQ-EC-009). PUBLIC on purpose: the router MUST derive
# its guard from here. The previous inline literal in `get_recepcion_saldos`
# is exactly how 'en_cuenta_corriente' drifted out of the allowed set.
ESTADOS_CONSULTA_SALDOS: frozenset[str] = _ESTADOS_RECEPTIVOS | {"controlado"}


# ──────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────


def _texto_faltantes(faltantes_texto: str | None, observaciones: str | None) -> str:
    """Prefer explicit faltantes_texto; observaciones is a backward-compat fallback."""
    for candidate in (faltantes_texto, observaciones):
        if candidate is not None and candidate.strip():
            return candidate.strip()
    return ""


def _alertar_faltantes_si_corresponde(session: Session, pedido: PedidoCompra, texto: str) -> None:
    from app.services import compras_alertas_service

    if pedido.proveedor is None:
        session.refresh(pedido, attribute_names=["proveedor"])
    compras_alertas_service.notificar_faltantes(session, pedido=pedido, texto=texto)


def _validar_no_servicio(pedido: PedidoCompra) -> None:
    """Servicio pedidos stay on procesal n_a_servicio — no recepción actions."""
    if getattr(pedido, "tipo", None) == "servicio":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido de servicio no admite recepción (n_a_servicio).",
        )


def _validar_estado_receptivo(pedido: PedidoCompra) -> None:
    """Raise 409 if the pedido cannot accept a receipt operation.

    Allowed entry states are `_ESTADOS_RECEPTIVOS` = ESTADOS_ARRIBO ('pagado',
    'en_cuenta_corriente') plus the control states ('recibido', 'con_faltantes').
    'controlado' raises a distinct 409 — it is the terminal state (D-SINOC).
    All other states raise a generic 409.
    """
    _validar_no_servicio(pedido)
    if pedido.estado == "controlado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido already controlled",
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
    triples = triples_for_pedido(session, pedido)
    if not triples:
        return SaldosResponse(
            pedido_id=pedido.id,
            tiene_oc=False,
            estado=pedido.estado,
            requiere_envio=bool(pedido.requiere_envio),
            lineas=[],
        )

    # Query A — OC lines from ERP + storage name + item name (all triples, one round-trip)
    # IMPORTANT: pod_isprocessed is BOOLEAN in PostgreSQL; COALESCE with FALSE literal
    # (not 0/1) to avoid DatatypeMismatch in production.
    or_clauses: list[str] = []
    lineas_params: dict[str, int] = {}
    for idx, (oc_comp_id, oc_bra_id, oc_poh_id) in enumerate(triples):
        or_clauses.append(f"(d.comp_id = :comp_{idx} AND d.bra_id = :bra_{idx} AND d.poh_id = :poh_{idx})")
        lineas_params[f"comp_{idx}"] = oc_comp_id
        lineas_params[f"bra_{idx}"] = oc_bra_id
        lineas_params[f"poh_{idx}"] = oc_poh_id

    stmt_lineas = text(
        f"""
        SELECT d.comp_id,
               d.bra_id,
               d.poh_id,
               d.pod_id,
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
        WHERE {" OR ".join(or_clauses)}
        ORDER BY d.comp_id, d.bra_id, d.poh_id, d.pod_id
        """
    )
    # Query B — accumulated ingresos from pricing-app, scoped per OC triple
    stmt_ingresos = text(
        """
        SELECT oc_poh_id, pod_id, COALESCE(SUM(cantidad_recibida), 0) AS recibido_pricing
        FROM pedido_compra_ingresos
        WHERE pedido_id = :pedido_id AND pod_id IS NOT NULL
        GROUP BY oc_poh_id, pod_id
        """
    )
    ingreso_rows = session.execute(stmt_ingresos, {"pedido_id": pedido.id}).all()
    recibido_by_oc_pod: dict[tuple[int | None, int], Decimal] = {
        (int(r[0]) if r[0] is not None else None, int(r[1])): Decimal(str(r[2])) for r in ingreso_rows
    }

    lineas: list[SaldoLineaResponse] = []
    oc_rows = session.execute(stmt_lineas, lineas_params).all()
    for row in oc_rows:
        oc_comp_id = int(row[0])
        oc_bra_id = int(row[1])
        oc_poh_id = int(row[2])
        pod_id = int(row[3])
        item_id = int(row[4]) if row[4] is not None else None
        stor_id = int(row[5]) if row[5] is not None else None
        deposito_nombre: str | None = row[6]
        pod_qty = Decimal(str(row[7] or 0))
        pod_confirmedqty = Decimal(str(row[8] or 0))
        raw_nombre: str | None = row[9]
        item_code: str | None = row[10]
        item_nombre = raw_nombre if raw_nombre is not None else (str(item_id) if item_id is not None else None)

        recibido_pricing = recibido_by_oc_pod.get((oc_poh_id, pod_id), Decimal("0"))
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
                oc_comp_id=oc_comp_id,
                oc_bra_id=oc_bra_id,
                oc_poh_id=oc_poh_id,
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
    touched_triples: set[tuple[int, int, int]] | None = None,
) -> str:
    """Transition pedido.estado based on remaining balances after a receipt batch.

    Args:
        oc_lineas_saldos: list of dicts with keys 'pod_id' and 'saldo' (Decimal).
            Optional 'oc_comp_id'/'oc_bra_id'/'oc_poh_id' for multi-OC grouping.
        touched_triples: OC identities controlled in this batch (D-MULTI).

    Returns:
        The new estado string ('controlado', 'recibido', or 'con_faltantes').
    """
    triples = triples_for_pedido(session, pedido)
    all_zero = all(Decimal(str(l["saldo"])) <= Decimal("0") for l in oc_lineas_saldos)
    if len(triples) <= 1:
        nuevo_estado = "controlado" if all_zero else "con_faltantes"
        pedido.estado = nuevo_estado
        return nuevo_estado

    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    untagged: list[dict[str, Any]] = []
    for line in oc_lineas_saldos:
        poh = line.get("oc_poh_id")
        if poh is None:
            untagged.append(line)
            continue
        key = (int(line.get("oc_comp_id") or 0), int(line.get("oc_bra_id") or 0), int(poh))
        grouped.setdefault(key, []).append(line)

    def _complete(triple: tuple[int, int, int]) -> bool:
        lines = grouped.get(triple) or []
        if not lines and untagged and triple == triples[0]:
            lines = untagged
        if not lines:
            return False
        return all(Decimal(str(l["saldo"])) <= Decimal("0") for l in lines)

    if all(_complete(t) for t in triples):
        nuevo_estado = "controlado"
    elif touched_triples and all(_complete(t) for t in touched_triples):
        nuevo_estado = "recibido"
    else:
        nuevo_estado = "con_faltantes"
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

    linked = triples_for_pedido(session, pedido)
    if not linked and pedido.oc_poh_id is None:
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

    def _match_linea(pod_id: int) -> SaldoLineaResponse:
        matches = [l for l in pre_saldos_resp.lineas if l.pod_id == pod_id]
        if not matches:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"pod_id {pod_id} not found in linked OC",
            )
        if len(matches) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"pod_id {pod_id} is ambiguous across linked OCs",
            )
        return matches[0]

    matched: dict[int, SaldoLineaResponse] = {linea.pod_id: _match_linea(linea.pod_id) for linea in lineas_validas}

    # Step 5 — over-receipt check (fail BEFORE any INSERT)
    for linea in lineas_validas:
        saldo_actual = matched[linea.pod_id].saldo_pendiente
        if linea.cantidad_recibida > saldo_actual:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Over-receipt: pod_id {linea.pod_id} — "
                    f"saldo pendiente es {saldo_actual}, solicitado {linea.cantidad_recibida}"
                ),
            )

    stmt_pod = text(
        """
        SELECT pod_id, item_id, stor_id
        FROM tb_purchase_order_detail
        WHERE comp_id = :comp AND bra_id = :bra AND poh_id = :poh
          AND pod_id IN :pod_ids
        """
    ).bindparams(bindparam("pod_ids", expanding=True))

    pod_detail: dict[tuple[int | None, int], dict[str, Any]] = {}
    by_oc: dict[tuple[int | None, int | None, int | None], list[int]] = {}
    for linea in lineas_validas:
        saldo_linea = matched[linea.pod_id]
        oc_key = (
            saldo_linea.oc_comp_id if saldo_linea.oc_comp_id is not None else pedido.oc_comp_id,
            saldo_linea.oc_bra_id if saldo_linea.oc_bra_id is not None else pedido.oc_bra_id,
            saldo_linea.oc_poh_id if saldo_linea.oc_poh_id is not None else pedido.oc_poh_id,
        )
        by_oc.setdefault(oc_key, []).append(linea.pod_id)
    for oc_comp, oc_bra, oc_poh, pod_ids in ((k[0], k[1], k[2], v) for k, v in by_oc.items()):
        pod_rows = session.execute(
            stmt_pod,
            {"comp": oc_comp, "bra": oc_bra, "poh": oc_poh, "pod_ids": pod_ids},
        ).all()
        for row in pod_rows:
            pod_detail[(oc_poh, int(row[0]))] = {
                "item_id": int(row[1]) if row[1] else None,
                "stor_id": int(row[2]) if row[2] else None,
            }

    # Step 6 — INSERT one row per non-zero line, stamped with the matched OC
    ingresos_creados: list[PedidoCompraIngreso] = []
    for linea in lineas_validas:
        saldo_linea = matched[linea.pod_id]
        oc_comp = saldo_linea.oc_comp_id if saldo_linea.oc_comp_id is not None else pedido.oc_comp_id
        oc_bra = saldo_linea.oc_bra_id if saldo_linea.oc_bra_id is not None else pedido.oc_bra_id
        oc_poh = saldo_linea.oc_poh_id if saldo_linea.oc_poh_id is not None else pedido.oc_poh_id
        detail = pod_detail.get((oc_poh, linea.pod_id), {})
        ingreso = PedidoCompraIngreso(
            pedido_id=pedido.id,
            oc_comp_id=oc_comp,
            oc_bra_id=oc_bra,
            oc_poh_id=oc_poh,
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
    saldos_lista = [
        {
            "pod_id": l.pod_id,
            "saldo": l.saldo_pendiente,
            "oc_comp_id": l.oc_comp_id,
            "oc_bra_id": l.oc_bra_id,
            "oc_poh_id": l.oc_poh_id,
        }
        for l in post_saldos_resp.lineas
    ]
    touched = {
        (int(ing.oc_comp_id), int(ing.oc_bra_id), int(ing.oc_poh_id))
        for ing in ingresos_creados
        if ing.oc_poh_id is not None
    }
    nuevo_estado = recalcular_estado(session, pedido, saldos_lista, touched_triples=touched)
    session.flush()  # persist estado update so callers see the new value

    # Step 8 — emit event
    if nuevo_estado == "controlado":
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
            "faltantes_texto": request.faltantes_texto,
        },
    )

    if nuevo_estado == "con_faltantes":
        texto = _texto_faltantes(request.faltantes_texto, request.observaciones)
        if not texto:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="faltantes_texto is required when marking faltantes.",
            )
        _alertar_faltantes_si_corresponde(session, pedido, texto)

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
    """Confirm reception at pedido level — SIN-OC path (D-SINOC truth table).

    Two-step logic derived from current estado:
      - estado in ESTADOS_ARRIBO + any → recibido  (ARRIVAL step; completo ignored)
        i.e. 'pagado' or 'en_cuenta_corriente' — both are arrival-entry states
      - recibido + True   → controlado  (CONTROL step: complete)
      - recibido + False  → con_faltantes
      - con_faltantes + True  → controlado
      - con_faltantes + False → con_faltantes (stays, partial again)
      - controlado + any  → 409 terminal

    Writes a sentinel row in pedido_compra_ingresos (pod_id=NULL,
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

    # D-SINOC routing: arrival vs control step
    if pedido.estado in ESTADOS_ARRIBO:
        # ARRIVAL step — record logistics fact; completo is ignored
        nuevo_estado = "recibido"
        tipo_evento = "recepcion_arribo"
    elif pedido.estado in {"recibido", "con_faltantes"}:
        # CONTROL step — evaluate completeness
        nuevo_estado = "controlado" if request.completo else "con_faltantes"
        tipo_evento = "recepcion_registrada" if request.completo else "recepcion_con_faltantes"
    else:
        # Unreachable while ESTADOS_ARRIBO | {'recibido', 'con_faltantes'} covers
        # every state `_validar_estado_receptivo` lets through. Kept as a fail-loud
        # net: if a new receptive state is added upstream without a branch here,
        # this rejects it explicitly instead of silently mis-transitioning.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pedido not in a receivable state (estado='{pedido.estado}')",
        )

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

    pedido.estado = nuevo_estado

    _emit_evento(
        session,
        pedido=pedido,
        user=user,
        tipo=tipo_evento,
        payload={
            "modo": "sin_oc",
            "completo": request.completo,
            "observaciones": request.observaciones,
            "faltantes_texto": request.faltantes_texto,
            "requiere_envio": bool(pedido.requiere_envio),
            "retiro_generado": False,
        },
    )

    session.flush()

    if nuevo_estado == "con_faltantes":
        texto = _texto_faltantes(request.faltantes_texto, request.observaciones)
        if not texto:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="faltantes_texto is required when marking faltantes.",
            )
        _alertar_faltantes_si_corresponde(session, pedido, texto)

    return ConfirmarPedidoResponse(
        pedido_id=pedido.id,
        estado_nuevo=nuevo_estado,
    )


# ──────────────────────────────────────────────────────────────────────────
# RD-A.8b — confirmar_arribo_con_oc (D-CONOC arrival, state-only)
# ──────────────────────────────────────────────────────────────────────────


def confirmar_arribo_con_oc(
    session: Session,
    pedido: PedidoCompra,
    user: Usuario,
) -> ConfirmarPedidoResponse:
    """State-only arrival transition for CON-OC pedidos: pagado → recibido.

    Does NOT create ingresos lines (counting happens via /recepcion/ingresos
    at the control step). Writes a sentinel row for WHO/WHEN auditing and
    emits 'recepcion_arribo'.

    Raises:
        HTTPException 409 — pedido has no OC linked (use confirmar_pedido_sin_oc).
        HTTPException 409 — pedido estado not in ESTADOS_ARRIBO ('pagado' /
            'en_cuenta_corriente') — only the arrival step is accepted here.
    """
    if pedido.oc_poh_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido has no linked OC. Use /recepcion/confirmar-pedido instead.",
        )

    _validar_estado_receptivo(pedido)

    if pedido.estado not in ESTADOS_ARRIBO:
        estados_validos = " or ".join(f"'{e}'" for e in sorted(ESTADOS_ARRIBO))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"CON-OC arrival only valid from {estados_validos} "
                f"(current estado='{pedido.estado}'). Use /recepcion/ingresos for the control step."
            ),
        )

    # Sentinel row — pod_id=NULL marks arrival confirmations without line counting
    sentinel = PedidoCompraIngreso(
        pedido_id=pedido.id,
        pod_id=None,
        oc_comp_id=pedido.oc_comp_id,
        oc_bra_id=pedido.oc_bra_id,
        oc_poh_id=pedido.oc_poh_id,
        item_id=None,
        stor_id=None,
        cantidad_recibida=Decimal("1"),
        usuario_id=user.id,
        observaciones=None,
    )
    session.add(sentinel)

    pedido.estado = "recibido"

    _emit_evento(
        session,
        pedido=pedido,
        user=user,
        tipo="recepcion_arribo",
        payload={
            "modo": "con_oc",
            "requiere_envio": bool(pedido.requiere_envio),
            "retiro_generado": False,
        },
    )

    session.flush()

    return ConfirmarPedidoResponse(
        pedido_id=pedido.id,
        estado_nuevo="recibido",
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
            CompraEvento.tipo.in_(
                [
                    "recepcion_registrada",
                    "recepcion_con_faltantes",
                    "recepcion_arribo",
                    "recepcion_undo_recibido",
                ]
            ),
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


def deshacer_recibido(
    session: Session,
    pedido: PedidoCompra,
    user: Usuario,
) -> DeshacerRecibidoResponse:
    """Undo `recibido` back to a waiting-for-goods state (D-UNDO-R).

    Restores `en_cuenta_corriente` when the CC OP is still open
    (`op_cuenta_corriente_id` set and `pagado_en` empty); otherwise `pagado`.
    `controlado` is terminal (409). Servicio is rejected (409).
    """
    _validar_no_servicio(pedido)
    if pedido.estado == "controlado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pedido already controlled",
        )
    if pedido.estado != "recibido":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Undo recibido only from estado='recibido' (estado='{pedido.estado}')",
        )

    if pedido.op_cuenta_corriente_id is not None and pedido.pagado_en is None:
        nuevo_estado = "en_cuenta_corriente"
    else:
        nuevo_estado = "pagado"

    pedido.estado = nuevo_estado
    _emit_evento(
        session,
        pedido=pedido,
        user=user,
        tipo="recepcion_undo_recibido",
        payload={
            "estado_anterior": "recibido",
            "estado_nuevo": nuevo_estado,
        },
    )
    session.flush()
    return DeshacerRecibidoResponse(pedido_id=pedido.id, estado_nuevo=nuevo_estado)


def resolver_faltantes(
    session: Session,
    pedido: PedidoCompra,
    user: Usuario,
    texto: str | None = None,
    *,
    ahora: datetime | None = None,
) -> ResolverFaltantesResponse:
    """Mark faltantes resolved and fan-out G31 to deposito.recibir_mercaderia."""
    if pedido.estado != "con_faltantes":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Solo se resuelven faltantes en estado con_faltantes (estado='{pedido.estado}').",
        )
    stamp = ahora if ahora is not None else datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    pedido.faltantes_resuelto_en = stamp
    _emit_evento(
        session,
        pedido=pedido,
        user=user,
        tipo="faltantes_resuelto",
        payload={"texto": texto, "faltantes_resuelto_en": stamp.isoformat()},
    )
    from app.services import compras_alertas_service

    if pedido.proveedor is None:
        session.refresh(pedido, attribute_names=["proveedor"])
    compras_alertas_service.notificar_faltantes_resuelto(session, pedido=pedido)
    session.flush()
    return ResolverFaltantesResponse(pedido_id=pedido.id, faltantes_resuelto_en=stamp)
