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
    # Propios — Slice 4
    ("propio", "emitido", "debitar"): "debitado",
    ("propio", "diferido", "debitar"): "debitado",
    ("propio", "emitido", "rechazar"): "rechazado",
    ("propio", "diferido", "rechazar"): "rechazado",
    # Terceros — Slice 2
    ("tercero", "en_cartera", "entregar"): "entregado",  # endoso a proveedor en OP
    ("tercero", "en_cartera", "anular"): "anulado",
    ("tercero", "en_cartera", "rechazar"): "rechazado",
    ("tercero", "entregado", "rechazar"): "rechazado",
    # Terceros — Slice 4
    ("tercero", "en_cartera", "depositar"): "depositado",
    ("tercero", "aceptado", "depositar"): "depositado",
    ("tercero", "depositado", "acreditar"): "acreditado",
    # e-cheq en_custodia → acreditar (Slice 4 le da salida a en_custodia)
    ("tercero", "en_custodia", "acreditar"): "acreditado",
    ("propio", "en_custodia", "acreditar"): "acreditado",
    # ── Slice 3 — e-cheq (instrumento == 'echeq' only; validado en transicionar_cheque) ──
    #
    # Terceros e-cheq: aceptación bancaria
    #   en_cartera --[aceptar]--> aceptado       (banco acepta el e-cheq; pasa a ser utilizable)
    #   en_cartera --[rechazar_emision]--> rechazado_emision  (banco rechaza antes de aceptar)
    #   aceptado   --[entregar]--> entregado      (endoso desde estado aceptado)
    #   aceptado   --[rechazar_emision]--> rechazado_emision  (banco rechaza post-aceptación)
    #   aceptado   --[anular]--> anulado
    #
    # NOTA DISEÑO: "aceptar" es OPCIONAL para e-cheq tercero. Un e-cheq en_cartera ya es
    # endosable directamente (en_cartera --[entregar]--> entregado), igual que un cheque
    # físico. aceptar/rechazar_emision reflejan el ciclo BCRA pero NO son obligatorios
    # en Slice 3 (sin integración bancaria real). La transición en_cartera→entregar está
    # disponible para TODOS los instrumentos de tercero (ver TRANSICIONES_CHEQUE de Slice 2).
    #
    # E-cheq propios y terceros: custodia (depósito automático al vencimiento)
    #   emitido    --[poner_en_custodia]--> en_custodia  (propio e-cheq)
    #   diferido   --[poner_en_custodia]--> en_custodia  (propio e-cheq diferido)
    #   aceptado   --[poner_en_custodia]--> en_custodia  (tercero e-cheq aceptado)
    #   en_cartera --[poner_en_custodia]--> en_custodia  (tercero e-cheq, raro pero permitido)
    #
    # NOTE: custodia es manual en este slice — Slice 4 agrega integración bancaria real.
    ("tercero", "en_cartera", "aceptar"): "aceptado",
    ("tercero", "en_cartera", "rechazar_emision"): "rechazado_emision",
    ("tercero", "aceptado", "entregar"): "entregado",
    ("tercero", "aceptado", "rechazar_emision"): "rechazado_emision",
    ("tercero", "aceptado", "anular"): "anulado",
    ("tercero", "aceptado", "poner_en_custodia"): "en_custodia",
    ("tercero", "en_cartera", "poner_en_custodia"): "en_custodia",
    ("propio", "emitido", "poner_en_custodia"): "en_custodia",
    ("propio", "diferido", "poner_en_custodia"): "en_custodia",
}

# Estados terminales (no permiten más transiciones).
# Slice 4: en_custodia ya NO es terminal (puede acreditarse). Se agregan debitado/acreditado.
ESTADOS_TERMINALES: Final[frozenset[str]] = frozenset(
    {"anulado", "rechazado", "rechazado_emision", "debitado", "acreditado"}
)

# Acciones exclusivas de e-cheq; se rechazan con 422 si instrumento == 'fisico'.
ACCIONES_ECHEQ: Final[frozenset[str]] = frozenset({"aceptar", "rechazar_emision", "poner_en_custodia"})


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

    # Acciones exclusivas de e-cheq — cheques físicos no pueden usarlas.
    if accion in ACCIONES_ECHEQ and cheque.instrumento != "echeq":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La acción '{accion}' es exclusiva de e-cheq. "
                f"El cheque id={cheque.id} es instrumento='{cheque.instrumento}'."
            ),
        )

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


