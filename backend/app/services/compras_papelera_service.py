"""
compras_papelera_service — hard-delete auditable de basura.

Reglas de negocio (scope resuelto):

1. **Qué se puede eliminar** (método `puede_eliminar_pedido/op`):
   - Pedido: estado ∈ {borrador, cancelado}, NUNCA aprobado, SIN imputaciones.
     Si cancelado, espera `dias_retencion` desde `updated_at`.
   - OP: estado == 'anulado', SIN imputaciones vivas (no-reversal > reversal),
     NUNCA pasó por 'pagado' con movimiento vigente. Espera `dias_retencion`.
     Nota: la anulación de una OP pagada dispara reversals que deben
     cancelar el movimiento; si la suma neta > 0 todavía hay plata asociada
     y NO se permite borrar.

2. **Opción B — snapshot con eventos copiados**:
   Antes del delete físico se serializa la entidad a dict + se incluye
   la lista completa de eventos `compras_eventos` bajo la clave 'eventos'.
   Los eventos se borran JUNTO con la entidad (ya están en el snapshot).

3. **Opción C — batch puede_eliminar en listados**:
   `_calcular_puede_eliminar_{pedidos,ops}_batch` hace 3 queries fijas
   (aprobados, con_imputaciones, retención) sin importar el page size,
   devolviendo un dict {entidad_id: bool} para poblar el flag en los
   listados sin N+1.

**APPEND-ONLY sagrado**: `imputaciones` y `cc_proveedor_movimientos` NO
se tocan acá. Si hay movimientos vivos en una entidad, el hard-delete
se rechaza con HTTP 409 — la línea defensiva.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.compras_papelera import ComprasPapelera
from app.models.configuracion import Configuracion
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.usuario import Usuario

logger = get_logger("services.compras_papelera")

# Retención por defecto si la clave de configuracion no existe.
_DIAS_RETENCION_DEFAULT: int = 30
_CLAVE_RETENCION: str = "compras.dias_retencion_cancelados"

# Estados candidatos para hard-delete
_ESTADOS_PEDIDO_BORRABLES: frozenset[str] = frozenset({"borrador", "cancelado"})
_ESTADOS_OP_BORRABLES: frozenset[str] = frozenset({"anulado"})


# ==========================================================================
# Helpers internos
# ==========================================================================


def _leer_dias_retencion(session: Session) -> int:
    """Lee `compras.dias_retencion_cancelados` de `configuracion`.

    Fallback a `_DIAS_RETENCION_DEFAULT` si no existe o no parsea a int.
    """
    fila = session.query(Configuracion).filter(Configuracion.clave == _CLAVE_RETENCION).first()
    if fila is None or fila.valor is None:
        return _DIAS_RETENCION_DEFAULT
    try:
        val = int(str(fila.valor).strip())
    except (ValueError, InvalidOperation):
        logger.warning(
            "Configuracion '%s' tiene valor inválido: %r (fallback a %d)",
            _CLAVE_RETENCION,
            fila.valor,
            _DIAS_RETENCION_DEFAULT,
        )
        return _DIAS_RETENCION_DEFAULT
    return max(0, val)


def _updated_at_aware(entidad: PedidoCompra | OrdenPago) -> datetime | None:
    """Devuelve `updated_at` asegurando timezone UTC (tolerante a TIMESTAMP naive)."""
    updated = getattr(entidad, "updated_at", None)
    if updated is None:
        return None
    if updated.tzinfo is None:
        return updated.replace(tzinfo=UTC)
    return updated


def _paso_ventana_retencion(updated_at: datetime | None, cutoff: datetime) -> bool:
    """True si la entidad cumple la ventana de retención (updated_at <= cutoff)."""
    if updated_at is None:
        # Sin fecha: tratamos como "muy viejo" — permite borrar. No debería pasar
        # en producción porque `updated_at` es NOT NULL, pero en SQLite de tests
        # puede haber filas sincronizadas sin flush. Prudencia: permitir borrar.
        return True
    return updated_at <= cutoff


# ==========================================================================
# Reglas individuales (single-entity — usadas por el DELETE)
# ==========================================================================


def puede_eliminar_pedido(
    session: Session,
    pedido: PedidoCompra,
) -> tuple[bool, str | None]:
    """Evalúa si un pedido es hard-deletable.

    Retorna (puede, razon_si_no). Las razones son strings legibles que se
    propagan al HTTP 409 del router.
    """
    if pedido.estado not in _ESTADOS_PEDIDO_BORRABLES:
        return (
            False,
            f"Pedido en estado '{pedido.estado}'. Solo se pueden eliminar pedidos en borrador o cancelados.",
        )

    # Si alguna vez fue aprobado, hubo impacto en CC → NO se borra, aunque
    # hoy esté cancelado. Señal: existencia de evento tipo='aprobado'.
    fue_aprobado = bool(
        session.execute(
            select(sa_func.count())
            .select_from(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
                CompraEvento.tipo == "aprobado",
            )
        ).scalar_one()
        or 0
    )
    if fue_aprobado:
        return (
            False,
            "Pedido fue aprobado alguna vez — tuvo impacto contable. No se puede eliminar.",
        )

    # Defensa extra: cualquier imputación contra este pedido (aunque haya reversal)
    # es señal de que movió plata. NO tocamos imputaciones (append-only sagrado).
    tiene_imputaciones = bool(
        session.execute(
            select(sa_func.count())
            .select_from(Imputacion)
            .where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido.id,
            )
        ).scalar_one()
        or 0
    )
    if tiene_imputaciones:
        return (
            False,
            "Pedido tiene imputaciones asociadas. No se puede eliminar.",
        )

    # Si está cancelado, exigir ventana de retención
    if pedido.estado == "cancelado":
        dias = _leer_dias_retencion(session)
        cutoff = datetime.now(UTC) - timedelta(days=dias)
        if not _paso_ventana_retencion(_updated_at_aware(pedido), cutoff):
            return (
                False,
                (f"Pedido cancelado hace menos de {dias} días. Esperá el período de retención antes de eliminarlo."),
            )

    return True, None


def puede_eliminar_op(
    session: Session,
    op: OrdenPago,
) -> tuple[bool, str | None]:
    """Evalúa si una OP es hard-deletable.

    Solo OPs en estado 'anulado', sin imputaciones netas vivas y que
    hayan superado la ventana de retención.
    """
    if op.estado not in _ESTADOS_OP_BORRABLES:
        return (
            False,
            f"OP en estado '{op.estado}'. Solo se pueden eliminar OPs anuladas.",
        )

    # Imputaciones netas: toda imputación (no-reversal) con origen en esta OP.
    # Si hay una imputación no-reversal sin su correspondiente reversal, la OP
    # movió plata y NO se puede borrar.
    no_reversal = int(
        session.execute(
            select(sa_func.count())
            .select_from(Imputacion)
            .where(
                Imputacion.origen_tipo == "orden_pago",
                Imputacion.origen_id == op.id,
                Imputacion.es_reversal.is_(False),
            )
        ).scalar_one()
        or 0
    )
    reversals = int(
        session.execute(
            select(sa_func.count())
            .select_from(Imputacion)
            .where(
                Imputacion.origen_tipo == "orden_pago",
                Imputacion.origen_id == op.id,
                Imputacion.es_reversal.is_(True),
            )
        ).scalar_one()
        or 0
    )
    if no_reversal > reversals:
        return (
            False,
            (
                f"OP tiene {no_reversal - reversals} imputación/es viva/s "
                "(no-reversal - reversal > 0). No se puede eliminar."
            ),
        )

    # Si aún tiene movimiento de caja asociado (caja_movimiento_id NOT NULL),
    # eso significa que al anular no se revirtió la caja — es caso raro pero
    # defensivo rechazar porque el hard-delete dejaría la caja inconsistente.
    if op.caja_movimiento_id is not None:
        return (
            False,
            ("OP anulada todavía referencia un movimiento de caja. Revisá el flujo de anulación antes de eliminar."),
        )

    dias = _leer_dias_retencion(session)
    cutoff = datetime.now(UTC) - timedelta(days=dias)
    if not _paso_ventana_retencion(_updated_at_aware(op), cutoff):
        return (
            False,
            (f"OP anulada hace menos de {dias} días. Esperá el período de retención antes de eliminarla."),
        )

    return True, None


# ==========================================================================
# Opción C — batch queries para listados
# ==========================================================================


def _calcular_puede_eliminar_pedidos_batch(
    session: Session,
    pedidos: list[PedidoCompra],
) -> dict[int, bool]:
    """3 queries fijas sin importar el page size. Retorna {pedido_id: puede}.

    Diseño (opción C del scope):
      Query 1: set de pedido_ids que tienen evento tipo='aprobado'.
      Query 2: set de pedido_ids con AL MENOS una imputación (cualquier tipo).
      Query 3: lectura única de `dias_retencion` para el cutoff de cancelados.

    Luego iteramos pedidos en memoria comparando contra los sets. Cost:
    O(N) memoria + 3 queries constantes.
    """
    if not pedidos:
        return {}

    pedido_ids = [p.id for p in pedidos]

    aprobados_ids: set[int] = set(
        session.execute(
            select(CompraEvento.entidad_id)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id.in_(pedido_ids),
                CompraEvento.tipo == "aprobado",
            )
            .distinct()
        )
        .scalars()
        .all()
    )

    con_impts_ids: set[int] = set(
        session.execute(
            select(Imputacion.destino_id)
            .where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id.in_(pedido_ids),
            )
            .distinct()
        )
        .scalars()
        .all()
    )

    dias = _leer_dias_retencion(session)
    cutoff = datetime.now(UTC) - timedelta(days=dias)

    resultado: dict[int, bool] = {}
    for p in pedidos:
        if p.estado not in _ESTADOS_PEDIDO_BORRABLES:
            resultado[p.id] = False
            continue
        if p.id in aprobados_ids:
            resultado[p.id] = False
            continue
        if p.id in con_impts_ids:
            resultado[p.id] = False
            continue
        if p.estado == "cancelado":
            resultado[p.id] = _paso_ventana_retencion(_updated_at_aware(p), cutoff)
        else:  # borrador
            resultado[p.id] = True

    return resultado


def _calcular_puede_eliminar_ops_batch(
    session: Session,
    ops: list[OrdenPago],
) -> dict[int, bool]:
    """Análogo para OPs. 3 queries fijas: counts no-reversal / reversal / retención.

    Una OP es borrable si está 'anulado' y (no_reversal_count == reversal_count)
    y `caja_movimiento_id IS NULL` y updated_at <= cutoff.
    """
    if not ops:
        return {}

    op_ids = [op.id for op in ops]

    # Contamos por OP los no-reversal y reversal
    no_reversal_rows = session.execute(
        select(Imputacion.origen_id, sa_func.count())
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.origen_id.in_(op_ids),
            Imputacion.es_reversal.is_(False),
        )
        .group_by(Imputacion.origen_id)
    ).all()
    no_reversal_map: dict[int, int] = {int(row[0]): int(row[1]) for row in no_reversal_rows}

    reversal_rows = session.execute(
        select(Imputacion.origen_id, sa_func.count())
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.origen_id.in_(op_ids),
            Imputacion.es_reversal.is_(True),
        )
        .group_by(Imputacion.origen_id)
    ).all()
    reversal_map: dict[int, int] = {int(row[0]): int(row[1]) for row in reversal_rows}

    dias = _leer_dias_retencion(session)
    cutoff = datetime.now(UTC) - timedelta(days=dias)

    resultado: dict[int, bool] = {}
    for op in ops:
        if op.estado not in _ESTADOS_OP_BORRABLES:
            resultado[op.id] = False
            continue
        if op.caja_movimiento_id is not None:
            resultado[op.id] = False
            continue
        if no_reversal_map.get(op.id, 0) > reversal_map.get(op.id, 0):
            resultado[op.id] = False
            continue
        resultado[op.id] = _paso_ventana_retencion(_updated_at_aware(op), cutoff)

    return resultado


# ==========================================================================
# Snapshots (opción B — eventos copiados al JSON)
# ==========================================================================


def _decimal_to_str(value: Any) -> str | None:
    """Serializa Decimal a string para JSON. Retorna None si value es None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _iso_or_none(value: Any) -> str | None:
    """Convierte datetime/date a ISO string, o None."""
    if value is None:
        return None
    return value.isoformat()


