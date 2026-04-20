"""
pedidos_service — flujo de pedidos de compra (state machine + eventos).

Este servicio implementa el ciclo de vida de `pedidos_compra` (design §6)
cubriendo:
  - Creación en estado `borrador` con numeración correlativa.
  - Edición con reglas por estado (borrador vs aprobado/pagado_parcial).
  - Matriz de transiciones manuales (enviar_aprobacion, aprobar, rechazar,
    reabrir, cancelar, cancelar_aprobado).
  - Transiciones automáticas desde imputaciones (aprobado → pagado_parcial
    → pagado, y sus reversos al anular OP).
  - Eventos en `compras_eventos` (append-only, polimórfico, D2).
  - Integración con CC proveedor: al aprobar inserta `debe`; al cancelar
    un pedido aprobado inserta `ajuste` con signo_ajuste=-1 para reversar.
  - Auto-match forward con el ERP cuando se edita `numero_factura`.

Responsabilidad del caller:
  - Ejecutar dentro de una transacción (`session.commit()` / `rollback()`).
  - Validar permisos (dependency FastAPI antes de llamar al servicio).

Referencias:
  - design.md §6 (state machine + matriz de permisos)
  - tasks.md COMPRAS-4.1, COMPRAS-4.8, COMPRAS-4.9
  - Engram #117 (design), #123 (F3 apply)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.pedido_compra import PedidoCompra
from app.services import (
    cc_proveedor_service,
    erp_matching_service,
    numeracion_service,
)

logger = get_logger("services.pedidos_service")


# ──────────────────────────────────────────────────────────────────────────
# Tipos y constantes
# ──────────────────────────────────────────────────────────────────────────


EstadoPedido = Literal[
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "pagado_parcial",
    "pagado",
]

# Estados terminales (no permiten transiciones manuales salvo las explícitas)
ESTADOS_TERMINALES: Final[frozenset[str]] = frozenset({"pagado", "cancelado"})

# Campos editables según estado (REQ-PED-006)
CAMPOS_EDITABLES_BORRADOR: Final[frozenset[str]] = frozenset(
    {
        "moneda",
        "monto",
        "fecha_pago_texto",
        "fecha_pago_estimada",
        "requiere_envio",
        "numero_factura",
    }
)
CAMPOS_EDITABLES_APROBADO: Final[frozenset[str]] = frozenset({"numero_factura"})


# Matriz de transiciones manuales (design §6):
#   clave: (estado_origen, accion) → estado_destino
TRANSICIONES_VALIDAS: Final[dict[tuple[str, str], str]] = {
    ("borrador", "enviar_aprobacion"): "pendiente_aprobacion",
    ("borrador", "cancelar"): "cancelado",
    ("pendiente_aprobacion", "aprobar"): "aprobado",
    # rechazar puede devolver a borrador o cancelar definitivamente (body.accion)
    ("pendiente_aprobacion", "rechazar_devolver"): "rechazado",
    ("pendiente_aprobacion", "rechazar_cancelar"): "cancelado",
    ("rechazado", "reabrir"): "borrador",
    ("rechazado", "cancelar_definitivo"): "cancelado",
    ("aprobado", "cancelar_aprobado"): "cancelado",
}


# Tipos de evento whitelisteados (compras_eventos.tipo)
class TiposEvento:
    CREADO: Final[str] = "creado"
    EDITADO: Final[str] = "editado"
    ENVIADO_APROBACION: Final[str] = "enviado_aprobacion"
    APROBADO: Final[str] = "aprobado"
    RECHAZADO: Final[str] = "rechazado"
    REABIERTO: Final[str] = "reabierto"
    CANCELADO: Final[str] = "cancelado"
    PAGO_PARCIAL_APLICADO: Final[str] = "pago_parcial_aplicado"
    PAGO_COMPLETADO: Final[str] = "pago_completado"
    REVERSO_CANCELACION: Final[str] = "reverso_cancelacion"
    MATCHEADO_CON_ERP: Final[str] = "matcheado_con_erp"


# ──────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────


def _registrar_evento(
    session: Session,
    *,
    pedido: PedidoCompra,
    tipo: str,
    usuario_id: int,
    payload: Optional[dict[str, Any]] = None,
) -> CompraEvento:
    """Inserta un evento en `compras_eventos` para el pedido dado."""
    evento = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        tipo=tipo,
        usuario_id=usuario_id,
        payload=payload,
    )
    session.add(evento)
    session.flush()
    return evento


def _obtener_pedido_o_404(session: Session, pedido_id: int) -> PedidoCompra:
    pedido = session.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PedidoCompra id={pedido_id} no encontrado.",
        )
    return pedido


# ──────────────────────────────────────────────────────────────────────────
# Alta (creación)
# ──────────────────────────────────────────────────────────────────────────


def crear_pedido(
    session: Session,
    *,
    empresa_id: int,
    proveedor_id: int,
    moneda: Literal["ARS", "USD"],
    monto: Decimal,
    creado_por_id: int,
    fecha_pago_texto: Optional[str] = None,
    fecha_pago_estimada: Optional[date] = None,
    requiere_envio: bool = False,
    numero_factura: Optional[str] = None,
) -> PedidoCompra:
    """
    Crea un pedido en estado `borrador` con número correlativo.

    - Genera número via `numeracion_service.generar_siguiente_numero`
      (tipo='pedido', empresa_id=empresa_id).
    - Inserta evento `creado` en `compras_eventos`.

    Args:
        session: tx activa.
        empresa_id: FK a empresas.
        proveedor_id: FK a proveedores.
        moneda: 'ARS' o 'USD'.
        monto: monto > 0.
        creado_por_id: FK a usuarios.
        fecha_pago_texto, fecha_pago_estimada, requiere_envio, numero_factura:
            campos opcionales del pedido.

    Returns:
        El `PedidoCompra` recién creado con `id` asignado.

    Raises:
        HTTPException 400 si `monto <= 0`.
    """
    if monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto debe ser > 0 (recibido: {monto}).",
        )

    numero, _ = numeracion_service.generar_siguiente_numero(
        session,
        tipo="pedido",
        empresa_id=empresa_id,
    )

    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda=moneda,
        monto=monto,
        fecha_pago_texto=fecha_pago_texto,
        fecha_pago_estimada=fecha_pago_estimada,
        requiere_envio=requiere_envio,
        numero_factura=numero_factura,
        estado="borrador",
        creado_por_id=creado_por_id,
    )
    session.add(pedido)
    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.CREADO,
        usuario_id=creado_por_id,
        payload={
            "numero": numero,
            "proveedor_id": proveedor_id,
            "empresa_id": empresa_id,
            "moneda": moneda,
            "monto": str(monto),
        },
    )

    logger.info(
        "pedido_creado id=%s numero=%s proveedor_id=%s empresa_id=%s monto=%s %s",
        pedido.id,
        numero,
        proveedor_id,
        empresa_id,
        monto,
        moneda,
    )
    return pedido


# ──────────────────────────────────────────────────────────────────────────
# Edición
# ──────────────────────────────────────────────────────────────────────────


def editar_pedido(
    session: Session,
    *,
    pedido_id: int,
    user_id: int,
    **campos: Any,
) -> PedidoCompra:
    """
    Edita un pedido aplicando reglas por estado (REQ-PED-006).

    Estados y campos editables:
      - `borrador`: todos los campos de `CAMPOS_EDITABLES_BORRADOR`.
      - `aprobado` / `pagado_parcial`: solo `numero_factura`.
      - Cualquier otro estado → HTTP 409.

    Side effects:
      - Inserta evento `editado` con payload `{campos_cambiados}`.
      - Si se editó `numero_factura` → invoca
        `erp_matching_service.match_forward(session, pedido_compra_id=...)`
        en la misma transacción (auto-match).

    Args:
        session: tx activa.
        pedido_id: PK del pedido.
        user_id: usuario que edita (auditoría).
        **campos: campos a actualizar. Se ignoran claves desconocidas.

    Returns:
        El `PedidoCompra` actualizado.

    Raises:
        HTTPException 404: si no existe.
        HTTPException 409: si el estado no permite editar el conjunto de
            campos solicitado.
        HTTPException 400: si un campo es inválido (moneda/monto).
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)

    if pedido.estado == "borrador":
        editables = CAMPOS_EDITABLES_BORRADOR
    elif pedido.estado in {"aprobado", "pagado_parcial"}:
        editables = CAMPOS_EDITABLES_APROBADO
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede editar un pedido en estado '{pedido.estado}'. "
                f"Estados editables: borrador, aprobado, pagado_parcial."
            ),
        )

    # Filtrar y validar campos
    campos_aplicables = {k: v for k, v in campos.items() if k in editables and v is not None}
    campos_rechazados = {k: v for k, v in campos.items() if k not in editables and v is not None}
    if campos_rechazados:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Los siguientes campos no son editables en estado '{pedido.estado}': "
                f"{sorted(campos_rechazados.keys())}. Editables: {sorted(editables)}."
            ),
        )

    # Validaciones de negocio puntuales
    if "monto" in campos_aplicables:
        nuevo_monto = Decimal(str(campos_aplicables["monto"]))
        if nuevo_monto <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"monto debe ser > 0 (recibido: {nuevo_monto}).",
            )
        campos_aplicables["monto"] = nuevo_monto
    if "moneda" in campos_aplicables:
        if campos_aplicables["moneda"] not in {"ARS", "USD"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"moneda inválida: '{campos_aplicables['moneda']}'.",
            )

    diff: dict[str, dict[str, Any]] = {}
    numero_factura_cambio = False
    for campo, nuevo_valor in campos_aplicables.items():
        valor_anterior = getattr(pedido, campo)
        if valor_anterior != nuevo_valor:
            diff[campo] = {"antes": _serializar_valor(valor_anterior), "despues": _serializar_valor(nuevo_valor)}
            setattr(pedido, campo, nuevo_valor)
            if campo == "numero_factura":
                numero_factura_cambio = True

    if not diff:
        return pedido  # nada que cambiar

    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.EDITADO,
        usuario_id=user_id,
        payload={"campos_cambiados": diff},
    )

    if numero_factura_cambio and pedido.numero_factura:
        # Auto-match forward — best-effort, no bloqueante
        try:
            erp_matching_service.match_forward(
                session,
                pedido_compra_id=pedido.id,
                usuario_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "editar_pedido: match_forward falló para pedido_id=%s: %s",
                pedido.id,
                exc,
            )

    logger.info(
        "pedido_editado id=%s estado=%s campos=%s",
        pedido.id,
        pedido.estado,
        sorted(diff.keys()),
    )
    return pedido


