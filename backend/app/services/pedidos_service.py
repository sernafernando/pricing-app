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
from decimal import ROUND_HALF_UP, Decimal
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
        "tipo_cambio",
        "fecha_pago_texto",
        "fecha_pago_estimada",
        "requiere_envio",
        "numero_factura",
    }
)
CAMPOS_EDITABLES_APROBADO: Final[frozenset[str]] = frozenset(
    {
        "numero_factura",
        # F5: tipo_cambio removed — TC corrections now go exclusively through
        # PUT /pedidos/{id}/tipo-cambio (actualizar_tipo_cambio_manual).
        # Attempting to pass tipo_cambio here returns HTTP 422.
        # Comentarios editables post-aprobación sin afectar CC/imputaciones
        "observaciones",
    }
)


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
    # Batch I — vinculación manual factura ERP + ajuste de monto controlado
    FACTURA_VINCULADA: Final[str] = "factura_vinculada"
    FACTURA_DESVINCULADA: Final[str] = "factura_desvinculada"
    MONTO_AJUSTADO_POR_FACTURA: Final[str] = "monto_ajustado_por_factura"
    MONTO_DIFIERE_AL_MATCHEAR: Final[str] = "monto_difiere_al_matchear"
    # Sub-batch 4 — UPDATE directo del monto sin generar ajuste en CC
    # cuando el pedido no tiene imputaciones vigentes.
    MONTO_ACTUALIZADO_SIN_IMPUTACIONES: Final[str] = "monto_actualizado_sin_imputaciones"
    # Feature D — corrección de pedido (clon append-only bidireccional).
    # `creado_por_correccion_de`: evento en el clon, apunta al original.
    # `cancelado_por_correccion`: evento en el original, apunta al clon.
    # `imputaciones_reaplicadas_por_correccion`: evento post-aprobación del
    #   clon cuando se re-aplican las imputaciones del original (reversals +
    #   nuevas).
    CREADO_POR_CORRECCION_DE: Final[str] = "creado_por_correccion_de"
    CANCELADO_POR_CORRECCION: Final[str] = "cancelado_por_correccion"
    IMPUTACIONES_REAPLICADAS_POR_CORRECCION: Final[str] = "imputaciones_reaplicadas_por_correccion"
    # F5 — manual TC override
    TC_MANUAL_ACTUALIZADO: Final[str] = "tc_manual_actualizado"


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


