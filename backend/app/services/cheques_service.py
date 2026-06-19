"""
cheques_service — Módulo de Cheques (Slice 1 backend core).

Implementa:
  - crear_chequera / listar_chequeras / proximo_numero.
  - emitir_cheque_propio: validaciones, estado inicial, evento.
  - TRANSICIONES_CHEQUE: dict (tipo, estado_origen, accion) -> estado_destino.
  - transicionar_cheque: aplica transición con validación + evento append-only.

Slice 1 alcance:
  - Propios: emitir, anular. Transiciones parciales listas para extensión.
  - NO imputa CC ni asocia OP en esta entrega (PR de integración OP es el siguiente).

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
    # Propios — Slice 4 (placeholder para no romper typing cuando se implemente)
    # ("propio", "emitido",  "debitar")  -> "debitado"   — Slice 4
    # ("propio", "diferido", "debitar")  -> "debitado"   — Slice 4
    # ("propio", "emitido",  "rechazar") -> "rechazado"  — Slice 4
    # ("propio", "diferido", "rechazar") -> "rechazado"  — Slice 4
    # Terceros — Slice 2 (placeholder)
    # ("tercero", "en_cartera", "entregar")  -> "entregado"   — Slice 2
    # ("tercero", "en_cartera", "depositar") -> "depositado"  — Slice 4
    # ("tercero", "en_cartera", "anular")    -> "anulado"     — Slice 2
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

    NO imputa CC en esta entrega (integración OP es el PR siguiente).
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


def _registrar_evento(
    db: Session,
    *,
    cheque_id: int,
    tipo: str,
    payload: Optional[dict],
    usuario_id: Optional[int],
) -> ChequeEvento:
    """Inserta un evento append-only en cheque_evento."""
    evento = ChequeEvento(
        cheque_id=cheque_id,
        tipo=tipo,
        payload=payload or {},
        usuario_id=usuario_id,
    )
    db.add(evento)
    return evento