def _snapshot_pedido(pedido: PedidoCompra, session: Session) -> dict[str, Any]:
    """Serializa el pedido completo + sus eventos (opción B).

    Incluye todos los campos del modelo + un array 'eventos' con cada
    fila de `compras_eventos` perteneciente al pedido. Los eventos se
    borran JUNTO con el pedido, pero quedan preservados acá.
    """
    eventos = (
        session.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
            )
            .order_by(CompraEvento.created_at.asc(), CompraEvento.id.asc())
        )
        .scalars()
        .all()
    )

    return {
        "id": pedido.id,
        "numero": pedido.numero,
        "empresa_id": pedido.empresa_id,
        "proveedor_id": pedido.proveedor_id,
        "moneda": pedido.moneda,
        "monto": _decimal_to_str(pedido.monto),
        "tipo_cambio": _decimal_to_str(pedido.tipo_cambio),
        "fecha_pago_texto": pedido.fecha_pago_texto,
        "fecha_pago_estimada": _iso_or_none(pedido.fecha_pago_estimada),
        "requiere_envio": bool(pedido.requiere_envio),
        "numero_factura": pedido.numero_factura,
        "ct_transaction_id": pedido.ct_transaction_id,
        "estado": pedido.estado,
        "creado_por_id": pedido.creado_por_id,
        "aprobado_por_id": pedido.aprobado_por_id,
        "created_at": _iso_or_none(pedido.created_at),
        "updated_at": _iso_or_none(pedido.updated_at),
        "eventos": [
            {
                "id": ev.id,
                "tipo": ev.tipo,
                "payload": ev.payload,
                "usuario_id": ev.usuario_id,
                "created_at": _iso_or_none(ev.created_at),
            }
            for ev in eventos
        ],
    }


