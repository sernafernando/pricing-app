"""
cheques_service — Módulo de Cheques (Slice 1 backend core).

Implementa:
  - crear_chequera / listar_chequeras / proximo_numero.
  - emitir_cheque_propio: validaciones, estado inicial, evento.
  - TRANSICIONES_CHEQUE: dict (tipo, estado_origen, accion) -> estado_destino.
  - transicionar_cheque: aplica transición con validación + evento append-only.

Alcance actual:
  - Propios: emitir, anular. Transiciones parciales listas para extensión.
  - Imputa CC del proveedor vía OP (ver _revertir_cc_si_linkeado).
  - Anular revierte la imputación: vía reversal de Imputacion (si hay pedido) o
    mediante movimiento 'debe' directo en cc_proveedor_movimientos (a cuenta).

Referencias:
  - openspec/changes/compras-cheques/design.md (máquina de estados, modelo de datos)
  - openspec/changes/compras-cheques/tasks.md T1.3, T1.4, T1.5
  - backend/app/services/pedidos_service.py (patrón TRANSICIONES_VALIDAS + eventos)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Final, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.cheque import Cheque, ChequeEvento, Chequera

logger = get_logger("services.cheques_service")


# ──────────────────────────────────────────────────────────────────────────
# Máquina de estados — Propios (Slice 1)
# ──────────────────────────────────────────────────────────────────────────
#
# La clave es (tipo, estado_origen, accion). Los slices futuros AGREGAN
# entradas al dict sin modificar las existentes.
#
# Nota: la transición "emitir" se maneja en emitir_cheque_propio directamente
# (el estado inicial depende de las fechas). Las transiciones aquí cubren
# cambios de estado POST-emisión.

TRANSICIONES_CHEQUE: Final[dict[tuple[str, str, str], str]] = {
    # Propios — Slice 1
    ("propio", "emitido", "anular"): "anulado",
    ("propio", "diferido", "anular"): "anulado",
    # Propios — Slice 4 (placeholder)
    # ("propio", "emitido",  "debitar")  -> "debitado"   — Slice 4
    # ("propio", "diferido", "debitar")  -> "debitado"   — Slice 4
    # ("propio", "emitido",  "rechazar") -> "rechazado"  — Slice 4
    # ("propio", "diferido", "rechazar") -> "rechazado"  — Slice 4
    # Terceros — Slice 2
    ("tercero", "en_cartera", "entregar"): "entregado",  # endoso a proveedor en OP
    ("tercero", "en_cartera", "anular"): "anulado",
    ("tercero", "en_cartera", "rechazar"): "rechazado",
    ("tercero", "entregado", "rechazar"): "rechazado",
    # Terceros — Slice 4 (placeholder)
    # ("tercero", "en_cartera", "depositar") -> "depositado"  — Slice 4
    # ("tercero", "depositado", "acreditar") -> "acreditado"  — Slice 4
}

# Estados terminales (no permiten más transiciones)
ESTADOS_TERMINALES: Final[frozenset[str]] = frozenset({"anulado", "rechazado"})


# ──────────────────────────────────────────────────────────────────────────
# Chequeras
# ──────────────────────────────────────────────────────────────────────────


def crear_chequera(
    db: Session,
    *,
    banco_empresa_id: int,
    descripcion: Optional[str],
    instrumento: str,
    numero_desde: Optional[int],
    numero_hasta: Optional[int],
    usuario_id: Optional[int],
) -> Chequera:
    """Registra una nueva chequera asociada a un banco propio.

    proximo_numero se inicializa igual a numero_desde (sugerido, editable).
    """
    chequera = Chequera(
        banco_empresa_id=banco_empresa_id,
        descripcion=descripcion,
        instrumento=instrumento,
        numero_desde=numero_desde,
        numero_hasta=numero_hasta,
        proximo_numero=numero_desde,
        activa=True,
        created_by=usuario_id,
    )
    db.add(chequera)
    logger.info("✅ Chequera creada — banco_empresa_id=%d instrumento=%s", banco_empresa_id, instrumento)
    return chequera


def listar_chequeras(
    db: Session,
    *,
    banco_empresa_id: Optional[int] = None,
    solo_activas: bool = False,
) -> list[Chequera]:
    """Lista chequeras, opcionalmente filtradas por banco y/o solo activas."""
    q = db.query(Chequera)
    if banco_empresa_id is not None:
        q = q.filter(Chequera.banco_empresa_id == banco_empresa_id)
    if solo_activas:
        q = q.filter(Chequera.activa.is_(True))
    return q.order_by(Chequera.id).all()


def proximo_numero(chequera: Chequera) -> int:
    """Retorna el próximo número sugerido de la chequera."""
    return chequera.proximo_numero or 1


# ──────────────────────────────────────────────────────────────────────────
# Emisión de cheque propio
# ──────────────────────────────────────────────────────────────────────────


def emitir_cheque_propio(
    db: Session,
    *,
    tipo: str,
    instrumento: str,
    numero: str,
    monto: Decimal,
    moneda: str,
    fecha_emision: date,
    fecha_pago: date,
    banco_empresa_id: int,
    chequera_id: Optional[int] = None,
    proveedor_id: Optional[int] = None,
    usuario_id: Optional[int] = None,
) -> Cheque:
    """Emite un cheque propio (standalone, sin OP).

    Reglas:
      - monto > 0 (422 si no).
      - fecha_pago >= fecha_emision (422 si no).
      - estado = 'emitido' si fecha_pago == fecha_emision, 'diferido' si fecha_pago > fecha_emision.
      - Avanza proximo_numero de la chequera si es físico.
      - Registra evento 'emitido' en cheque_evento.

    La imputación CC ocurre al asociar el cheque a una OP (ver routers de compras).
    Anular el cheque revierte esa imputación vía _revertir_cc_si_linkeado.
    """
    # Validaciones
    if tipo != "propio":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Este endpoint solo admite cheques propios; tipo recibido: '{tipo}'.",
        )
    if instrumento == "fisico" and chequera_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un cheque propio físico requiere chequera_id.",
        )
    if chequera_id is not None:
        chequera_obj = db.execute(select(Chequera).where(Chequera.id == chequera_id)).scalar_one_or_none()
        if chequera_obj is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Chequera id={chequera_id} no encontrada.",
            )
        if chequera_obj.banco_empresa_id != banco_empresa_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"La chequera id={chequera_id} pertenece al banco_empresa_id="
                    f"{chequera_obj.banco_empresa_id}, no al banco_empresa_id={banco_empresa_id} recibido."
                ),
            )
    if monto <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El monto del cheque debe ser mayor a cero.",
        )
    if fecha_pago < fecha_emision:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha de pago no puede ser anterior a la fecha de emisión.",
        )

    # Determinar estado inicial y es_diferido
    es_diferido = fecha_pago > fecha_emision
    estado_inicial = "diferido" if es_diferido else "emitido"

    cheque = Cheque(
        tipo=tipo,
        instrumento=instrumento,
        estado=estado_inicial,
        numero=numero,
        monto=monto,
        moneda=moneda,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        es_diferido=es_diferido,
        banco_empresa_id=banco_empresa_id,
        chequera_id=chequera_id,
        proveedor_id=proveedor_id,
        created_by=usuario_id,
    )
    db.add(cheque)

    # Avanzar próximo número en la chequera (fisico) — atomic: SELECT FOR UPDATE
    if chequera_id is not None and instrumento == "fisico":
        chequera_locked = db.execute(
            select(Chequera).where(Chequera.id == chequera_id).with_for_update()
        ).scalar_one_or_none()
        if chequera_locked is not None and chequera_locked.proximo_numero is not None:
            chequera_locked.proximo_numero = chequera_locked.proximo_numero + 1

    # Flush para obtener cheque.id antes de crear el evento
    db.flush()

    _registrar_evento(
        db,
        cheque_id=cheque.id,
        tipo="emitido",
        payload={
            "estado": estado_inicial,
            "monto": str(monto),
            "moneda": moneda,
            "fecha_emision": fecha_emision.isoformat(),
            "fecha_pago": fecha_pago.isoformat(),
        },
        usuario_id=usuario_id,
    )

    logger.info(
        "✅ Cheque propio emitido — id=%s numero=%s estado=%s monto=%s %s",
        cheque.id,
        numero,
        estado_inicial,
        monto,
        moneda,
    )
    return cheque


# ──────────────────────────────────────────────────────────────────────────
# Máquina de estados
# ──────────────────────────────────────────────────────────────────────────


def transicionar_cheque(
    db: Session,
    cheque: Cheque,
    accion: str,
    *,
    usuario_id: Optional[int] = None,
    motivo: Optional[str] = None,
    empresa_id: Optional[int] = None,
) -> Cheque:
    """Aplica una transición de estado al cheque.

    Valida contra TRANSICIONES_CHEQUE. Levanta 422 si la transición es inválida
    o si el estado actual es terminal.

    Para `anular`: requiere motivo (almacenado en cheque.motivo_anulacion).
    """
    estado_actual = cheque.estado

    # Estados terminales no permiten transiciones
    if estado_actual in ESTADOS_TERMINALES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El cheque está en estado terminal '{estado_actual}' y no puede transicionar.",
        )

    clave = (cheque.tipo, estado_actual, accion)
    estado_destino = TRANSICIONES_CHEQUE.get(clave)

    if estado_destino is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Transición inválida: ({cheque.tipo}, {estado_actual}) --[{accion}]--> ?",
        )

    # Campos adicionales por acción
    if accion == "anular":
        cheque.motivo_anulacion = motivo or ""
        # Revertir imputación CC si el cheque estaba linkeado a una OP.
        _revertir_cc_si_linkeado(db, cheque=cheque, usuario_id=usuario_id, empresa_id=empresa_id)

    cheque.estado = estado_destino

    _registrar_evento(
        db,
        cheque_id=cheque.id,
        tipo=estado_destino,
        payload={
            "accion": accion,
            "estado_anterior": estado_actual,
            "motivo": motivo,
        },
        usuario_id=usuario_id,
    )

    logger.info(
        "🔄 Cheque id=%s: %s -[%s]-> %s",
        cheque.id,
        estado_actual,
        accion,
        estado_destino,
    )
    return cheque


# ──────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────


def _revertir_cc_si_linkeado(
    db: Session,
    *,
    cheque: Cheque,
    usuario_id: Optional[int],
    empresa_id: Optional[int],
) -> None:
    """Revierte el movimiento CC del proveedor si el cheque estaba linkeado a una OP.

    Busca el OrdenPagoCheque del cheque; si existe, inserta un 'debe' en
    cc_proveedor_movimientos (reversal append-only) por el monto_op_moneda
    del link. Registra evento 'revertido_cc' en cheque_evento.

    Si el cheque no tiene link OP, no hace nada.
    """
    from app.models.cheque import OrdenPagoCheque  # noqa: PLC0415
    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.models.orden_pago import OrdenPago  # noqa: PLC0415

    if cheque.orden_pago_id is None:
        return

    link = db.execute(select(OrdenPagoCheque).where(OrdenPagoCheque.cheque_id == cheque.id)).scalar_one_or_none()

    if link is None:
        logger.warning(
            "⚠️ Cheque id=%s tiene orden_pago_id=%s pero no hay OrdenPagoCheque — skip reversal CC.",
            cheque.id,
            cheque.orden_pago_id,
        )
        return

    # Resolver empresa_id desde la OP si no se pasó explícitamente.
    eid = empresa_id
    if eid is None:
        op = db.get(OrdenPago, cheque.orden_pago_id)
        eid = int(op.empresa_id) if op is not None else None

    if eid is None:
        logger.error(
            "❌ No se pudo determinar empresa_id para reversal CC del cheque id=%s",
            cheque.id,
        )
        return

    from datetime import date as _date  # noqa: PLC0415

    from app.services import cc_proveedor_service, imputaciones_service, pedidos_service  # noqa: PLC0415

    # Detect whether this cheque was imputado via Imputacion (con pedido_id) or
    # via direct CC haber (a cuenta / old path).
    imp_pedido = db.execute(
        select(Imputacion).where(
            Imputacion.origen_tipo == "cheque",
            Imputacion.origen_id == cheque.id,
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.es_reversal.is_(False),
        )
    ).scalar_one_or_none()

    if imp_pedido is not None:
        # Caso A — cheque imputado a un pedido específico.
        # Revert via append-only reversal imputacion (mirrors NC/OP anulacion).
        reversals = imputaciones_service.revertir_imputaciones_de_origen(
            db,
            origen_tipo="cheque",
            origen_id=cheque.id,
            user_id=usuario_id,
            motivo=f"Cheque #{cheque.numero} anulado",
        )
        # Recalculate pedido state for every affected pedido.
        pedidos_afectados: set[int] = {
            int(r.destino_id) for r in reversals if r.destino_tipo == "pedido_compra" and r.destino_id is not None
        }
        for pid in pedidos_afectados:
            pedidos_service.aplicar_imputacion_a_pedido(db, pedido_id=pid, monto_imputado=Decimal("0"))

        _registrar_evento(
            db,
            cheque_id=cheque.id,
            tipo="revertido_cc",
            payload={
                "orden_pago_id": cheque.orden_pago_id,
                "monto_revertido": str(link.monto_op_moneda),
                "moneda": str(cheque.moneda),
                "via": "imputacion_reversal",
                "reversals_count": len(reversals),
            },
            usuario_id=usuario_id,
        )
        logger.info(
            "🔄 Imputacion revertida para cheque id=%s OP id=%s pedidos=%s monto=%s %s",
            cheque.id,
            cheque.orden_pago_id,
            sorted(pedidos_afectados),
            link.monto_op_moneda,
            cheque.moneda,
        )
    else:
        # Caso B — "a cuenta": append-only reversal via direct CC debe movement.
        if cheque.proveedor_id is None:
            logger.error(
                "❌ Cheque id=%s vinculado a OP id=%s sin proveedor_id ni imputacion a pedido — "
                "no se puede revertir CC directo. Revisá la integridad del link.",
                cheque.id,
                cheque.orden_pago_id,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"No se puede revertir la CC del cheque #{cheque.numero}: "
                    "falta proveedor_id y no hay imputación a pedido registrada."
                ),
            )
        cc_proveedor_service.insertar_mov(
            db,
            proveedor_id=cheque.proveedor_id,
            empresa_id=eid,
            fecha_movimiento=_date.today(),
            tipo="debe",
            monto=Decimal(str(link.monto_op_moneda)),
            moneda=str(cheque.moneda),
            origen_tipo="cheque_anulado",
            origen_id=cheque.id,
            descripcion=f"Reversal cheque #{cheque.numero} anulado (OP id={cheque.orden_pago_id})",
            creado_por_id=usuario_id,
        )

        _registrar_evento(
            db,
            cheque_id=cheque.id,
            tipo="revertido_cc",
            payload={
                "orden_pago_id": cheque.orden_pago_id,
                "monto_revertido": str(link.monto_op_moneda),
                "moneda": str(cheque.moneda),
                "via": "cc_directo",
            },
            usuario_id=usuario_id,
        )

        logger.info(
            "🔄 CC revertida para cheque id=%s OP id=%s monto=%s %s",
            cheque.id,
            cheque.orden_pago_id,
            link.monto_op_moneda,
            cheque.moneda,
        )


# ──────────────────────────────────────────────────────────────────────────
# Slice 2 — Cheques de terceros
# ──────────────────────────────────────────────────────────────────────────


def recibir_cheque_tercero(
    db: Session,
    *,
    banco_nombre: str,
    cuit_librador: str,
    librador_nombre: Optional[str] = None,
    numero: str,
    monto: Decimal,
    moneda: str,
    fecha_emision: date,
    fecha_pago: date,
    instrumento: str = "fisico",
    usuario_id: Optional[int] = None,
) -> Cheque:
    """Da de alta un cheque de tercero a la cartera (estado `en_cartera`).

    El cheque de tercero NO usa chequera/banco_empresa propio. Los campos
    banco_nombre y cuit_librador son obligatorios porque identifican al
    librador externo.

    Validaciones:
      - monto > 0 (422 si no).
      - fecha_pago >= fecha_emision (422 si no).
      - cuit_librador y banco_nombre son obligatorios.
      - estado inicial = 'en_cartera'.
      - Registra evento 'recibido'.

    Args:
        db: sesión activa.
        banco_nombre: nombre del banco del librador (texto libre).
        cuit_librador: CUIT del librador externo.
        librador_nombre: razón social o nombre del librador (opcional).
        numero: número del cheque físico o e-cheq.
        monto: monto del cheque.
        moneda: 'ARS' | 'USD'.
        fecha_emision: fecha de emisión del cheque.
        fecha_pago: fecha de pago / cobro del cheque.
        instrumento: 'fisico' | 'echeq'.
        usuario_id: id del usuario que lo registra.

    Returns:
        El Cheque creado en estado 'en_cartera'.

    Raises:
        HTTPException 422: validaciones fallidas.
    """
    if not banco_nombre or not banco_nombre.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="banco_nombre es requerido para cheques de tercero.",
        )
    if not cuit_librador or not cuit_librador.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cuit_librador es requerido para cheques de tercero.",
        )
    if monto <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El monto del cheque debe ser mayor a cero.",
        )
    if fecha_pago < fecha_emision:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha de pago no puede ser anterior a la fecha de emisión.",
        )

    es_diferido = fecha_pago > fecha_emision
    cheque = Cheque(
        tipo="tercero",
        instrumento=instrumento,
        estado="en_cartera",
        numero=numero,
        monto=monto,
        moneda=moneda,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        es_diferido=es_diferido,
        banco_nombre=banco_nombre,
        cuit_librador=cuit_librador,
        librador_nombre=librador_nombre,
        created_by=usuario_id,
    )
    db.add(cheque)
    db.flush()

    _registrar_evento(
        db,
        cheque_id=cheque.id,
        tipo="recibido",
        payload={
            "estado": "en_cartera",
            "banco_nombre": banco_nombre,
            "cuit_librador": cuit_librador,
            "monto": str(monto),
            "moneda": moneda,
            "fecha_emision": fecha_emision.isoformat(),
            "fecha_pago": fecha_pago.isoformat(),
        },
        usuario_id=usuario_id,
    )

    logger.info(
        "✅ Cheque tercero recibido — id=%s numero=%s banco=%s cuit=%s monto=%s %s",
        cheque.id,
        numero,
        banco_nombre,
        cuit_librador,
        monto,
        moneda,
    )
    return cheque


# NOTE: des_endosar_cheque_tercero was removed (dead code — no callers).
# The des-endorsement logic when canceling an OP lives in
# ordenes_pago_service._des_endosar_cheques_tercero_de_op, which handles
# the full context (op, empresa_id, linked imputaciones) correctly.


def registrar_evento(
    db: Session,
    *,
    cheque_id: int,
    tipo: str,
    payload: Optional[dict],
    usuario_id: Optional[int],
) -> ChequeEvento:
    """Inserta un evento append-only en cheque_evento (API pública)."""
    evento = ChequeEvento(
        cheque_id=cheque_id,
        tipo=tipo,
        payload=payload or {},
        usuario_id=usuario_id,
    )
    db.add(evento)
    return evento


# Alias interno para compatibilidad con llamadas dentro de este módulo.
_registrar_evento = registrar_evento