def _resolver_tipo_cambio_para_pedido(
    session: Session,
    *,
    moneda: str,
    tipo_cambio: Optional[Decimal],
) -> Optional[Decimal]:
    """
    Valida coherencia `moneda` ↔ `tipo_cambio` y autollena el TC del día
    cuando corresponde (Batch B del plan UX compras).

    Reglas:
      - moneda='ARS' + tipo_cambio!=None  → HTTP 400 (no aplica).
      - moneda='ARS' + tipo_cambio=None   → return None.
      - moneda='USD' + tipo_cambio>0      → return tipo_cambio.
      - moneda='USD' + tipo_cambio<=0     → HTTP 400.
      - moneda='USD' + tipo_cambio=None   → intenta leer el TC del día
        desde `tipo_cambio` (moneda='USD', fecha=hoy). Usa `venta` (es el
        que el usuario paga). Si no existe, devuelve None con log WARNING
        (el frontend puede ofrecer editarlo luego).
    """
    if moneda == "ARS":
        if tipo_cambio is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tipo_cambio solo aplica a moneda='USD'.",
            )
        return None

    if moneda == "USD":
        if tipo_cambio is not None:
            if tipo_cambio <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"tipo_cambio debe ser > 0 (recibido: {tipo_cambio}).",
                )
            return Decimal(str(tipo_cambio))

        # Autollenar desde `tipo_cambio` (tabla del sync BNA). Best-effort.
        from app.models.tipo_cambio import TipoCambio  # noqa: PLC0415

        hoy = date.today()
        tc_row = (
            session.query(TipoCambio)
            .filter(TipoCambio.moneda == "USD", TipoCambio.fecha == hoy)
            .order_by(TipoCambio.id.desc())
            .first()
        )
        if tc_row is None or tc_row.venta in (None, 0):
            logger.warning(
                "pedidos_service: TC del día no disponible para USD (fecha=%s). "
                "Pedido se creará con tipo_cambio=NULL — el usuario deberá editarlo.",
                hoy,
            )
            return None
        return Decimal(str(tc_row.venta))

    # Defensivo: moneda con patrón validado en Pydantic, no debería llegar otra.
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"moneda inválida: '{moneda}' (esperado ARS|USD).",
    )


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
    tipo_cambio: Optional[Decimal] = None,
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
    - Resuelve `tipo_cambio` vía `_resolver_tipo_cambio_para_pedido`
      (autollena con TC del día cuando corresponde).

    Args:
        session: tx activa.
        empresa_id: FK a empresas.
        proveedor_id: FK a proveedores.
        moneda: 'ARS' o 'USD'.
        monto: monto > 0.
        creado_por_id: FK a usuarios.
        tipo_cambio: cotización ARS/USD. Solo aplica a moneda='USD'.
            Si es None y moneda='USD', el servicio intenta leer el TC del
            día desde la tabla `tipo_cambio`.
        fecha_pago_texto, fecha_pago_estimada, requiere_envio, numero_factura:
            campos opcionales del pedido.

    Returns:
        El `PedidoCompra` recién creado con `id` asignado.

    Raises:
        HTTPException 400 si `monto <= 0`.
        HTTPException 400 si `tipo_cambio` es incoherente con `moneda`.
    """
    if monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto debe ser > 0 (recibido: {monto}).",
        )

    tipo_cambio_resuelto = _resolver_tipo_cambio_para_pedido(
        session,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
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
        tipo_cambio=tipo_cambio_resuelto,
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
            "tipo_cambio": str(tipo_cambio_resuelto) if tipo_cambio_resuelto is not None else None,
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
      - `aprobado` / `pagado_parcial` / `pagado`: solo campos de
        `CAMPOS_EDITABLES_APROBADO` (numero_factura, tipo_cambio, observaciones).
        Estos campos son metadata y no disparan recalculos en CC/imputaciones.
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
    elif pedido.estado in {"aprobado", "pagado_parcial", "pagado"}:
        editables = CAMPOS_EDITABLES_APROBADO
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede editar un pedido en estado '{pedido.estado}'. "
                f"Estados editables: borrador, aprobado, pagado_parcial, pagado."
            ),
        )

    # F5 — tipo_cambio is no longer editable via this endpoint in non-borrador states (FR5.9, AC5.6).
    # In 'borrador', tipo_cambio is still a valid setup field (CAMPOS_EDITABLES_BORRADOR).
    # In 'aprobado' / 'pagado_parcial' / 'pagado', TC corrections go through PUT /tipo-cambio.
    # Specific 422 before the generic rejection path for a more actionable error message.
    if pedido.estado != "borrador" and "tipo_cambio" in campos and campos.get("tipo_cambio") is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "tipo_cambio ya no es editable por esta vía. "
                "Usá PUT /pedidos/{id}/tipo-cambio para ajustar el TC del pedido."
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

    # tipo_cambio: validar coherencia con moneda FINAL (la que queda tras
    # aplicar los cambios). Si el usuario no tocó `moneda` se usa la actual.
    if "tipo_cambio" in campos_aplicables or "moneda" in campos_aplicables:
        moneda_final = campos_aplicables.get("moneda", pedido.moneda)
        tc_final = campos_aplicables.get(
            "tipo_cambio",
            pedido.tipo_cambio if "tipo_cambio" not in campos_aplicables else None,
        )
        # Solo re-resolvemos si el usuario mandó tipo_cambio explícito o cambió moneda.
        # Cuando solo cambia moneda ARS→USD y no mandó TC, intentamos autollenar.
        if "tipo_cambio" in campos_aplicables:
            campos_aplicables["tipo_cambio"] = _resolver_tipo_cambio_para_pedido(
                session, moneda=moneda_final, tipo_cambio=tc_final
            )
        elif "moneda" in campos_aplicables and moneda_final == "ARS" and pedido.tipo_cambio is not None:
            # Si pasa de USD→ARS, el TC previo queda inválido → forzar a None.
            campos_aplicables["tipo_cambio"] = None
        elif "moneda" in campos_aplicables and moneda_final == "USD" and pedido.tipo_cambio is None:
            # ARS→USD sin TC explícito → autollenar best-effort.
            campos_aplicables["tipo_cambio"] = _resolver_tipo_cambio_para_pedido(
                session, moneda="USD", tipo_cambio=None
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
        # F1 — Capture tipo_cambio_original at approval time (immutable after this).
        # Only set if not already populated (idempotent: won't overwrite on re-approval).
        if pedido.tipo_cambio_original is None and pedido.tipo_cambio is not None:
            pedido.tipo_cambio_original = pedido.tipo_cambio
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

    # Feature D — al aprobar un clon que nació `pendiente_aprobacion` por
    # cambios financieros, disparar la transferencia de imputaciones
    # congeladas en el original (opción Z). Si la aprobación viene sobre un
    # pedido NO-clon, es no-op.
    if accion == "aprobar" and pedido.corregido_desde_id is not None:
        _aplicar_transferencia_correccion_al_aprobar(session, clon=pedido, user_id=user_id)

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


def calcular_saldos_pendientes_batch(session: Session, pedido_ids: list[int]) -> dict[int, Decimal]:
    """
    Calcula saldo pendiente de múltiples pedidos en una sola query (sin N+1).

    Usa la misma fórmula que `calcular_saldo_pendiente_pedido` pero agregada
    por pedido. Cuando un pedido no tiene imputaciones, no aparece en el
    GROUP BY pero el saldo es igual al monto del pedido — el caller debe
    fallbackear a `pedido.monto` si la key no está en el dict.

    IMPORTANTE: filtra por `moneda_imputada == pedido.moneda`. Si una imp
    se grabó en moneda distinta al pedido (caso edge de cross-moneda mal
    cargada), NO descuenta — el saldo se mantiene en la moneda nativa
    del pedido. Sin este filtro, un pedido USD con imp ARS sumaba el
    monto ARS como si fuera USD y daba saldos negativos absurdos.

    Returns:
        dict {pedido_id: imputado_efectivo} en la moneda de cada pedido.
        El caller hace `pedido.monto - dict.get(pedido_id, 0)`.
    """
    from sqlalchemy import case, func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415

    if not pedido_ids:
        return {}

    # Sumamos cada imputación con su signo: no-reversal suma, reversal resta.
    # JOIN con pedido para filtrar imps en la moneda nativa del pedido.
    signed_sum = sa_func.sum(
        case(
            (Imputacion.es_reversal.is_(True), -Imputacion.monto_imputado),
            else_=Imputacion.monto_imputado,
        )
    )
    rows = session.execute(
        select(Imputacion.destino_id, signed_sum)
        .join(PedidoCompra, PedidoCompra.id == Imputacion.destino_id)
        .where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id.in_(pedido_ids),
            Imputacion.moneda_imputada == PedidoCompra.moneda,
        )
        .group_by(Imputacion.destino_id)
    ).all()
    return {int(pid): Decimal(total or 0) for pid, total in rows}


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


# ──────────────────────────────────────────────────────────────────────────
# TC ponderado por pedido (cross-moneda, FR-005 / FR-008)
# ──────────────────────────────────────────────────────────────────────────


def calcular_tc_ponderado_pedido(session: Session, pedido_id: int) -> Optional[Decimal]:
    """
    TC ponderado por aporte de imputaciones cross-moneda sobre un pedido.

    Fórmula:
        tc_pond = SUM(imp.tipo_cambio * imp.monto_imputado)
                  / SUM(imp.monto_imputado)
        WHERE imp.destino_tipo = 'pedido_compra'
          AND imp.destino_id = pedido.id
          AND imp.moneda_imputada = pedido.moneda
          AND imp.tipo_cambio IS NOT NULL
          AND imp.es_reversal = FALSE

    Interpretación: numerador = total en moneda OP origen aportado, denominador
    = total en moneda destino imputado. Cociente = unidades de moneda origen
    por unidad de moneda destino, ponderado por aporte.

    Reversals excluidos (append-only: imp original sigue contando si la
    reversal aún no fue compensada por una nueva imp). El TC ponderado
    describe el costo histórico declarado de las imps activas; los reversals
    se descuentan correctamente en `calcular_saldos_pendientes_batch`.

    Args:
        session: tx activa.
        pedido_id: id del pedido.

    Returns:
        Decimal cuantizado a 4 decimales (ROUND_HALF_UP) o None si no hay
        imps cross-moneda (denominador = 0).

    Raises:
        HTTPException 404: si el pedido no existe.
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415

    pedido = _obtener_pedido_o_404(session, pedido_id)
    row = session.execute(
        select(
            sa_func.coalesce(
                sa_func.sum(Imputacion.tipo_cambio * Imputacion.monto_imputado),
                0,
            ).label("numerador"),
            sa_func.coalesce(sa_func.sum(Imputacion.monto_imputado), 0).label("denominador"),
        ).where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == pedido.moneda,
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
        )
    ).one()
    numerador = Decimal(row.numerador or 0)
    denominador = Decimal(row.denominador or 0)
    if denominador == 0:
        return None
    return (numerador / denominador).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calcular_tc_ponderado_pedido_batch(
    session: Session,
    pedido_ids: list[int],
) -> dict[int, Optional[Decimal]]:
    """
    TC ponderado batch para múltiples pedidos en una sola query (NFR-001).

    Mismo cálculo que `calcular_tc_ponderado_pedido` pero agregado por
    `destino_id`. JOIN con `pedidos_compra` para filtrar
    `moneda_imputada == pedido.moneda` por cada pedido (cada uno puede
    tener una moneda distinta).

    Pedido ausente del result → None en el dict (no tiene imps cross-moneda,
    o todas las imps fueron same-moneda / con TC NULL).

    Args:
        session: tx activa.
        pedido_ids: lista de ids de pedidos. Si está vacía, devuelve {}.

    Returns:
        dict {pedido_id: Decimal | None}. Todos los `pedido_ids` están
        presentes en el dict (los ausentes del result = None).
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415

    if not pedido_ids:
        return {}

    rows = session.execute(
        select(
            Imputacion.destino_id,
            sa_func.sum(Imputacion.tipo_cambio * Imputacion.monto_imputado).label("num"),
            sa_func.sum(Imputacion.monto_imputado).label("den"),
        )
        .join(PedidoCompra, PedidoCompra.id == Imputacion.destino_id)
        .where(
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id.in_(pedido_ids),
            Imputacion.moneda_imputada == PedidoCompra.moneda,
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
        )
        .group_by(Imputacion.destino_id)
    ).all()

    result: dict[int, Optional[Decimal]] = {pid: None for pid in pedido_ids}
    for pid, num, den in rows:
        if den is None:
            continue
        den_dec = Decimal(den)
        if den_dec == 0:
            continue
        num_dec = Decimal(num or 0)
        result[int(pid)] = (num_dec / den_dec).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return result


# ──────────────────────────────────────────────────────────────────────────
# F1 — TC ponderado Caso A (compras-op-rework PR #1)
# ──────────────────────────────────────────────────────────────────────────


def calcular_tc_ponderado_caso_a(session: Session, pedido_id: int) -> Optional[Decimal]:
    """
    TC ponderado de las imputaciones Caso A (actualizar_tc_pedido=TRUE) sobre
    un pedido.

    Caso A: OPs con `actualizar_tc_pedido=True`. Solo estas contribuyen al
    promedio ponderado. Caso B (tilde OFF) es ignorado.

    Fórmula (igual a `calcular_tc_ponderado_pedido`):
        tc_caso_a = SUM(imp.tipo_cambio * imp.monto_imputado)
                    / SUM(imp.monto_imputado)
        WHERE imp.origen_tipo='orden_pago'
          AND ordenes_pago.actualizar_tc_pedido = TRUE
          AND imp.destino_tipo='pedido_compra'
          AND imp.destino_id = pedido_id
          AND imp.tipo_cambio IS NOT NULL
          AND imp.es_reversal = FALSE

    Per AD-6 (design): la distinción Caso A/B se deriva via JOIN a
    `ordenes_pago`; no se almacena en `imputaciones`.

    Args:
        session: tx activa.
        pedido_id: id del pedido.

    Returns:
        Decimal cuantizado a 4 decimales o None si no hay Caso-A imputaciones
        (denominador = 0).
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.models.orden_pago import OrdenPago  # noqa: PLC0415

    row = session.execute(
        select(
            sa_func.coalesce(
                sa_func.sum(Imputacion.tipo_cambio * Imputacion.monto_imputado),
                0,
            ).label("numerador"),
            sa_func.coalesce(sa_func.sum(Imputacion.monto_imputado), 0).label("denominador"),
        )
        .join(OrdenPago, OrdenPago.id == Imputacion.origen_id)
        .join(PedidoCompra, PedidoCompra.id == Imputacion.destino_id)
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido_id,
            # W1 — solo imputaciones en la moneda del propio pedido alimentan
            # el promedio ponderado (igual que calcular_tc_ponderado_pedido).
            Imputacion.moneda_imputada == PedidoCompra.moneda,
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
            OrdenPago.actualizar_tc_pedido.is_(True),
        )
    ).one()

    numerador = Decimal(row.numerador or 0)
    denominador = Decimal(row.denominador or 0)
    if denominador == 0:
        return None
    return (numerador / denominador).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calcular_tc_ponderado_caso_a_batch(
    session: Session,
    pedido_ids: list[int],
) -> dict[int, Optional[Decimal]]:
    """
    Batch variant of `calcular_tc_ponderado_caso_a` for N pedidos in one query.

    Returns dict {pedido_id: Decimal | None}. All pedido_ids are present in
    the result dict; missing ones (no Caso-A imputaciones) map to None.

    Args:
        session: tx activa.
        pedido_ids: list of pedido PKs. Empty list → returns {}.
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.models.orden_pago import OrdenPago  # noqa: PLC0415

    if not pedido_ids:
        return {}

    rows = session.execute(
        select(
            Imputacion.destino_id,
            sa_func.sum(Imputacion.tipo_cambio * Imputacion.monto_imputado).label("num"),
            sa_func.sum(Imputacion.monto_imputado).label("den"),
        )
        .join(OrdenPago, OrdenPago.id == Imputacion.origen_id)
        .join(PedidoCompra, PedidoCompra.id == Imputacion.destino_id)
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id.in_(pedido_ids),
            # W1 — solo imputaciones en la moneda del propio pedido alimentan
            # el promedio ponderado (igual que calcular_tc_ponderado_pedido).
            Imputacion.moneda_imputada == PedidoCompra.moneda,
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
            OrdenPago.actualizar_tc_pedido.is_(True),
        )
        .group_by(Imputacion.destino_id)
    ).all()

    result: dict[int, Optional[Decimal]] = {pid: None for pid in pedido_ids}
    for pid, num, den in rows:
        if den is None:
            continue
        den_dec = Decimal(den)
        if den_dec == 0:
            continue
        num_dec = Decimal(num or 0)
        result[int(pid)] = (num_dec / den_dec).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return result


def resolver_tc_efectivo_pedido(
    session: Session,
    pedido: PedidoCompra,
) -> Optional[Decimal]:
    """
    Resolves the effective TC for a pedido following the AD-2 precedence ladder.

    Precedence (top wins):
      1. `tipo_cambio_manual` is not None → manual override is authoritative.
      2. Caso-A payments exist → weighted average of Caso-A imputaciones.
      3. Fallback → `tipo_cambio_original` (approval snapshot).

    Called by every mutator that changes imputaciones or TC state (AD-1
    consistency invariant). The result is written back to `pedido.tipo_cambio`
    by the caller — this function is a PURE READER.

    Args:
        session: tx activa.
        pedido: the PedidoCompra ORM instance (with `tipo_cambio_manual`,
            `tipo_cambio_original` already loaded).

    Returns:
        Effective TC as Decimal, or None for ARS pedidos with no TC.
    """
    # Mode 1: manual override is authoritative (AD-4).
    tipo_cambio_manual = getattr(pedido, "tipo_cambio_manual", None)
    if tipo_cambio_manual is not None:
        return Decimal(tipo_cambio_manual)

    # Mode 2: weighted average of Caso-A imputaciones.
    tc_caso_a = calcular_tc_ponderado_caso_a(session, pedido.id)
    if tc_caso_a is not None:
        return tc_caso_a

    # Mode 3: approval snapshot.
    if pedido.tipo_cambio_original is not None:
        return Decimal(pedido.tipo_cambio_original)

    return None


def resolver_tc_efectivo_pedido_batch(
    session: Session,
    pedido_ids: list[int],
) -> dict[int, Optional[Decimal]]:
    """
    F6 — Batch variant of resolver_tc_efectivo_pedido (§7.4, AD-11, AC6.4).

    Resolves the effective TC for N pedidos in O(1) DB queries — no N+1.

    Precedence per AD-2 (top wins, applied in memory after batch loads):
      1. tipo_cambio_manual IS NOT NULL → authoritative override.
      2. Caso-A payments exist → weighted average (via calcular_tc_ponderado_caso_a_batch).
      3. Fallback → tipo_cambio_original (approval snapshot).

    For ARS pedidos (no TC column) the result is None — the caller treats
    None as "pass-through factor 1" (monto_ars = monto).

    Args:
        session: active DB session.
        pedido_ids: list of PedidoCompra PKs. Empty list → returns {}.

    Returns:
        dict {pedido_id: Decimal | None}. All input ids are present in the result.
    """
    if not pedido_ids:
        return {}

    from sqlalchemy import select  # noqa: PLC0415

    # Single query: load tipo_cambio_manual and tipo_cambio_original for all pedidos.
    rows = session.execute(
        select(
            PedidoCompra.id,
            PedidoCompra.tipo_cambio_manual,
            PedidoCompra.tipo_cambio_original,
        ).where(PedidoCompra.id.in_(pedido_ids))
    ).all()

    # Build lookup maps from the single query.
    manual_map: dict[int, Optional[Decimal]] = {}
    original_map: dict[int, Optional[Decimal]] = {}
    for row in rows:
        pid = int(row[0])
        manual_map[pid] = Decimal(row[1]) if row[1] is not None else None
        original_map[pid] = Decimal(row[2]) if row[2] is not None else None

    # Identify pedidos that need Caso-A resolution (mode 2): no manual override.
    needs_caso_a = [pid for pid in pedido_ids if manual_map.get(pid) is None]

    # Single batch query for all Caso-A weighted TCs.
    caso_a_map: dict[int, Optional[Decimal]] = {}
    if needs_caso_a:
        caso_a_map = calcular_tc_ponderado_caso_a_batch(session, needs_caso_a)

    # Apply precedence in memory.
    result: dict[int, Optional[Decimal]] = {}
    for pid in pedido_ids:
        # Mode 1: manual override is authoritative.
        if manual_map.get(pid) is not None:
            result[pid] = manual_map[pid]
            continue
        # Mode 2: weighted Caso-A average.
        tc_caso_a = caso_a_map.get(pid)
        if tc_caso_a is not None:
            result[pid] = tc_caso_a
            continue
        # Mode 3: approval snapshot (may be None for ARS pedidos).
        result[pid] = original_map.get(pid)

    return result


def calcular_varianza_tc(session: Session, pedido: PedidoCompra) -> Decimal:
    """
    F2 — Compute the ARS variance not yet compensated by ND/NC imputaciones.

    Per spec §3.3 and AD-8: this is a PURE DERIVATION — never stored.

    Formula:
        varianza_bruta = (TC_efectivo - TC_original) * SUM(monto_USD_Caso_B)
        where:
            TC_efectivo  = resolver_tc_efectivo_pedido(session, pedido)
            TC_original  = pedido.tipo_cambio_original (TC at PO creation)
            Caso-B payments = ARS OPs with actualizar_tc_pedido=False

    For ARS pedidos (no TC) or pedidos with no Caso-B imputaciones:
        varianza_bruta = 0.

    varianza_compensada = SUM of NC-local → pedido_compra imputaciones (non-reversal)
        signed by NC tipo: 'debito' → positive contribution (increases ND balance),
        'credito' → negative contribution (reduces variance).

    varianza_tc_neta = varianza_bruta - varianza_compensada.

    Sign convention (matches spec §3.3):
        positive → TC rose → buyer underpaid → ND needed.
        negative → TC fell → buyer overpaid → NC needed.

    Args:
        session: active tx.
        pedido: the PedidoCompra ORM instance.

    Returns:
        Decimal varianza_tc_neta. Zero for ARS pedidos or no Caso-B payments.
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415
    from app.models.orden_pago import OrdenPago  # noqa: PLC0415

    # ARS pedidos have no TC variance.
    if pedido.moneda != "USD":
        return Decimal("0")

    tc_efectivo = resolver_tc_efectivo_pedido(session, pedido)
    if tc_efectivo is None:
        return Decimal("0")

    # --- Caso-B imputaciones -----------------------------------------------
    # Caso-B: ARS OP paying a USD pedido without actualizar_tc_pedido=True.
    # moneda_imputada='USD', tipo_cambio IS NOT NULL (set by ejecutar_pago).
    # Formula per spec §3.3: varianza_bruta = (TC_ef - TC_orig) * sum(monto_USD_caso_b).
    # Append-only invariant: cancelled OPs insert reversal rows (es_reversal=True).
    # We net non-reversals minus reversals so cancelled OPs don't over-count.
    caso_b_non_rev = session.execute(
        select(sa_func.sum(Imputacion.monto_imputado).label("total_usd"))
        .join(OrdenPago, OrdenPago.id == Imputacion.origen_id)
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == "USD",
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(False),
            OrdenPago.actualizar_tc_pedido.is_(False),
        )
    ).one()
    caso_b_rev = session.execute(
        select(sa_func.sum(Imputacion.monto_imputado).label("total_usd"))
        .join(OrdenPago, OrdenPago.id == Imputacion.origen_id)
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == "USD",
            Imputacion.tipo_cambio.is_not(None),
            Imputacion.es_reversal.is_(True),
            OrdenPago.actualizar_tc_pedido.is_(False),
        )
    ).one()

    total_usd_caso_b = Decimal(caso_b_non_rev.total_usd or 0) - Decimal(caso_b_rev.total_usd or 0)
    tc_original = Decimal(pedido.tipo_cambio_original) if pedido.tipo_cambio_original is not None else tc_efectivo
    varianza_bruta = (tc_efectivo - tc_original) * total_usd_caso_b

    # --- Compensación via NC-local → pedido_compra imputaciones -------------
    # Signed by NC tipo: 'debito' → +ARS (ND covers positive varianza),
    # 'credito' → -ARS (NC covers negative varianza).
    # Append-only: cancelled NDs/NCs insert reversal imputaciones.
    # We net non-reversals minus reversals so cancelled NDs don't over-compensate.
    nc_rows_non_rev = session.execute(
        select(
            Imputacion.monto_imputado,
            NotaCreditoLocal.tipo.label("nc_tipo"),
        )
        .join(NotaCreditoLocal, NotaCreditoLocal.id == Imputacion.origen_id)
        .where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == "ARS",
            Imputacion.es_reversal.is_(False),
        )
    ).all()
    nc_rows_rev = session.execute(
        select(
            Imputacion.monto_imputado,
            NotaCreditoLocal.tipo.label("nc_tipo"),
        )
        .join(NotaCreditoLocal, NotaCreditoLocal.id == Imputacion.origen_id)
        .where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id == pedido.id,
            Imputacion.moneda_imputada == "ARS",
            Imputacion.es_reversal.is_(True),
        )
    ).all()

    varianza_compensada = Decimal("0")
    for monto_ars, nc_tipo in nc_rows_non_rev:
        signo = Decimal("1") if nc_tipo == "debito" else Decimal("-1")
        varianza_compensada += signo * Decimal(monto_ars)
    for monto_ars, nc_tipo in nc_rows_rev:
        # Reversal cancels the original: subtract the original's contribution.
        signo = Decimal("1") if nc_tipo == "debito" else Decimal("-1")
        varianza_compensada -= signo * Decimal(monto_ars)

    return (varianza_bruta - varianza_compensada).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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