# ──────────────────────────────────────────────────────────────────────────
# Slice 4 — Conciliación bancaria
# ──────────────────────────────────────────────────────────────────────────


def debitar_cheque(
    db: Session,
    cheque: Cheque,
    *,
    fecha: date,
    usuario_id: Optional[int] = None,
) -> Cheque:
    """Marca un cheque propio como debitado (el banco lo débita de la cuenta).

    Transiciones válidas: emitido → debitado, diferido → debitado.
    Genera un BancoMovimiento de EGRESO en el banco del cheque.

    Validaciones:
      - FR-4.3: no antes de fecha_pago (422).
      - Moneda del cheque debe coincidir con moneda del banco (422).
      - El banco_empresa_id debe existir en el cheque (422 si no).

    Args:
        db: sesión activa.
        cheque: instancia del Cheque (tipo='propio', estado emitido|diferido).
        fecha: fecha real del débito (generalmente hoy o fecha_pago).
        usuario_id: id del usuario que ejecuta la acción.

    Returns:
        El Cheque actualizado a estado 'debitado'.

    Raises:
        HTTPException 422: fecha antes de fecha_pago, moneda no coincide, banco no encontrado.
    """
    from app.models.banco_empresa import BancoEmpresa  # noqa: PLC0415
    from app.services.banco_service import BancoService  # noqa: PLC0415

    # FR-4.3: no debitar antes de fecha_pago
    if fecha < cheque.fecha_pago:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No se puede debitar antes de la fecha de pago. "
                f"fecha_pago={cheque.fecha_pago.isoformat()}, fecha_accion={fecha.isoformat()}."
            ),
        )

    if cheque.banco_empresa_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El cheque id={cheque.id} no tiene banco_empresa_id asignado.",
        )

    banco = db.query(BancoEmpresa).filter(BancoEmpresa.id == cheque.banco_empresa_id).first()
    if banco is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BancoEmpresa id={cheque.banco_empresa_id} no encontrado.",
        )

    # Validar moneda
    if str(banco.moneda) != str(cheque.moneda):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La moneda del banco ({banco.moneda}) no coincide con la moneda del cheque ({cheque.moneda}). "
                "No se puede debitar en moneda distinta."
            ),
        )

    # Aplicar transición vía máquina de estados estándar
    transicionar_cheque(db, cheque, "debitar", usuario_id=usuario_id)

    # Registrar movimiento bancario de EGRESO
    svc = BancoService(db)
    movimiento = svc.registrar_movimiento(
        banco_id=cheque.banco_empresa_id,
        fecha=fecha,
        detalle=f"Débito cheque #{cheque.numero} (id={cheque.id})",
        tipo="egreso",
        monto=Decimal(str(cheque.monto)),
        user_id=usuario_id,
        origen="cheque_debitado",
    )

    # Actualizar evento con referencia al movimiento bancario
    _registrar_evento(
        db,
        cheque_id=cheque.id,
        tipo="banco_movimiento_egreso",
        payload={
            "banco_movimiento_id": movimiento.id,
            "banco_id": cheque.banco_empresa_id,
            "monto": str(cheque.monto),
            "moneda": str(cheque.moneda),
            "fecha": fecha.isoformat(),
        },
        usuario_id=usuario_id,
    )

    logger.info(
        "✅ Cheque propio debitado — id=%s numero=%s banco_id=%s monto=%s %s mov_id=%s",
        cheque.id,
        cheque.numero,
        cheque.banco_empresa_id,
        cheque.monto,
        cheque.moneda,
        movimiento.id,
    )
    return cheque