def _snapshot_op(op: OrdenPago, session: Session) -> dict[str, Any]:
    """Serializa la OP completa + sus eventos (opción B)."""
    eventos = (
        session.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_ORDEN_PAGO,
                CompraEvento.entidad_id == op.id,
            )
            .order_by(CompraEvento.created_at.asc(), CompraEvento.id.asc())
        )
        .scalars()
        .all()
    )

    return {
        "id": op.id,
        "numero": op.numero,
        "empresa_id": op.empresa_id,
        "proveedor_id": op.proveedor_id,
        "moneda": op.moneda,
        "monto_total": _decimal_to_str(op.monto_total),
        "tipo_cambio": _decimal_to_str(op.tipo_cambio),
        "modo_imputacion": op.modo_imputacion,
        "estado": op.estado,
        "caja_id": op.caja_id,
        "caja_movimiento_id": op.caja_movimiento_id,
        "caja_documento_id": op.caja_documento_id,
        "fecha_pago_estimada": _iso_or_none(op.fecha_pago_estimada),
        "fecha_pago_real": _iso_or_none(op.fecha_pago_real),
        "observaciones": op.observaciones,
        "creado_por_id": op.creado_por_id,
        "pagado_por_id": op.pagado_por_id,
        "created_at": _iso_or_none(op.created_at),
        "updated_at": _iso_or_none(op.updated_at),
        "paid_at": _iso_or_none(op.paid_at),
        "eventos": [
            {
                "id": ev.id,
                "tipo": ev.tipo,
                "payload": ev.payload,
                "usuario_id": ev.usuario_id,
                "created_at": _iso_or_none(ev.created_at),
            }
            for ev in eventos
        ],
    }