def recalcular_estado_por_imputaciones(
    session: Session,
    *,
    pedido_id: int,
) -> Optional[PedidoCompra]:
    """
    Recalcula el estado del pedido según el saldo pendiente tras las
    imputaciones actuales (excluyendo reversals). Transiciones:
      - Si saldo_pendiente == monto → pedido vuelve a `aprobado`
        (no queda ninguna imputación viva — ej. tras desimputar la única).
      - Si 0 < saldo_pendiente < monto → `pagado_parcial`.
      - Si saldo_pendiente == 0 → `pagado`.

    Matriz simétrica a `aplicar_imputacion_a_pedido` / `ncs_locales_service.
    recalcular_estado_por_imputaciones`. Solo aplica si el pedido está en
    `{aprobado, pagado_parcial, pagado}`; otros estados son no-op.

    Invocado por `imputaciones_service.desimputar` cuando la imputación
    revertida tenía destino `pedido_compra`. Garantiza consistencia entre
    el saldo contable y el estado del pedido en flujos de desimputación
    aislada (fuera del flujo `anular OP` o `cancelar NC aprobada`).

    Tolerante a imputaciones huérfanas: `destino_id` no tiene FK a
    `pedidos_compra` (la polimorfía lo impide). Si el pedido no existe
    (p. ej. purgado de la DB, o en tests aislados que usan IDs sintéticos),
    se loggea WARNING y la función retorna `None` sin propagar 404 —
    evitar que una imputación huérfana bloquee el flujo de desimputación.

    NO registra evento `reverso_cancelacion`: la desimputación aislada no
    implica anulación. Si cambia de estado, registra un evento neutro
    (`pago_parcial_aplicado` o `pago_completado` vía el branch "reverso
    reabre deuda" de `aplicar_imputacion_a_pedido` si corresponde).

    Args:
        session: tx activa.
        pedido_id: PK.

    Returns:
        El pedido con el estado potencialmente actualizado. No-op si el
        estado actual coincide con el estado recalculado. `None` si el
        pedido no existe.
    """
    pedido = session.get(PedidoCompra, pedido_id)
    if pedido is None:
        logger.warning(
            "recalcular_estado_por_imputaciones: pedido_id=%s no encontrado; "
            "imputación destino pedido_compra huérfana — skip.",
            pedido_id,
        )
        return None
    if pedido.estado not in {"aprobado", "pagado_parcial", "pagado"}:
        return pedido

    saldo = calcular_saldo_pendiente_pedido(session, pedido.id)
    estado_previo = pedido.estado

    if saldo <= Decimal("0"):
        nuevo_estado = "pagado"
        tipo_evento = TiposEvento.PAGO_COMPLETADO
    elif saldo >= Decimal(pedido.monto):
        # Saldo pendiente == monto → no hay imputaciones vivas → vuelve a aprobado.
        nuevo_estado = "aprobado"
        tipo_evento = TiposEvento.REVERSO_CANCELACION
    else:
        # 0 < saldo < monto → pagado_parcial.
        nuevo_estado = "pagado_parcial"
        # Si veníamos de 'pagado' (reversal que reabrió deuda) → REVERSO_CANCELACION.
        # Si veníamos de 'aprobado' → PAGO_PARCIAL_APLICADO.
        tipo_evento = (
            TiposEvento.REVERSO_CANCELACION if estado_previo == "pagado" else TiposEvento.PAGO_PARCIAL_APLICADO
        )

    if nuevo_estado == estado_previo:
        return pedido

    pedido.estado = nuevo_estado  # type: ignore[assignment]
    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=tipo_evento,
        usuario_id=pedido.creado_por_id,  # auto-transición sin user explícito
        payload={
            "estado_previo": estado_previo,
            "estado_nuevo": nuevo_estado,
            "saldo_pendiente": str(saldo),
            "motivo": "desimputacion",
        },
    )
    logger.info(
        "pedido_recalculo_por_imputaciones id=%s %s -> %s (saldo=%s)",
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


# ──────────────────────────────────────────────────────────────────────────
# Batch I — vinculación manual factura ERP + ajuste controlado
# ──────────────────────────────────────────────────────────────────────────


def _buscar_ct_vigente_para_proveedor(
    session: Session,
    *,
    ct_transaction: int,
    supp_id: int,
) -> Optional[tuple[str, Decimal, int]]:
    """
    Busca en `v_facturas_compra_vigentes` la ct cuya llave sea la dada Y
    que pertenezca al `supp_id` recibido.

    Returns:
        tupla `(ct_docnumber, ct_total, curr_id_transaction)` si existe;
        None si no hay match en la vista.
    """
    from sqlalchemy import text  # noqa: PLC0415

    stmt = text(
        """
        SELECT ct_docnumber, ct_total, curr_id_transaction
        FROM v_facturas_compra_vigentes
        WHERE ct_transaction = :ct
          AND supp_id = :supp_id
        LIMIT 1
        """
    )
    fila = session.execute(
        stmt,
        {"ct": ct_transaction, "supp_id": supp_id},
    ).first()
    if fila is None:
        return None
    ct_docnumber, ct_total, curr_id = fila
    return str(ct_docnumber or ""), Decimal(str(ct_total or 0)), int(curr_id or 0)


def _curr_id_a_moneda(curr_id: int) -> Optional[str]:
    """Mapea `curr_id_transaction` del ERP a la moneda usada por el módulo
    compras. Convención ERP: 1=ARS, 2=USD. Si no matchea, retorna None
    (caller decide cómo manejar).
    """
    if curr_id == 1:
        return "ARS"
    if curr_id == 2:
        return "USD"
    return None


def _validar_moneda_factura_coincide(
    *, pedido: PedidoCompra, ct_transaction: int, ct_docnumber: str, curr_id: int
) -> None:
    """Verifica que la moneda de la factura ERP coincida con la del pedido.

    Si difieren, vincular o ajustar produciría datos incoherentes (un pedido
    USD con monto en pesos, o viceversa). Caso real detectado: pedido
    P-02-2026-00001 quedó con monto 46M USD por vincular factura ARS.
    """
    moneda_factura = _curr_id_a_moneda(curr_id)
    if moneda_factura is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Factura ct={ct_transaction} ({ct_docnumber}) tiene curr_id={curr_id} "
                f"que no mapea a ARS ni USD. No se puede vincular."
            ),
        )
    if moneda_factura != pedido.moneda:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Moneda de la factura ({moneda_factura}) no coincide con la del "
                f"pedido ({pedido.moneda}). ct={ct_transaction} ({ct_docnumber}). "
                f"Si el pedido tiene la moneda mal, corregilo primero; si la factura "
                f"es la correcta, vinculá una factura del proveedor en {pedido.moneda}."
            ),
        )