def _serializar_valor(valor: Any) -> Any:
    """Convierte valores no-JSON-serializables (date, Decimal) a string."""
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


# ──────────────────────────────────────────────────────────────────────────
# Transiciones (state machine)
# ──────────────────────────────────────────────────────────────────────────


def transicionar(
    session: Session,
    *,
    pedido_id: int,
    accion: str,
    user_id: int,
    motivo: Optional[str] = None,
    fecha_pago_estimada: Optional[date] = None,
) -> PedidoCompra:
    """
    Aplica una transición manual según la matriz `TRANSICIONES_VALIDAS`.

    Acciones soportadas (design §6):
      - `enviar_aprobacion`, `cancelar` (desde borrador)
      - `aprobar`, `rechazar_devolver`, `rechazar_cancelar` (desde pendiente_aprobacion)
      - `reabrir`, `cancelar_definitivo` (desde rechazado)
      - `cancelar_aprobado` (desde aprobado — con reverso en CC)

    Side effects por acción:
      - `aprobar`: set `aprobado_por_id` y `fecha_pago_estimada` (si se pasa).
        Inserta movimiento `debe` en `cc_proveedor_movimientos` por el monto
        del pedido (design §6 nota).
      - `cancelar_aprobado`: inserta `ajuste` con `signo_ajuste=-1` en CC
        para compensar el debe previo (reverso contable).
      - Todas: insertan evento en `compras_eventos`.

    Args:
        session: tx activa.
        pedido_id: PK del pedido.
        accion: clave de la matriz.
        user_id: usuario ejecutando (auditoría + aprobador).
        motivo: texto libre — obligatorio para `rechazar_*`, `cancelar_*`.
        fecha_pago_estimada: se aplica solo en `aprobar`.

    Returns:
        El pedido con el nuevo estado.

    Raises:
        HTTPException 404: pedido inexistente.
        HTTPException 400: transición inválida (combo estado+accion no existe).
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)

    clave = (pedido.estado, accion)
    if clave not in TRANSICIONES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transición no permitida: estado='{pedido.estado}' accion='{accion}'. "
                f"Combos válidos: {sorted(TRANSICIONES_VALIDAS.keys())}."
            ),
        )

    nuevo_estado = TRANSICIONES_VALIDAS[clave]
    estado_previo = pedido.estado
    payload: dict[str, Any] = {"estado_previo": estado_previo, "estado_nuevo": nuevo_estado}
    if motivo:
        payload["motivo"] = motivo

    # Side effects específicos por acción
    if accion == "aprobar":
        pedido.aprobado_por_id = user_id
        if fecha_pago_estimada is not None:
            pedido.fecha_pago_estimada = fecha_pago_estimada
            payload["fecha_pago_estimada"] = fecha_pago_estimada.isoformat()
        # Inserta DEBE en CC por el monto total del pedido
        cc_proveedor_service.insertar_mov(
            session,
            proveedor_id=pedido.proveedor_id,
            empresa_id=pedido.empresa_id,
            fecha_movimiento=date.today(),
            tipo="debe",
            monto=Decimal(pedido.monto),
            moneda=pedido.moneda,  # type: ignore[arg-type]
            origen_tipo="pedido_compra",
            origen_id=pedido.id,
            descripcion=f"Aprobación pedido {pedido.numero}",
            creado_por_id=user_id,
        )
    elif accion == "cancelar_aprobado":
        # Reverso en CC: ajuste con signo -1 por el monto del pedido
        cc_proveedor_service.insertar_mov(
            session,
            proveedor_id=pedido.proveedor_id,
            empresa_id=pedido.empresa_id,
            fecha_movimiento=date.today(),
            tipo="ajuste",
            monto=Decimal(pedido.monto),
            moneda=pedido.moneda,  # type: ignore[arg-type]
            origen_tipo="cancelacion_pedido",
            origen_id=pedido.id,
            descripcion=f"Cancelación pedido aprobado {pedido.numero}",
            creado_por_id=user_id,
            signo_ajuste=-1,
        )

    pedido.estado = nuevo_estado
    session.flush()

    # Evento contextualizado
    tipo_evento = _tipo_evento_para_accion(accion)
    _registrar_evento(
        session,
        pedido=pedido,
        tipo=tipo_evento,
        usuario_id=user_id,
        payload=payload,
    )

    logger.info(
        "pedido_transicion id=%s %s --(%s)--> %s user_id=%s",
        pedido.id,
        estado_previo,
        accion,
        nuevo_estado,
        user_id,
    )
    return pedido


def _tipo_evento_para_accion(accion: str) -> str:
    """Mapea una acción de transición a su `tipo` en `compras_eventos`."""
    mapping = {
        "enviar_aprobacion": TiposEvento.ENVIADO_APROBACION,
        "aprobar": TiposEvento.APROBADO,
        "rechazar_devolver": TiposEvento.RECHAZADO,
        "rechazar_cancelar": TiposEvento.CANCELADO,
        "reabrir": TiposEvento.REABIERTO,
        "cancelar_definitivo": TiposEvento.CANCELADO,
        "cancelar": TiposEvento.CANCELADO,
        "cancelar_aprobado": TiposEvento.CANCELADO,
    }
    return mapping.get(accion, accion)


# ──────────────────────────────────────────────────────────────────────────
# Transiciones automáticas (disparadas por imputaciones)
# ──────────────────────────────────────────────────────────────────────────


def calcular_saldo_pendiente_pedido(session: Session, pedido_id: int) -> Decimal:
    """
    Saldo pendiente efectivo de un pedido.

    Fórmula:
        saldo = monto - (imputado_no_reversal - imputado_reversal)

    Donde:
        - `imputado_no_reversal`: suma de imputaciones con `es_reversal=False`
          cuyo destino es este pedido.
        - `imputado_reversal`: suma de imputaciones con `es_reversal=True`
          cuyo destino es este pedido (compensan la imputación original).

    Cuando una imputación se reimputa a OTRO destino, se inserta el
    reversal al destino original → el reversal descuenta correctamente
    este pedido.
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415

    pedido = _obtener_pedido_o_404(session, pedido_id)

    # No-reversal
    imputado_no_reversal = session.execute(
        select(sa_func.coalesce(sa_func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == pedido.moneda,
            Imputacion.es_reversal.is_(False),
        )
    ).scalar_one()

    # Reversal
    imputado_reversal = session.execute(
        select(sa_func.coalesce(sa_func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == pedido.moneda,
            Imputacion.es_reversal.is_(True),
        )
    ).scalar_one()

    imputado_efectivo = Decimal(imputado_no_reversal) - Decimal(imputado_reversal)
    return Decimal(pedido.monto) - imputado_efectivo


def aplicar_imputacion_a_pedido(
    session: Session,
    *,
    pedido_id: int,
    monto_imputado: Decimal,  # noqa: ARG001 — compatibilidad con llamadas
) -> PedidoCompra:
    """
    Transición automática: al crear/aplicar una imputación con destino
    `pedido_compra`, recalcula el saldo pendiente y ajusta el estado.

    Matriz:
      - `aprobado` + saldo > 0 → `pagado_parcial`
      - `aprobado` + saldo == 0 → `pagado`
      - `pagado_parcial` + saldo == 0 → `pagado`
      - Cualquier otro estado → no-op (se ignora).

    NO toca CC (el `haber` ya lo generó `cc_proveedor_service.aplicar_imputacion`).

    Si `monto_imputado > saldo_anterior` (overpay) → se queda en `pagado`
    pero el excedente debería haberse dirigido a `saldo` por el FIFO del
    caller — este servicio no valida overpay (responsabilidad del caller).

    Args:
        session: tx activa.
        pedido_id: PK del pedido.
        monto_imputado: monto de la imputación (informativo; el cálculo
            real usa `calcular_saldo_pendiente_pedido`).

    Returns:
        El pedido con el estado potencialmente actualizado.
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)

    if pedido.estado not in {"aprobado", "pagado_parcial", "pagado"}:
        # Estados donde no aplica la lógica automática
        return pedido

    saldo = calcular_saldo_pendiente_pedido(session, pedido.id)
    estado_previo = pedido.estado

    if saldo <= Decimal("0"):
        nuevo_estado = "pagado"
        tipo_evento = TiposEvento.PAGO_COMPLETADO
    else:
        # Aún hay saldo pendiente. Si era 'pagado' (por un reversal que
        # reabre deuda) → vuelve a 'pagado_parcial'. Si era 'aprobado' →
        # 'pagado_parcial'.
        if pedido.estado == "aprobado":
            nuevo_estado = "pagado_parcial"
            tipo_evento = TiposEvento.PAGO_PARCIAL_APLICADO
        elif pedido.estado == "pagado":
            nuevo_estado = "pagado_parcial"
            tipo_evento = TiposEvento.REVERSO_CANCELACION
        else:
            # pagado_parcial con saldo > 0 → sigue pagado_parcial (no-op)
            return pedido

    if nuevo_estado == estado_previo:
        return pedido

    pedido.estado = nuevo_estado  # type: ignore[assignment]
    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=tipo_evento,
        usuario_id=pedido.creado_por_id,  # auto-transición: sin user explícito
        payload={
            "estado_previo": estado_previo,
            "estado_nuevo": nuevo_estado,
            "saldo_pendiente": str(saldo),
        },
    )
    logger.info(
        "pedido_auto_transicion id=%s %s -> %s (saldo=%s)",
        pedido.id,
        estado_previo,
        nuevo_estado,
        saldo,
    )
    return pedido


def revertir_transicion_por_anulacion_op(
    session: Session,
    *,
    pedido_id: int,
    user_id: int,
) -> PedidoCompra:
    """
    Al anular una OP, los pedidos que habían quedado `pagado`/`pagado_parcial`
    por esa OP deben recalcularse. Invocado por `ordenes_pago_service.anular`.

    Idéntico a `aplicar_imputacion_a_pedido`, pero explicita la intención
    y registra un evento `reverso_cancelacion` si aplica.
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)
    estado_previo = pedido.estado
    saldo = calcular_saldo_pendiente_pedido(session, pedido.id)

    if saldo <= Decimal("0"):
        # Todavía cubierto por otras imputaciones → no cambia.
        return pedido

    # Saldo pendiente > 0 → vuelve a aprobado (si no hay otras imputaciones)
    # o a pagado_parcial (si las hay).
    imputado_efectivo = Decimal(pedido.monto) - saldo
    nuevo_estado = "aprobado" if imputado_efectivo <= Decimal("0") else "pagado_parcial"

    if nuevo_estado == estado_previo:
        return pedido

    pedido.estado = nuevo_estado  # type: ignore[assignment]
    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.REVERSO_CANCELACION,
        usuario_id=user_id,
        payload={
            "estado_previo": estado_previo,
            "estado_nuevo": nuevo_estado,
            "saldo_pendiente": str(saldo),
            "motivo": "anulacion_op",
        },
    )
    logger.info(
        "pedido_revertir_por_anulacion_op id=%s %s -> %s",
        pedido.id,
        estado_previo,
        nuevo_estado,
    )
    return pedido


__all__ = [
    "CAMPOS_EDITABLES_APROBADO",
    "CAMPOS_EDITABLES_BORRADOR",
    "ESTADOS_TERMINALES",
    "EstadoPedido",
    "TRANSICIONES_VALIDAS",
    "TiposEvento",
    "aplicar_imputacion_a_pedido",
    "calcular_saldo_pendiente_pedido",
    "crear_pedido",
    "editar_pedido",
    "revertir_transicion_por_anulacion_op",
    "transicionar",
]