# ==========================================================================
# Hard-delete (mutadores — el router commitea)
# ==========================================================================


def _validar_motivo(motivo: str | None) -> str:
    """Normaliza motivo y valida que no sea vacío. HTTP 400 si falla."""
    if motivo is None or not str(motivo).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El motivo es requerido para eliminar definitivamente.",
        )
    return str(motivo).strip()


def eliminar_pedido(
    session: Session,
    *,
    pedido_id: int,
    user_id: int,
    motivo: str,
    challenge_palabra_usada: str | None = None,
) -> ComprasPapelera:
    """Hard-delete de un pedido con papelera auditable (opción B).

    Flujo:
      1. Cargar pedido o 404.
      2. Validar puede_eliminar_pedido → 409 con razón si no.
      3. Validar motivo no vacío → 400.
      4. Snapshot con eventos embebidos.
      5. Insertar fila en compras_papelera.
      6. Borrar eventos de compras_eventos (ya copiados en snapshot).
      7. Delete físico del pedido.

    NO commitea — el router orquesta. Flush final para materializar el ID.

    Raises:
      HTTPException 404 si pedido no existe.
      HTTPException 409 si reglas de negocio no permiten borrar.
      HTTPException 400 si motivo vacío.
    """
    pedido = session.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido id={pedido_id} no encontrado.",
        )

    puede, razon = puede_eliminar_pedido(session, pedido)
    if not puede:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=razon or "No se puede eliminar este pedido.",
        )

    motivo_norm = _validar_motivo(motivo)

    # Opción B: snapshot con eventos DENTRO. Calculamos ANTES de borrar eventos.
    snapshot = _snapshot_pedido(pedido, session)

    papelera_row = ComprasPapelera(
        entidad_tipo=ComprasPapelera.ENTIDAD_TIPO_PEDIDO,
        entidad_id_original=pedido.id,
        numero=pedido.numero,
        empresa_id=pedido.empresa_id,
        proveedor_id=pedido.proveedor_id,
        snapshot=snapshot,
        eliminado_por_id=user_id,
        motivo=motivo_norm,
        challenge_palabra=(challenge_palabra_usada or None),
        estado_original=pedido.estado,
    )
    session.add(papelera_row)
    session.flush()

    # Borrar eventos asociados al pedido (ya están copiados en snapshot.eventos)
    session.query(CompraEvento).filter(
        CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
        CompraEvento.entidad_id == pedido.id,
    ).delete(synchronize_session=False)

    # Delete físico del pedido
    session.delete(pedido)
    session.flush()

    logger.info(
        "Pedido hard-deleted: id=%s numero=%s por user=%s motivo='%s' papelera_id=%s",
        pedido_id,
        papelera_row.numero,
        user_id,
        motivo_norm,
        papelera_row.id,
    )
    return papelera_row