def vincular_factura(
    session: Session,
    *,
    pedido_id: int,
    ct_transaction: int,
    user_id: int,
) -> PedidoCompra:
    """
    Vincula manualmente una factura del ERP al pedido (sin ajustar monto).

    Precondiciones:
      - El pedido existe.
      - `pedido.ct_transaction_id IS NULL` (si ya está vinculado → 409).
      - El proveedor del pedido tiene `supp_id` ERP.
      - La ct aparece en `v_facturas_compra_vigentes` para ese `supp_id`.

    NO ajusta `pedido.monto`. Si el monto de la factura difiere, el caller
    debe invocar `ajustar_monto_con_factura` (requiere permiso específico
    + motivo obligatorio).

    Registra evento `factura_vinculada`. NO commit.

    Raises:
        HTTPException 404 — pedido inexistente.
        HTTPException 409 — pedido ya tiene `ct_transaction_id`.
        HTTPException 400 — proveedor sin supp_id o ct no vigente para ese proveedor.
    """
    from sqlalchemy import text  # noqa: PLC0415

    pedido = _obtener_pedido_o_404(session, pedido_id)
    if pedido.ct_transaction_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Pedido id={pedido.id} ya está vinculado a "
                f"ct_transaction={pedido.ct_transaction_id}. "
                f"Desvinculalo antes de vincular otra factura."
            ),
        )

    supp_id = session.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": pedido.proveedor_id},
    ).scalar_one_or_none()
    if supp_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Proveedor id={pedido.proveedor_id} no tiene supp_id ERP — no se puede vincular factura."),
        )

    match = _buscar_ct_vigente_para_proveedor(session, ct_transaction=ct_transaction, supp_id=int(supp_id))
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ct_transaction={ct_transaction} no existe en la vista de facturas vigentes "
                f"para el proveedor id={pedido.proveedor_id} (supp_id={supp_id})."
            ),
        )
    ct_docnumber, ct_total, curr_id = match
    _validar_moneda_factura_coincide(
        pedido=pedido, ct_transaction=ct_transaction, ct_docnumber=ct_docnumber, curr_id=curr_id
    )

    pedido.ct_transaction_id = int(ct_transaction)
    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.FACTURA_VINCULADA,
        usuario_id=user_id,
        payload={
            "ct_transaction": int(ct_transaction),
            "ct_docnumber": ct_docnumber,
            "ct_total": str(ct_total),
            "monto_pedido": str(pedido.monto),
            "modo": "manual",
        },
    )
    logger.info(
        "pedido_vincular_factura id=%s ct=%s docnumber=%s (manual)",
        pedido.id,
        ct_transaction,
        ct_docnumber,
    )
    return pedido