def depositar_cheque(
    db: Session,
    cheque: Cheque,
    *,
    banco_empresa_id: int,
    fecha: date,
    usuario_id: Optional[int] = None,
) -> Cheque:
    """Deposita un cheque de tercero en una cuenta bancaria de la empresa.

    Transiciones: en_cartera → depositado, aceptado → depositado.
    NO genera movimiento bancario (depositado ≠ acreditado).
    Registra banco_deposito_id en el cheque para luego acreditar.

    Validaciones:
      - FR-4.3: no antes de fecha_pago (422).
      - Moneda del banco destino debe coincidir con moneda del cheque (422).

    Args:
        db: sesión activa.
        cheque: instancia del Cheque (tipo='tercero', estado en_cartera|aceptado).
        banco_empresa_id: id de la cuenta bancaria destino del depósito.
        fecha: fecha del depósito.
        usuario_id: id del usuario que ejecuta la acción.

    Returns:
        El Cheque actualizado a estado 'depositado'.

    Raises:
        HTTPException 422: fecha antes de fecha_pago, moneda no coincide.
    """
    from app.models.banco_empresa import BancoEmpresa  # noqa: PLC0415

    # FR-4.3: no depositar antes de fecha_pago
    if fecha < cheque.fecha_pago:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No se puede depositar antes de la fecha de pago. "
                f"fecha_pago={cheque.fecha_pago.isoformat()}, fecha_accion={fecha.isoformat()}."
            ),
        )

    banco = db.query(BancoEmpresa).filter(BancoEmpresa.id == banco_empresa_id).first()
    if banco is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BancoEmpresa id={banco_empresa_id} no encontrado.",
        )

    # Validar moneda
    if str(banco.moneda) != str(cheque.moneda):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La moneda del banco destino ({banco.moneda}) no coincide con la moneda del cheque ({cheque.moneda}). "
                "No se puede depositar en moneda distinta."
            ),
        )

    # Guardar banco destino para usar al acreditar
    cheque.banco_deposito_id = banco_empresa_id

    # Aplicar transición
    transicionar_cheque(db, cheque, "depositar", usuario_id=usuario_id)

    # Agregar detalle del depósito al último evento (registrado por transicionar_cheque)
    _registrar_evento(
        db,
        cheque_id=cheque.id,
        tipo="deposito_banco",
        payload={
            "banco_deposito_id": banco_empresa_id,
            "banco_nombre": str(banco.banco),
            "fecha": fecha.isoformat(),
        },
        usuario_id=usuario_id,
    )

    logger.info(
        "✅ Cheque tercero depositado — id=%s numero=%s banco_destino_id=%s monto=%s %s",
        cheque.id,
        cheque.numero,
        banco_empresa_id,
        cheque.monto,
        cheque.moneda,
    )
    return cheque


def acreditar_cheque(
    db: Session,
    cheque: Cheque,
    *,
    fecha: date,
    usuario_id: Optional[int] = None,
) -> Cheque:
    """Acredita un cheque de tercero (depositado o en_custodia) en el banco.

    Transiciones: depositado → acreditado, en_custodia → acreditado.
    Genera un BancoMovimiento de INGRESO en el banco destino.

    Para en_custodia (e-cheq): el banco_deposito_id puede ser el banco_empresa_id
    del cheque (si es propio) o requerir ser seteado antes.

    Validaciones:
      - Moneda del banco destino debe coincidir con moneda del cheque (422).
      - banco_deposito_id debe estar seteado (422 si no).

    Args:
        db: sesión activa.
        cheque: instancia del Cheque en estado depositado o en_custodia.
        fecha: fecha real de la acreditación.
        usuario_id: id del usuario que ejecuta la acción.

    Returns:
        El Cheque actualizado a estado 'acreditado'.

    Raises:
        HTTPException 422: banco no encontrado, moneda no coincide.
    """
    from app.models.banco_empresa import BancoEmpresa  # noqa: PLC0415
    from app.services.banco_service import BancoService  # noqa: PLC0415

    # FR-4.3: no acreditar antes de fecha_pago
    if fecha < cheque.fecha_pago:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No se puede acreditar antes de la fecha de pago. "
                f"fecha_pago={cheque.fecha_pago.isoformat()}, fecha_accion={fecha.isoformat()}."
            ),
        )

    # Determinar banco destino: banco_deposito_id (terceros depositados) o banco_empresa_id (propios en_custodia)
    banco_id = cheque.banco_deposito_id or cheque.banco_empresa_id

    if banco_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"El cheque id={cheque.id} no tiene banco destino asignado. "
                "Para cheques de tercero: ejecutar depositar_cheque primero. "
                "Para e-cheq en custodia: setear banco_deposito_id antes de acreditar."
            ),
        )

    banco = db.query(BancoEmpresa).filter(BancoEmpresa.id == banco_id).first()
    if banco is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BancoEmpresa id={banco_id} no encontrado.",
        )

    # Validar moneda
    if str(banco.moneda) != str(cheque.moneda):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La moneda del banco ({banco.moneda}) no coincide con la moneda del cheque ({cheque.moneda}). "
                "No se puede acreditar en moneda distinta."
            ),
        )

    # Para en_custodia necesitamos bypass del check de ESTADOS_TERMINALES anterior.
    # en_custodia NO está en ESTADOS_TERMINALES desde Slice 4, así que transicionar_cheque funciona.
    # La acción 'acreditar' es válida para depositado→acreditado y en_custodia→acreditado.
    transicionar_cheque(db, cheque, "acreditar", usuario_id=usuario_id)

    # Registrar movimiento bancario de INGRESO
    svc = BancoService(db)
    movimiento = svc.registrar_movimiento(
        banco_id=banco_id,
        fecha=fecha,
        detalle=f"Acreditación cheque #{cheque.numero} (id={cheque.id})",
        tipo="ingreso",
        monto=Decimal(str(cheque.monto)),
        user_id=usuario_id,
        origen="cheque_acreditado",
    )

    _registrar_evento(
        db,
        cheque_id=cheque.id,
        tipo="banco_movimiento_ingreso",
        payload={
            "banco_movimiento_id": movimiento.id,
            "banco_id": banco_id,
            "monto": str(cheque.monto),
            "moneda": str(cheque.moneda),
            "fecha": fecha.isoformat(),
        },
        usuario_id=usuario_id,
    )

    logger.info(
        "✅ Cheque acreditado — id=%s numero=%s banco_id=%s monto=%s %s mov_id=%s",
        cheque.id,
        cheque.numero,
        banco_id,
        cheque.monto,
        cheque.moneda,
        movimiento.id,
    )
    return cheque