def eliminar_op(
    session: Session,
    *,
    op_id: int,
    user_id: int,
    motivo: str,
    challenge_palabra_usada: str | None = None,
) -> ComprasPapelera:
    """Hard-delete de una OP con papelera auditable (opción B).

    Mismas reglas que `eliminar_pedido` pero aplicadas a OP anulada sin
    movimiento. Eventos copiados al snapshot antes de borrarlos.
    """
    op = session.get(OrdenPago, op_id)
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={op_id} no encontrada.",
        )

    puede, razon = puede_eliminar_op(session, op)
    if not puede:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=razon or "No se puede eliminar esta OP.",
        )

    motivo_norm = _validar_motivo(motivo)

    snapshot = _snapshot_op(op, session)

    papelera_row = ComprasPapelera(
        entidad_tipo=ComprasPapelera.ENTIDAD_TIPO_ORDEN_PAGO,
        entidad_id_original=op.id,
        numero=op.numero,
        empresa_id=op.empresa_id,
        proveedor_id=op.proveedor_id,
        snapshot=snapshot,
        eliminado_por_id=user_id,
        motivo=motivo_norm,
        challenge_palabra=(challenge_palabra_usada or None),
        estado_original=op.estado,
    )
    session.add(papelera_row)
    session.flush()

    session.query(CompraEvento).filter(
        CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_ORDEN_PAGO,
        CompraEvento.entidad_id == op.id,
    ).delete(synchronize_session=False)

    session.delete(op)
    session.flush()

    logger.info(
        "OP hard-deleted: id=%s numero=%s por user=%s motivo='%s' papelera_id=%s",
        op_id,
        papelera_row.numero,
        user_id,
        motivo_norm,
        papelera_row.id,
    )
    return papelera_row