def desvincular_factura(
    session: Session,
    *,
    pedido_id: int,
    user_id: int,
) -> PedidoCompra:
    """
    Desvincula la factura del ERP del pedido.

    Si hubo un ajuste de monto asociado, NO se revierte — el ajuste quedó
    registrado como movimiento separado en `cc_proveedor_movimientos` y
    seguir el hilo es responsabilidad del operador (admin puede hacer un
    ajuste inverso manual si corresponde).

    Raises:
        HTTPException 404 — pedido inexistente.
        HTTPException 400 — pedido no tiene ct_transaction_id seteado.
    """
    pedido = _obtener_pedido_o_404(session, pedido_id)
    if pedido.ct_transaction_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pedido id={pedido.id} no tiene factura vinculada.",
        )

    ct_anterior = int(pedido.ct_transaction_id)
    pedido.ct_transaction_id = None
    session.flush()

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.FACTURA_DESVINCULADA,
        usuario_id=user_id,
        payload={"ct_transaction_anterior": ct_anterior},
    )
    logger.info(
        "pedido_desvincular_factura id=%s ct_anterior=%s",
        pedido.id,
        ct_anterior,
    )
    return pedido


def ajustar_monto_con_factura(
    session: Session,
    *,
    pedido_id: int,
    ct_transaction: int,
    nuevo_monto: Decimal,
    motivo: str,
    user_id: int,
) -> PedidoCompra:
    """
    Ajusta `pedido.monto` al valor de la factura Y lo vincula en una sola
    operación atómica.

    Estrategia (sub-batch 4):
      - Si el pedido NO tiene imputaciones vigentes (es_reversal=False):
        UPDATE directo del monto SIN generar movimiento de ajuste en CC.
        El pedido recién va a impactar en CC cuando se ejecute una OP.
        Se registra evento `monto_actualizado_sin_imputaciones` en lugar
        del ajuste compensatorio.
      - Si SÍ tiene imputaciones vigentes: comportamiento previo —
        movimiento de ajuste append-only en CC por la diferencia, porque
        la CC ya tiene movimientos asociados al monto viejo y no podemos
        cambiar silenciosamente (decisión del usuario: "los pedidos
        cuando le cargás una factura no tiene que generar un ajuste sino
        modificar el monto precisamente", pero ese UPDATE directo SOLO
        es válido sin imputaciones vigentes).

    Genera:
      1) Si hay imputaciones vigentes y `diferencia != 0`: movimiento en
         `cc_proveedor_movimientos` por la diferencia (`tipo='ajuste'`,
         `signo_ajuste=+1/-1`, `origen_tipo='ajuste_pedido'`).
      2) UPDATE `pedido.monto`, `pedido.ct_transaction_id`.
      3) Evento `monto_ajustado_por_factura` (con imputaciones) o
         `monto_actualizado_sin_imputaciones` (sin imputaciones).

    IMPORTANTE — append-only: las imputaciones y movimientos CC previos NO
    se tocan en NINGÚN caso. El ajuste en CC es un movimiento NUEVO.

    Precondiciones:
      - Pedido existe.
      - Pedido NO está vinculado a OTRA factura distinta (si ya tiene
        `ct_transaction_id` != `ct_transaction` → 409; si está vinculado a
        la MISMA `ct_transaction` sigue, porque puede ser un reajuste).
      - `nuevo_monto > 0`.
      - `motivo` no vacío.
      - La ct existe en `v_facturas_compra_vigentes` para el proveedor del pedido.

    Permiso: el caller (router) debe chequear `administracion.ajustar_monto_pedido`.

    NO commit.

    Raises:
        HTTPException 404/409/400 según corresponda.
    """
    from sqlalchemy import text  # noqa: PLC0415

    if nuevo_monto is None or nuevo_monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"nuevo_monto debe ser > 0 (recibido: {nuevo_monto}).",
        )
    motivo_normalizado = (motivo or "").strip()
    if not motivo_normalizado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="motivo es obligatorio para ajustar el monto de un pedido.",
        )

    pedido = _obtener_pedido_o_404(session, pedido_id)

    if pedido.ct_transaction_id is not None and int(pedido.ct_transaction_id) != int(ct_transaction):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Pedido id={pedido.id} ya está vinculado a "
                f"ct_transaction={pedido.ct_transaction_id} (distinta a la solicitada "
                f"{ct_transaction}). Desvinculá primero."
            ),
        )

    supp_id = session.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": pedido.proveedor_id},
    ).scalar_one_or_none()
    if supp_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Proveedor id={pedido.proveedor_id} no tiene supp_id ERP — no se puede ajustar contra la factura."
            ),
        )

    match = _buscar_ct_vigente_para_proveedor(session, ct_transaction=ct_transaction, supp_id=int(supp_id))
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ct_transaction={ct_transaction} no existe en la vista de facturas vigentes "
                f"para el proveedor id={pedido.proveedor_id}."
            ),
        )
    ct_docnumber, _ct_total, curr_id = match
    _validar_moneda_factura_coincide(
        pedido=pedido, ct_transaction=ct_transaction, ct_docnumber=ct_docnumber, curr_id=curr_id
    )

    monto_anterior = Decimal(pedido.monto)
    nuevo_monto_dec = Decimal(str(nuevo_monto))
    diferencia = nuevo_monto_dec - monto_anterior

    # Sub-batch 4: si no hay imputaciones vigentes al pedido → UPDATE directo
    # sin mover CC. Solo genera evento auditado.
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415

    tiene_imputaciones_vivas = (
        session.execute(
            select(func.count())
            .select_from(Imputacion)
            .where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido.id,
                Imputacion.es_reversal.is_(False),
            )
        ).scalar_one()
        or 0
    ) > 0

    if tiene_imputaciones_vivas and diferencia != Decimal("0"):
        # Comportamiento previo: ajuste compensatorio append-only.
        signo = 1 if diferencia > 0 else -1
        cc_proveedor_service.insertar_mov(
            session,
            proveedor_id=pedido.proveedor_id,
            empresa_id=pedido.empresa_id,
            fecha_movimiento=date.today(),
            tipo="ajuste",
            signo_ajuste=signo,
            monto=abs(diferencia),
            moneda=pedido.moneda,  # type: ignore[arg-type]
            origen_tipo="ajuste_pedido",
            origen_id=pedido.id,
            descripcion=(
                f"Ajuste monto pedido {pedido.numero} por factura ct={ct_transaction} "
                f"({ct_docnumber}): {monto_normalizar(monto_anterior)} → "
                f"{monto_normalizar(nuevo_monto_dec)}. Motivo: {motivo_normalizado[:200]}"
            ),
            creado_por_id=user_id,
        )

    pedido.monto = nuevo_monto_dec  # type: ignore[assignment]
    pedido.ct_transaction_id = int(ct_transaction)
    session.flush()

    evento_tipo = (
        TiposEvento.MONTO_AJUSTADO_POR_FACTURA
        if tiene_imputaciones_vivas
        else TiposEvento.MONTO_ACTUALIZADO_SIN_IMPUTACIONES
    )
    _registrar_evento(
        session,
        pedido=pedido,
        tipo=evento_tipo,
        usuario_id=user_id,
        payload={
            "monto_anterior": str(monto_anterior),
            "monto_nuevo": str(nuevo_monto_dec),
            "diferencia": str(diferencia),
            "ct_transaction": int(ct_transaction),
            "ct_docnumber": ct_docnumber,
            "motivo": motivo_normalizado,
            "tenia_imputaciones_vivas": tiene_imputaciones_vivas,
        },
    )
    logger.info(
        "pedido_ajustar_monto id=%s %s → %s (dif=%s) ct=%s user=%s imp_vivas=%s",
        pedido.id,
        monto_anterior,
        nuevo_monto_dec,
        diferencia,
        ct_transaction,
        user_id,
        tiene_imputaciones_vivas,
    )
    return pedido


def monto_normalizar(valor: Decimal) -> str:
    """Representa un Decimal con 2 decimales para descripciones legibles."""
    return f"{Decimal(valor):.2f}"


# ──────────────────────────────────────────────────────────────────────────
# Feature D — Corregir pedido (clonación append-only bidireccional)
# ──────────────────────────────────────────────────────────────────────────