def get_reporte_cheques(
    db: Session,
    *,
    hoy: Optional[date] = None,
) -> dict[str, list[Cheque]]:
    """Reporte de cheques agrupado por segmento (FR-4.4).

    Segmentos:
      - en_cartera: terceros en estado en_cartera o aceptado (disponibles).
      - a_debitar: propios en emitido|diferido con fecha_pago <= hoy (listos para debitar).
      - vencidos: cualquier cheque activo con fecha_pago < hoy y aún no terminal.

    Args:
        db: sesión activa.
        hoy: fecha de referencia (default: date.today()).

    Returns:
        Dict con claves 'en_cartera', 'a_debitar', 'vencidos'.
    """
    from datetime import date as _date  # noqa: PLC0415

    ref = hoy or _date.today()

    en_cartera = (
        db.query(Cheque)
        .filter(
            Cheque.tipo == "tercero",
            Cheque.estado.in_(["en_cartera", "aceptado"]),
        )
        .order_by(Cheque.fecha_pago)
        .all()
    )

    # Propios emitidos/diferidos listos para debitar (fecha_pago <= hoy)
    a_debitar = (
        db.query(Cheque)
        .filter(
            Cheque.tipo == "propio",
            Cheque.estado.in_(["emitido", "diferido"]),
            Cheque.fecha_pago <= ref,
        )
        .order_by(Cheque.fecha_pago)
        .all()
    )

    # Vencidos: cheques activos con fecha_pago < hoy que AÚN no fueron conciliados.
    # Segmentación sin solapamiento:
    #   - Propios (emitido|diferido): solo aparecen en 'vencidos' si fecha_pago < hoy
    #     (estrictamente) Y NO están en 'a_debitar' (que usa <= hoy). Como 'a_debitar'
    #     ya cubre propios emitido|diferido con fecha_pago <= hoy, cualquier propio
    #     con fecha_pago < hoy ya está en 'a_debitar'. Por lo tanto, propios
    #     emitido|diferido NO se incluyen aquí para evitar doble conteo.
    #   - Terceros (en_cartera|aceptado|depositado) con fecha_pago < hoy sí aparecen
    #     en vencidos (no tienen segmento propio equivalente a 'a_debitar').
    estados_vencidos_tercero = ["en_cartera", "aceptado", "depositado"]
    vencidos = (
        db.query(Cheque)
        .filter(
            Cheque.tipo == "tercero",
            Cheque.estado.in_(estados_vencidos_tercero),
            Cheque.fecha_pago < ref,
        )
        .order_by(Cheque.fecha_pago)
        .all()
    )

    return {
        "en_cartera": en_cartera,
        "a_debitar": a_debitar,
        "vencidos": vencidos,
    }


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