# ==========================================================================
# Lectura de papelera (para el tab UI)
# ==========================================================================


def listar_papelera(
    session: Session,
    *,
    entidad_tipo: str | None = None,
    proveedor_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ComprasPapelera], int]:
    """Lista paginada de papelera. Retorna (items, total).

    Los items vienen con `empresa`, `proveedor`, `eliminado_por` precargados
    (joinedload en el router) — este service solo arma el query base.
    """
    stmt = select(ComprasPapelera)
    conds = []
    if entidad_tipo is not None:
        conds.append(ComprasPapelera.entidad_tipo == entidad_tipo)
    if proveedor_id is not None:
        conds.append(ComprasPapelera.proveedor_id == proveedor_id)
    if conds:
        stmt = stmt.where(*conds)

    count_stmt = select(sa_func.count()).select_from(stmt.subquery())
    total = int(session.execute(count_stmt).scalar_one() or 0)

    offset = (page - 1) * page_size
    stmt = stmt.order_by(ComprasPapelera.created_at.desc(), ComprasPapelera.id.desc())
    stmt = stmt.offset(offset).limit(page_size)
    items = list(session.execute(stmt).scalars().all())
    return items, total


def obtener_papelera_item(session: Session, papelera_id: int) -> ComprasPapelera:
    """Fetch de una fila de papelera por ID, o 404."""
    item = session.get(ComprasPapelera, papelera_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item de papelera id={papelera_id} no encontrado.",
        )
    return item


def enriquecer_nombres_papelera(
    session: Session,
    items: list[ComprasPapelera],
) -> dict[int, dict[str, str | None]]:
    """Devuelve map {papelera_id: {empresa_nombre, proveedor_nombre, eliminado_por_nombre}}.

    Evita N+1 en el listado: hace 3 fetches en batch sobre las FK relevantes.
    """
    if not items:
        return {}

    from app.models.empresa import Empresa
    from app.models.proveedor import Proveedor

    empresa_ids = {it.empresa_id for it in items if it.empresa_id is not None}
    proveedor_ids = {it.proveedor_id for it in items if it.proveedor_id is not None}
    user_ids = {it.eliminado_por_id for it in items}

    empresas = (
        {e.id: e.nombre for e in session.execute(select(Empresa).where(Empresa.id.in_(empresa_ids))).scalars().all()}
        if empresa_ids
        else {}
    )
    proveedores = (
        {
            p.id: p.nombre
            for p in session.execute(select(Proveedor).where(Proveedor.id.in_(proveedor_ids))).scalars().all()
        }
        if proveedor_ids
        else {}
    )
    usuarios = (
        {
            u.id: (getattr(u, "nombre", None) or getattr(u, "username", None))
            for u in session.execute(select(Usuario).where(Usuario.id.in_(user_ids))).scalars().all()
        }
        if user_ids
        else {}
    )

    return {
        it.id: {
            "empresa_nombre": empresas.get(it.empresa_id) if it.empresa_id is not None else None,
            "proveedor_nombre": proveedores.get(it.proveedor_id) if it.proveedor_id is not None else None,
            "eliminado_por_nombre": usuarios.get(it.eliminado_por_id),
        }
        for it in items
    }