# Estados desde los que se permite corregir un pedido (design feature D.3).
# NO se permite desde borrador/pendiente_aprobacion/rechazado/cancelado:
#   - borrador/pendiente: editar directo o usar flujo normal.
#   - rechazado/cancelado: flujo terminal, no hay qué corregir (o se reabre).
ESTADOS_CORREGIBLES: Final[frozenset[str]] = frozenset({"aprobado", "pagado_parcial", "pagado"})


# Campos que, si cambian respecto al original, fuerzan al clon a nacer en
# `pendiente_aprobacion` (requieren re-aprobación). Cualquier otro cambio
# es cosmético y el clon hereda `aprobado`.
CAMPOS_FINANCIEROS_CORRECCION: Final[frozenset[str]] = frozenset(
    {
        "monto",
        # F5: tipo_cambio removed from corregir_pedido — TC corrections go through
        # PUT /pedidos/{id}/tipo-cambio (in-place, append-only, no clone).
    }
)


def _imputaciones_vigentes_sobre_pedido(session: Session, pedido_id: int) -> list[Any]:
    """Devuelve imputaciones activas (no-reversal sin reversal posterior) con
    destino_tipo='pedido_compra' y destino_id=pedido_id."""
    from sqlalchemy import select

    from app.models.imputacion import Imputacion  # noqa: PLC0415

    # Trae todas las no-reversal; filtra en Python las que ya tienen reversal
    # emitido (otra fila con reimputada_desde_id = esta.id).
    no_reversal = (
        session.execute(
            select(Imputacion).where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido_id,
                Imputacion.es_reversal.is_(False),
            )
        )
        .scalars()
        .all()
    )
    if not no_reversal:
        return []

    ids = [imp.id for imp in no_reversal]
    ids_con_reversal = set(
        session.execute(
            select(Imputacion.reimputada_desde_id).where(
                Imputacion.es_reversal.is_(True),
                Imputacion.reimputada_desde_id.in_(ids),
            )
        )
        .scalars()
        .all()
    )
    return [imp for imp in no_reversal if imp.id not in ids_con_reversal]


def _clonar_adjuntos_de_pedido(
    session: Session,
    *,
    pedido_original_id: int,
    pedido_clon_id: int,
    user_id: int,
) -> int:
    """Clona las filas de `compras_adjuntos` apuntando al clon.

    Los archivos físicos NO se duplican: `path_archivo` se reusa (el
    almacenamiento es inmutable — el mismo archivo puede ser referenciado
    por ambos pedidos). El `subido_por_id` se atribuye al usuario que
    corrige (auditoría del clon).

    Returns el número de adjuntos clonados.
    """
    from sqlalchemy import select

    from app.models.compra_adjunto import CompraAdjunto  # noqa: PLC0415

    adjuntos_orig = (
        session.execute(
            select(CompraAdjunto).where(
                CompraAdjunto.entidad_tipo == CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
                CompraAdjunto.entidad_id == pedido_original_id,
            )
        )
        .scalars()
        .all()
    )
    for adj in adjuntos_orig:
        clon_adj = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=pedido_clon_id,
            nombre_archivo=adj.nombre_archivo,
            path_archivo=adj.path_archivo,  # MISMO archivo físico
            mime_type=adj.mime_type,
            tamano_bytes=adj.tamano_bytes,
            tipo=adj.tipo,
            descripcion=adj.descripcion,
            subido_por_id=user_id,
        )
        session.add(clon_adj)
    return len(adjuntos_orig)


