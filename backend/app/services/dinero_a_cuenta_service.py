"""
dinero_a_cuenta_service — lifecycle del overpay real-money dentro del CC.

Dinero a cuenta es el componente real-money del saldo a favor del CC del
proveedor. Es un índice navegable sobre las imputaciones que lo originan
y consumen — NO es un ledger divorciado del CC (INV-2, AD-2).

El saldo consumible se DERIVA de las imputaciones (append-only, AD-3):
  saldo_disponible = monto - SUM(imputaciones origen='dinero_a_cuenta'
                                  no-reversal) + SUM(reversals)
Idéntico patrón al saldo_pendiente de NC local en imputaciones_service.

`estado` es un CACHE derivado. Fuente de verdad: las imputaciones.

PR2 implementa: crear, calcular_saldo_disponible, recalcular_estado,
listar_por_proveedor, calcular_componente_dinero_a_cuenta.
`consumir` se implementa en PR4 (necesita la whitelist PR4).

References:
  - design §3.1, AD-2, AD-3, AD-4
  - tasks T2.4
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.dinero_a_cuenta import DineroACuenta
from app.models.imputacion import Imputacion

logger = get_logger("services.dinero_a_cuenta_service")


# ──────────────────────────────────────────────────────────────────────────
# crear
# ──────────────────────────────────────────────────────────────────────────


def crear(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: int,
    monto: Decimal,
    moneda: str,
    origen_op_id: int,
    user_id: int,
) -> DineroACuenta:
    """
    Inserta una fila DineroACuenta con estado='disponible'.

    NO emite movimiento CC — el haber ya lo emite la imputación
    (orden_pago, dinero_a_cuenta) vía aplicar_imputacion (AD-6).

    Args:
        session: tx activa del caller.
        proveedor_id: FK proveedores.
        empresa_id: FK empresas.
        monto: monto original (inmutable). Debe ser > 0.
        moneda: 'ARS' o 'USD'.
        origen_op_id: FK ordenes_pago — la OP que lo creó.
        user_id: FK usuarios — quien ejecutó el pago.

    Returns:
        La fila DineroACuenta recién insertada (con id ya en sesión).

    Raises:
        HTTPException 400: monto <= 0 o moneda inválida.
    """
    if monto <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El monto de dinero a cuenta debe ser > 0 (recibido: {monto}).",
        )
    if moneda not in {"ARS", "USD"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Moneda inválida: '{moneda}'. Valores: 'ARS', 'USD'.",
        )

    dac = DineroACuenta(
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        monto=monto,
        moneda=moneda,
        estado="disponible",
        origen_op_id=origen_op_id,
        creado_por_id=user_id,
    )
    session.add(dac)
    session.flush()

    logger.info(
        "✅ DineroACuenta id=%s creado: proveedor=%s monto=%s %s origen_op=%s",
        dac.id,
        proveedor_id,
        monto,
        moneda,
        origen_op_id,
    )
    return dac


# ──────────────────────────────────────────────────────────────────────────
# calcular_saldo_disponible
# ──────────────────────────────────────────────────────────────────────────


def calcular_saldo_disponible(
    session: Session,
    dinero_a_cuenta_id: int,
) -> Decimal:
    """
    Calcula el saldo consumible de un DineroACuenta (AD-3).

    Fórmula (idéntica al saldo_pendiente de NC local):
      saldo = monto - SUM(imputaciones origen='dinero_a_cuenta' no-reversal)
                    + SUM(imputaciones origen='dinero_a_cuenta' reversal)

    Returns:
        Decimal — puede ser 0 si completamente consumido.

    Raises:
        HTTPException 404: si el id no existe.
    """
    dac = session.get(DineroACuenta, dinero_a_cuenta_id)
    if dac is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DineroACuenta id={dinero_a_cuenta_id} no encontrado.",
        )

    imputado_no_reversal = session.execute(
        select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.origen_tipo == "dinero_a_cuenta",
            Imputacion.origen_id == dinero_a_cuenta_id,
            Imputacion.es_reversal.is_(False),
        )
    ).scalar_one()

    imputado_reversal = session.execute(
        select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.origen_tipo == "dinero_a_cuenta",
            Imputacion.origen_id == dinero_a_cuenta_id,
            Imputacion.es_reversal.is_(True),
        )
    ).scalar_one()

    imputado_efectivo = Decimal(imputado_no_reversal) - Decimal(imputado_reversal)
    saldo = Decimal(dac.monto) - imputado_efectivo
    return max(Decimal("0"), saldo)


# ──────────────────────────────────────────────────────────────────────────
# recalcular_estado
# ──────────────────────────────────────────────────────────────────────────


def recalcular_estado(
    session: Session,
    dinero_a_cuenta_id: int,
) -> None:
    """
    Actualiza el campo `estado` del DineroACuenta según el saldo disponible.

    Transiciones (AD-3):
      saldo == monto  → 'disponible'
      0 < saldo < monto → 'consumido_parcial'
      saldo <= 0      → 'consumido'

    `estado` es un CACHE — la fuente de verdad son las imputaciones.
    Este update es el ÚNICO caso en que se modifica una fila de dinero_a_cuenta
    (el campo estado). Es el único UPDATE permitido por AD-3.
    """
    dac = session.get(DineroACuenta, dinero_a_cuenta_id)
    if dac is None:
        logger.warning("recalcular_estado: DineroACuenta id=%s no encontrado.", dinero_a_cuenta_id)
        return

    saldo = calcular_saldo_disponible(session, dinero_a_cuenta_id)
    monto = Decimal(dac.monto)

    if saldo >= monto:
        nuevo_estado = "disponible"
    elif saldo <= Decimal("0"):
        nuevo_estado = "consumido"
    else:
        nuevo_estado = "consumido_parcial"

    if dac.estado != nuevo_estado:
        dac.estado = nuevo_estado
        session.flush()
        logger.info(
            "🔄 DineroACuenta id=%s estado → '%s' (saldo=%s monto=%s)",
            dinero_a_cuenta_id,
            nuevo_estado,
            saldo,
            monto,
        )


# ──────────────────────────────────────────────────────────────────────────
# listar_por_proveedor
# ──────────────────────────────────────────────────────────────────────────


def listar_por_proveedor(
    session: Session,
    *,
    proveedor_id: int,
    moneda: Optional[str] = None,
    estado: Optional[str] = None,
    empresa_id: Optional[int] = None,
) -> list[DineroACuenta]:
    """
    Lista las filas DineroACuenta de un proveedor con filtros opcionales.

    Args:
        proveedor_id: FK proveedores.
        moneda: 'ARS' | 'USD'. Si None, devuelve todas las monedas.
        estado: 'disponible' | 'consumido_parcial' | 'consumido'. Si None, todos.
        empresa_id: si se provee, filtra por empresa.

    Returns:
        Lista ordenada por id ASC (orden de creación).
    """
    stmt = select(DineroACuenta).where(DineroACuenta.proveedor_id == proveedor_id)

    if moneda is not None:
        stmt = stmt.where(DineroACuenta.moneda == moneda)
    if estado is not None:
        stmt = stmt.where(DineroACuenta.estado == estado)
    if empresa_id is not None:
        stmt = stmt.where(DineroACuenta.empresa_id == empresa_id)

    stmt = stmt.order_by(DineroACuenta.id.asc())
    return list(session.execute(stmt).scalars().all())


# ──────────────────────────────────────────────────────────────────────────
# calcular_componente_dinero_a_cuenta
# ──────────────────────────────────────────────────────────────────────────


def calcular_componente_dinero_a_cuenta(
    session: Session,
    *,
    proveedor_id: int,
    moneda: str,
    empresa_id: Optional[int] = None,
) -> Decimal:
    """
    Suma el saldo disponible real de todas las filas de dinero a cuenta no
    completamente consumidas de un proveedor para una moneda dada (AD-8).

    - Per-moneda (INV-4): ARS y USD se calculan por separado.
    - Excluye filas con estado 'consumido'; incluye 'disponible' y
      'consumido_parcial' (estas últimas pueden tener saldo > 0).
    - El saldo de cada fila se calcula derivado de imputaciones (AD-3).
    - empresa_id: si se provee, filtra por empresa (coherencia con saldo CC).

    Returns:
        Decimal — suma de saldos disponibles. Decimal('0') si no hay filas.
    """
    # Traer filas no-completamente-consumidas de esa moneda
    filas = listar_por_proveedor(
        session,
        proveedor_id=proveedor_id,
        moneda=moneda,
        empresa_id=empresa_id,
        estado=None,  # filtramos abajo para incluir parciales
    )
    # Excluir completamente consumidas
    filas_activas = [f for f in filas if f.estado != "consumido"]

    if not filas_activas:
        return Decimal("0")

    dac_ids = [f.id for f in filas_activas]
    dac_montos = {f.id: Decimal(f.monto) for f in filas_activas}

    saldos = calcular_saldos_disponibles_batch(session, dac_ids, dac_montos)
    return sum((s for s in saldos.values() if s > Decimal("0")), Decimal("0"))


# ──────────────────────────────────────────────────────────────────────────
# calcular_saldos_disponibles_batch
# ──────────────────────────────────────────────────────────────────────────


def calcular_saldos_disponibles_batch(
    session: Session,
    dac_ids: list[int],
    dac_montos: dict[int, Decimal],
) -> dict[int, Decimal]:
    """
    Calcula el saldo disponible de múltiples filas DineroACuenta en 2 queries.

    Mismo cálculo que `calcular_saldo_disponible` pero batch: evita N queries
    al agrupar imputaciones por origen_id en una sola pasada.

    Args:
        session: sesión SQLAlchemy activa.
        dac_ids: lista de IDs de DineroACuenta a calcular.
        dac_montos: mapa {dac_id: monto_original} para derivar el saldo.

    Returns:
        dict {dac_id: saldo_disponible} — siempre >= 0.
    """
    if not dac_ids:
        return {}

    neto_no_reversal: dict[int, Decimal] = {
        row.origen_id: Decimal(row.total)
        for row in session.execute(
            select(Imputacion.origen_id, func.sum(Imputacion.monto_imputado).label("total"))
            .where(
                Imputacion.origen_tipo == "dinero_a_cuenta",
                Imputacion.origen_id.in_(dac_ids),
                Imputacion.es_reversal.is_(False),
            )
            .group_by(Imputacion.origen_id)
        ).all()
    }
    neto_reversal: dict[int, Decimal] = {
        row.origen_id: Decimal(row.total)
        for row in session.execute(
            select(Imputacion.origen_id, func.sum(Imputacion.monto_imputado).label("total"))
            .where(
                Imputacion.origen_tipo == "dinero_a_cuenta",
                Imputacion.origen_id.in_(dac_ids),
                Imputacion.es_reversal.is_(True),
            )
            .group_by(Imputacion.origen_id)
        ).all()
    }

    return {
        dac_id: max(
            Decimal("0"),
            dac_montos[dac_id] - neto_no_reversal.get(dac_id, Decimal("0")) + neto_reversal.get(dac_id, Decimal("0")),
        )
        for dac_id in dac_ids
    }


__all__ = [
    "crear",
    "calcular_saldo_disponible",
    "calcular_saldos_disponibles_batch",
    "recalcular_estado",
    "listar_por_proveedor",
    "calcular_componente_dinero_a_cuenta",
]