def _construir_diff_correccion(original: PedidoCompra, cambios: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Serializa los cambios aplicados al clon en formato {campo: {de, a}}."""
    diff: dict[str, dict[str, str]] = {}
    for campo, nuevo in cambios.items():
        previo = getattr(original, campo, None)
        if previo != nuevo:
            diff[campo] = {
                "de": _serializar_valor(previo),
                "a": _serializar_valor(nuevo),
            }
    return diff


def corregir_pedido(
    session: Session,
    *,
    pedido_original_id: int,
    cambios: dict[str, Any],
    motivo_correccion: str,
    user_id: int,
) -> PedidoCompra:
    """Clona un pedido aprobado/pagado_parcial/pagado aplicando cambios,
    cancelando el original (Feature D — corrección append-only).

    Reglas:
      - Original debe estar en `ESTADOS_CORREGIBLES`.
      - No se puede cambiar `moneda` (si aparece en cambios con valor
        distinto al original → HTTP 400).
      - Si cambia `monto` o `tipo_cambio` respecto al original → clon nace
        en `pendiente_aprobacion`. Las imputaciones quedan "congeladas" en
        el original; se re-aplican cuando el clon se apruebe (opción Z).
      - Solo cambios cosméticos → clon nace en `aprobado`. Las imputaciones
        se transfieren inmediatamente (reversals en original + nuevas en
        clon) dentro de la misma transacción.

    Side effects:
      - Inserta clon en `pedidos_compra` con `corregido_desde_id=original.id`.
      - Setea `original.estado = 'cancelado'` y `original.corregido_a_id = clon.id`.
      - Transfiere `ct_transaction_id` del original al clon (el original
        queda con NULL para no violar unicidad lógica de factura ERP↔pedido).
      - Clona filas de `compras_adjuntos` (archivos físicos NO se duplican).
      - Inserta eventos `creado_por_correccion_de` (clon) y
        `cancelado_por_correccion` (original) en `compras_eventos`.
      - Si clon nace `aprobado`: inserta DEBE en CC del clon + HABER de
        cancelación en CC del original + reversals de imputaciones + nuevas
        imputaciones al clon. Todo append-only.
      - Si clon nace `pendiente_aprobacion`: NO toca CC ni imputaciones.
        El DEBE original queda vivo; la transferencia se dispara cuando se
        aprueba el clon (ver `_aplicar_transferencia_correccion_al_aprobar`).

    NO commitea — responsabilidad del caller.

    Args:
        session: tx activa.
        pedido_original_id: PK del pedido a corregir.
        cambios: dict `{campo: valor_nuevo}`. Solo se consideran claves que
            aparecen en `CAMPOS_EDITABLES_BORRADOR` + `observaciones`. El
            resto se ignora silenciosamente.
        motivo_correccion: texto libre ≥5 chars. Persistido en los payloads
            de ambos eventos (clon y original).
        user_id: quien ejecuta la corrección (auditoría del clon).

    Returns:
        El pedido clon recién creado (puede estar en `aprobado` o
        `pendiente_aprobacion` según los cambios).

    Raises:
        HTTPException 404: si el original no existe.
        HTTPException 409: si el estado del original no es corregible.
        HTTPException 400: si se intenta cambiar `moneda`.
    """
    # Import diferido para evitar ciclos (imputaciones_service importa
    # helpers de CC, que a su vez pueden importar utilidades genéricas).
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.services import imputaciones_service  # noqa: PLC0415

    # 1. Validar original existe y está en estado corregible
    original = _obtener_pedido_o_404(session, pedido_original_id)
    if original.estado not in ESTADOS_CORREGIBLES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede corregir un pedido en estado '{original.estado}'. "
                f"Solo se permite desde: {sorted(ESTADOS_CORREGIBLES)}."
            ),
        )

    # 2. Validar que no se intenta cambiar moneda
    moneda_propuesta = cambios.get("moneda")
    if moneda_propuesta is not None and moneda_propuesta != original.moneda:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("No se puede cambiar la moneda al corregir un pedido. Cancelá el pedido y creá uno nuevo."),
        )

    # 3. Rechazar tipo_cambio explícito en /corregir — F5 impone que las
    # correcciones de TC vayan exclusivamente por PUT /tipo-cambio (in-place,
    # append-only, con ajuste CC auditado). Aceptar tipo_cambio aquí haría que
    # el clon herede el valor sin emitir el movimiento de revaluación.
    if "tipo_cambio" in cambios and cambios["tipo_cambio"] is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "tipo_cambio no es corregible por esta vía. "
                "Usá PUT /pedidos/{id}/tipo-cambio para ajustar el TC con auditoría de CC."
            ),
        )

    # 3b. Normalizar `monto` si vino (para la comparación Decimal con el
    # original, que está en Numeric). Garantiza que `==` funcione como
    # esperamos.
    if "monto" in cambios and cambios["monto"] is not None:
        cambios["monto"] = Decimal(str(cambios["monto"]))

    # 4. Determinar estado del clon según cambios financieros reales
    cambios_financieros_reales = any(
        campo in cambios and cambios[campo] is not None and cambios[campo] != getattr(original, campo)
        for campo in CAMPOS_FINANCIEROS_CORRECCION
    )
    estado_clon = "pendiente_aprobacion" if cambios_financieros_reales else "aprobado"

    # 5. Snapshot de imputaciones vigentes del original (antes de mutar nada)
    imputaciones_vigentes = _imputaciones_vigentes_sobre_pedido(session, pedido_id=original.id)
    ids_imputaciones_vigentes = [int(imp.id) for imp in imputaciones_vigentes]

    # 6. Construir clon heredando lo del original + cambios aplicados
    nuevo_numero, _ = numeracion_service.generar_siguiente_numero(
        session,
        tipo="pedido",
        empresa_id=original.empresa_id,
    )
    ct_transaction_heredado = original.ct_transaction_id
    clon = PedidoCompra(
        numero=nuevo_numero,
        empresa_id=original.empresa_id,
        proveedor_id=original.proveedor_id,
        moneda=original.moneda,  # inmutable por diseño
        monto=cambios.get("monto") if cambios.get("monto") is not None else original.monto,
        tipo_cambio=original.tipo_cambio,  # TC immutable via /corregir — use PUT /tipo-cambio (F5)
        # F5: tipo_cambio_manual intentionally NOT cloned. The manual override is bound
        # to the original pedido's CC history (it was applied in-place with an audit movement).
        # The clone starts with no override; any TC adjustment on the clone must go through
        # PUT /tipo-cambio on the clone explicitly (fresh audit trail required).
        fecha_pago_texto=cambios.get("fecha_pago_texto", original.fecha_pago_texto),
        fecha_pago_estimada=cambios.get("fecha_pago_estimada", original.fecha_pago_estimada),
        requiere_envio=cambios.get("requiere_envio")
        if cambios.get("requiere_envio") is not None
        else original.requiere_envio,
        numero_factura=cambios.get("numero_factura", original.numero_factura),
        observaciones=cambios.get("observaciones", original.observaciones),
        ct_transaction_id=ct_transaction_heredado,
        corregido_desde_id=original.id,
        estado=estado_clon,
        creado_por_id=user_id,
        aprobado_por_id=(original.aprobado_por_id if estado_clon == "aprobado" else None),
    )
    session.add(clon)
    session.flush()  # → obtenemos clon.id

    # 7. Transferir ct_transaction y marcar original cancelado + ref cruzada
    original_estado_anterior = original.estado
    original.ct_transaction_id = None
    original.estado = "cancelado"
    original.corregido_a_id = clon.id
    session.flush()

    # 8. Clonar adjuntos (archivos físicos reutilizados)
    n_adjuntos = _clonar_adjuntos_de_pedido(
        session,
        pedido_original_id=original.id,
        pedido_clon_id=clon.id,
        user_id=user_id,
    )

    # 9. Construir diff para el evento del clon
    cambios_persistidos = {
        k: v
        for k, v in cambios.items()
        if k
        in {
            "monto",
            # tipo_cambio removed — F5 rejects it with 422 before reaching here
            "fecha_pago_texto",
            "fecha_pago_estimada",
            "requiere_envio",
            "numero_factura",
            "observaciones",
        }
        and v is not None
    }
    diff = _construir_diff_correccion(original, cambios_persistidos)

    # 10. Evento en el original (cancelado_por_correccion)
    _registrar_evento(
        session,
        pedido=original,
        tipo=TiposEvento.CANCELADO_POR_CORRECCION,
        usuario_id=user_id,
        payload={
            "clon_id": clon.id,
            "clon_numero": clon.numero,
            "motivo": motivo_correccion,
            "estado_anterior": original_estado_anterior,
            "ct_transaction_transferida": ct_transaction_heredado,
            "imputaciones_pendientes_reaplicar": (ids_imputaciones_vigentes if cambios_financieros_reales else []),
            "adjuntos_clonados": n_adjuntos,
        },
    )

    # 11. Evento en el clon (creado_por_correccion_de)
    _registrar_evento(
        session,
        pedido=clon,
        tipo=TiposEvento.CREADO_POR_CORRECCION_DE,
        usuario_id=user_id,
        payload={
            "original_id": original.id,
            "original_numero": original.numero,
            "cambios": diff,
            "motivo": motivo_correccion,
            "estado_clon": estado_clon,
            "imputaciones_pendientes_reaplicar": (ids_imputaciones_vigentes if cambios_financieros_reales else []),
        },
    )

    # 12. Side effects CC según estado del clon
    if estado_clon == "aprobado":
        # Cosméticos: transferencia inmediata.
        # (a) HABER de cancelación en CC del original (compensa DEBE original).
        cc_proveedor_service.insertar_mov(
            session,
            proveedor_id=original.proveedor_id,
            empresa_id=original.empresa_id,
            fecha_movimiento=date.today(),
            tipo="ajuste",
            monto=Decimal(original.monto),
            moneda=original.moneda,  # type: ignore[arg-type]
            origen_tipo="cancelacion_pedido_por_correccion",
            origen_id=original.id,
            descripcion=f"Cancelación por corrección {original.numero} → {clon.numero}",
            creado_por_id=user_id,
            signo_ajuste=-1,
        )
        # (b) DEBE del clon (igual que flujo normal de aprobación).
        cc_proveedor_service.insertar_mov(
            session,
            proveedor_id=clon.proveedor_id,
            empresa_id=clon.empresa_id,
            fecha_movimiento=date.today(),
            tipo="debe",
            monto=Decimal(clon.monto),
            moneda=clon.moneda,  # type: ignore[arg-type]
            origen_tipo="pedido_compra",
            origen_id=clon.id,
            descripcion=f"Aprobación por corrección pedido {clon.numero}",
            creado_por_id=user_id,
        )
        # (c) Reversals de imputaciones vigentes del original (append-only).
        # (d) Re-crear las imputaciones apuntando al clon.
        for imp in imputaciones_vigentes:
            imputaciones_service.desimputar(
                session,
                imputacion_id=int(imp.id),
                user_id=user_id,
                motivo=f"Transferencia por corrección a {clon.numero}",
            )
            imputaciones_service.crear_imputacion(
                session,
                origen_tipo=imp.origen_tipo,
                origen_id=int(imp.origen_id),
                destino_tipo="pedido_compra",
                destino_id=clon.id,
                monto_imputado=imp.monto_imputado,
                moneda_imputada=imp.moneda_imputada,
                proveedor_id=int(imp.proveedor_id),
                creado_por_id=user_id,
                tipo_cambio=imp.tipo_cambio,
            )
            # Aplicar la nueva imputación en CC del clon (haber compensando
            # el DEBE recién creado).
            from app.services import cc_proveedor_service as _cc  # noqa: PLC0415

            # La imputación más reciente del proveedor con destino clon es la
            # que acabamos de crear — la aplicamos.
            nueva = session.execute(
                select(Imputacion)
                .where(
                    Imputacion.destino_tipo == "pedido_compra",
                    Imputacion.destino_id == clon.id,
                    Imputacion.es_reversal.is_(False),
                )
                .order_by(Imputacion.id.desc())
                .limit(1)
            ).scalar_one()
            _cc.aplicar_imputacion(session, imputacion_id=nueva.id)

        # (e) Recalcular estado del clon por las imputaciones transferidas
        if imputaciones_vigentes:
            recalcular_estado_por_imputaciones(session, pedido_id=clon.id)

    logger.info(
        "pedido_corregido original_id=%s(%s) clon_id=%s(%s) estado_clon=%s "
        "financiero=%s imputaciones=%d adjuntos=%d user_id=%s",
        original.id,
        original.numero,
        clon.id,
        clon.numero,
        estado_clon,
        cambios_financieros_reales,
        len(imputaciones_vigentes),
        n_adjuntos,
        user_id,
    )
    return clon


def _aplicar_transferencia_correccion_al_aprobar(
    session: Session,
    *,
    clon: PedidoCompra,
    user_id: int,
) -> None:
    """Completa la transferencia de imputaciones cuando un clon con
    `corregido_desde_id` se aprueba desde `pendiente_aprobacion`.

    Flujo (disparado post-aprobación normal, en la misma transacción):
      1. Recupera las imputaciones "pendientes_reaplicar" del evento
         `creado_por_correccion_de` del clon.
      2. Para cada una: desimputa (reversal en original) + re-crea en clon
         + aplica la nueva imputación en CC.
      3. Inserta HABER de cancelación en CC del original (compensa el DEBE
         original que hasta ahora seguía "vivo").
      4. Recalcula el estado del clon por imputaciones (puede quedar
         `pagado_parcial`/`pagado`).
      5. Inserta evento `imputaciones_reaplicadas_por_correccion` en el
         clon con snapshot de IDs transferidos.

    NO se dispara si el clon no tiene `corregido_desde_id` (no es un clon)
    o si no hay imputaciones pendientes de transferir.

    Args:
        session: tx activa (misma que llamó a `transicionar(..., 'aprobar')`).
        clon: pedido clon recién aprobado.
        user_id: quien aprobó.
    """
    if clon.corregido_desde_id is None:
        return

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.imputacion import Imputacion  # noqa: PLC0415
    from app.services import imputaciones_service  # noqa: PLC0415

    original = session.get(PedidoCompra, clon.corregido_desde_id)
    if original is None:
        logger.warning(
            "aplicar_transferencia_correccion: clon id=%s sin original válido",
            clon.id,
        )
        return

    # Leer el evento de creación del clon para recuperar los IDs de
    # imputaciones que quedaron congeladas en el original.
    evento = session.execute(
        select(CompraEvento)
        .where(
            CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
            CompraEvento.entidad_id == clon.id,
            CompraEvento.tipo == TiposEvento.CREADO_POR_CORRECCION_DE,
        )
        .order_by(CompraEvento.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    payload = (evento.payload or {}) if evento else {}
    ids_pendientes = list(payload.get("imputaciones_pendientes_reaplicar", []) or [])
    if not ids_pendientes:
        return  # no había nada que transferir

    # Filtrar: solo las que siguen vigentes (podría haber cambiado el estado
    # entre corregir y aprobar — ej. se desimputaron manualmente). Además,
    # excluir las ya transferidas por una aprobación previa (idempotencia).
    imputaciones_a_transferir = (
        session.execute(
            select(Imputacion).where(
                Imputacion.id.in_(ids_pendientes),
                Imputacion.es_reversal.is_(False),
            )
        )
        .scalars()
        .all()
    )
    ids_ya_revertidas = set(
        session.execute(
            select(Imputacion.reimputada_desde_id).where(
                Imputacion.es_reversal.is_(True),
                Imputacion.reimputada_desde_id.in_([imp.id for imp in imputaciones_a_transferir]),
            )
        )
        .scalars()
        .all()
    )
    imputaciones_a_transferir = [imp for imp in imputaciones_a_transferir if imp.id not in ids_ya_revertidas]

    # HABER de cancelación en CC del original (diferido desde el corregir).
    cc_proveedor_service.insertar_mov(
        session,
        proveedor_id=original.proveedor_id,
        empresa_id=original.empresa_id,
        fecha_movimiento=date.today(),
        tipo="ajuste",
        monto=Decimal(original.monto),
        moneda=original.moneda,  # type: ignore[arg-type]
        origen_tipo="cancelacion_pedido_por_correccion",
        origen_id=original.id,
        descripcion=f"Cancelación por corrección {original.numero} → {clon.numero}",
        creado_por_id=user_id,
        signo_ajuste=-1,
    )

    # Transferencia imputación por imputación (append-only).
    transferidas_ids: list[int] = []
    for imp in imputaciones_a_transferir:
        imputaciones_service.desimputar(
            session,
            imputacion_id=int(imp.id),
            user_id=user_id,
            motivo=f"Transferencia por corrección a {clon.numero}",
        )
        imputaciones_service.crear_imputacion(
            session,
            origen_tipo=imp.origen_tipo,
            origen_id=int(imp.origen_id),
            destino_tipo="pedido_compra",
            destino_id=clon.id,
            monto_imputado=imp.monto_imputado,
            moneda_imputada=imp.moneda_imputada,
            proveedor_id=int(imp.proveedor_id),
            creado_por_id=user_id,
            tipo_cambio=imp.tipo_cambio,
        )
        nueva = session.execute(
            select(Imputacion)
            .where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == clon.id,
                Imputacion.es_reversal.is_(False),
            )
            .order_by(Imputacion.id.desc())
            .limit(1)
        ).scalar_one()
        cc_proveedor_service.aplicar_imputacion(session, imputacion_id=nueva.id)
        transferidas_ids.append(int(imp.id))

    if imputaciones_a_transferir:
        recalcular_estado_por_imputaciones(session, pedido_id=clon.id)

    _registrar_evento(
        session,
        pedido=clon,
        tipo=TiposEvento.IMPUTACIONES_REAPLICADAS_POR_CORRECCION,
        usuario_id=user_id,
        payload={
            "original_id": original.id,
            "imputaciones_origen_transferidas": transferidas_ids,
            "cantidad": len(transferidas_ids),
        },
    )
    logger.info(
        "transferencia_correccion_aplicada clon_id=%s original_id=%s transferidas=%d",
        clon.id,
        original.id,
        len(transferidas_ids),
    )


def actualizar_tipo_cambio_manual(
    session: Session,
    *,
    pedido_id: int,
    tipo_cambio: Optional[Decimal],
    motivo: str,
    user_id: int,
) -> "PedidoCompra":
    """
    F5 — Set or clear a manual TC override on a pedido (§3.8, AD-2, AD-3, AD-5).

    Precedence (AD-2):
      1. tipo_cambio_manual is not None → authoritative.
      2. Caso-A weighted average.
      3. tipo_cambio_original.

    Operations:
      - `tipo_cambio` non-null → set/replace override.
        * Stores value in `pedido.tipo_cambio_manual`.
        * Re-derives effective TC via `resolver_tc_efectivo_pedido`.
        * Emits an append-only CC `ajuste` movement for the ARS delta.
      - `tipo_cambio` null → CLEAR override.
        * Sets `pedido.tipo_cambio_manual = None`.
        * Re-derives effective TC (falls back to Caso-A weighted or tipo_cambio_original).
        * Emits CC `ajuste` for the delta from old to new effective TC.

    This is IN-PLACE re-valuation — never cancels+clones the pedido (AD-9).
    `pedido.monto` is NEVER changed.

    Args:
        session: active tx.
        pedido_id: PK of the pedido.
        tipo_cambio: new manual TC (non-null) or None (clear override).
        motivo: reason for audit trail.
        user_id: user performing the change.

    Returns:
        Updated PedidoCompra instance.

    Raises:
        HTTPException 400: motivo is blank.
        HTTPException 400: pedido moneda is not 'USD' (ARS pedidos have no TC).
        HTTPException 404: pedido not found.
        HTTPException 409: pedido state is not in {aprobado, pagado_parcial, pagado}.
    """
    from app.services.cc_proveedor_service import registrar_ajuste_revaluacion_tc  # noqa: PLC0415

    # Validate motivo — must be non-empty after stripping whitespace.
    motivo_limpio = (motivo or "").strip()
    if not motivo_limpio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="motivo no puede estar vacío.",
        )
    motivo = motivo_limpio

    pedido = _obtener_pedido_o_404(session, pedido_id)

    # F5 — TC override only applies to USD pedidos (ARS has no TC concept).
    if pedido.moneda != "USD":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El ajuste de TC manual solo aplica a pedidos en USD.",
        )

    # F5 — TC override is only allowed on financially-active states.
    # ESTADOS_CORREGIBLES = {aprobado, pagado_parcial, pagado}.
    # 'pagado' is included because variance revaluation on a fully-paid USD pedido
    # is a valid operation (e.g. post-close TC audit adjustment).
    # 'cancelado' and 'rechazado' are excluded — no open financial obligation.
    if pedido.estado not in ESTADOS_CORREGIBLES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede ajustar el TC de un pedido en estado '{pedido.estado}'. "
                f"Estados permitidos: {sorted(ESTADOS_CORREGIBLES)}."
            ),
        )

    # Capture old effective TC before any change.
    tc_anterior = resolver_tc_efectivo_pedido(session, pedido)

    # Apply the change.
    pedido.tipo_cambio_manual = tipo_cambio  # None or Decimal

    # Re-derive effective TC with the new override state.
    tc_nuevo = resolver_tc_efectivo_pedido(session, pedido)

    # Write the materialized cache (AD-1).
    # Edge case: if tc_nuevo is None (no Caso-A payments, no tipo_cambio_original —
    # a USD pedido approved when daily TC wasn't available), the cache is left as-is.
    # This is intentional: the stale cache will be overwritten the next time any TC
    # event (Caso-A payment, manual override) resolves a non-None value. A None cache
    # on a USD pedido is already a pre-existing condition, not introduced by F5.
    if tc_nuevo is not None:
        pedido.tipo_cambio = tc_nuevo

    # Emit append-only CC ajuste for the ARS delta (AD-9).
    if tc_anterior is not None and tc_nuevo is not None:
        registrar_ajuste_revaluacion_tc(
            session,
            pedido=pedido,
            tc_anterior=tc_anterior,
            tc_nuevo=tc_nuevo,
            user_id=user_id,
            motivo=motivo,
        )

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.TC_MANUAL_ACTUALIZADO,
        usuario_id=user_id,
        payload={
            "tc_anterior": str(tc_anterior) if tc_anterior is not None else None,
            "tc_nuevo": str(tc_nuevo) if tc_nuevo is not None else None,
            "motivo": motivo,
        },
    )

    session.flush()

    logger.info(
        "actualizar_tipo_cambio_manual pedido_id=%s tc_anterior=%s tc_nuevo=%s motivo=%r user_id=%s",
        pedido.id,
        tc_anterior,
        tc_nuevo,
        motivo,
        user_id,
    )

    return pedido


__all__ = [
    "CAMPOS_EDITABLES_APROBADO",
    "CAMPOS_EDITABLES_BORRADOR",
    "CAMPOS_FINANCIEROS_CORRECCION",
    "ESTADOS_CORREGIBLES",
    "ESTADOS_TERMINALES",
    "EstadoPedido",
    "TRANSICIONES_VALIDAS",
    "TiposEvento",
    # F5 — Manual TC override
    "actualizar_tipo_cambio_manual",
    "ajustar_monto_con_factura",
    "aplicar_imputacion_a_pedido",
    "calcular_saldo_pendiente_pedido",
    "calcular_saldos_pendientes_batch",
    # F2 — ND/NC variance circuit
    "calcular_varianza_tc",
    # F1 — TC re-valuation
    "calcular_tc_ponderado_caso_a",
    "calcular_tc_ponderado_caso_a_batch",
    "calcular_tc_ponderado_pedido",
    "calcular_tc_ponderado_pedido_batch",
    "resolver_tc_efectivo_pedido",
    # F6 — CC ARS display batch resolver
    "resolver_tc_efectivo_pedido_batch",
    "corregir_pedido",
    "crear_pedido",
    "desvincular_factura",
    "editar_pedido",
    "recalcular_estado_por_imputaciones",
    "revertir_transicion_por_anulacion_op",
    "transicionar",
    "vincular_factura",
]
