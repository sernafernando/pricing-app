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
        "tipo_cambio",
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
    # Batch I — vinculación manual factura ERP + ajuste de monto controlado
    FACTURA_VINCULADA: Final[str] = "factura_vinculada"
    FACTURA_DESVINCULADA: Final[str] = "factura_desvinculada"
    MONTO_AJUSTADO_POR_FACTURA: Final[str] = "monto_ajustado_por_factura"
    MONTO_DIFIERE_AL_MATCHEAR: Final[str] = "monto_difiere_al_matchear"


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
    ct_docnumber, ct_total, _curr_id = match

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

    Genera:
      1) Movimiento en `cc_proveedor_movimientos` por la diferencia
         (`tipo='ajuste'`, `signo_ajuste=+1` si nuevo>actual, `-1` si es
         menor; `origen_tipo='ajuste_pedido'`, `origen_id=pedido.id`).
         Si la diferencia es 0 → NO se emite movimiento CC, pero SÍ se
         vincula y se registra el evento.
      2) Update `pedido.monto`, `pedido.ct_transaction_id`.
      3) Evento `monto_ajustado_por_factura` con `{monto_anterior,
         monto_nuevo, diferencia, ct_transaction, motivo}`.

    IMPORTANTE — append-only: las imputaciones y movimientos CC previos NO
    se tocan. El ajuste es un movimiento NUEVO en CC. Si el pedido ya
    estaba pagado por un monto viejo distinto, el ajuste refleja el delta
    contra el proveedor pero NO cambia las imputaciones existentes.

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
    ct_docnumber, _ct_total, _curr_id = match

    monto_anterior = Decimal(pedido.monto)
    nuevo_monto_dec = Decimal(str(nuevo_monto))
    diferencia = nuevo_monto_dec - monto_anterior

    if diferencia != Decimal("0"):
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

    _registrar_evento(
        session,
        pedido=pedido,
        tipo=TiposEvento.MONTO_AJUSTADO_POR_FACTURA,
        usuario_id=user_id,
        payload={
            "monto_anterior": str(monto_anterior),
            "monto_nuevo": str(nuevo_monto_dec),
            "diferencia": str(diferencia),
            "ct_transaction": int(ct_transaction),
            "ct_docnumber": ct_docnumber,
            "motivo": motivo_normalizado,
        },
    )
    logger.info(
        "pedido_ajustar_monto id=%s %s → %s (dif=%s) ct=%s user=%s",
        pedido.id,
        monto_anterior,
        nuevo_monto_dec,
        diferencia,
        ct_transaction,
        user_id,
    )
    return pedido


def monto_normalizar(valor: Decimal) -> str:
    """Representa un Decimal con 2 decimales para descripciones legibles."""
    return f"{Decimal(valor):.2f}"


__all__ = [
    "CAMPOS_EDITABLES_APROBADO",
    "CAMPOS_EDITABLES_BORRADOR",
    "ESTADOS_TERMINALES",
    "EstadoPedido",
    "TRANSICIONES_VALIDAS",
    "TiposEvento",
    "ajustar_monto_con_factura",
    "aplicar_imputacion_a_pedido",
    "calcular_saldo_pendiente_pedido",
    "crear_pedido",
    "desvincular_factura",
    "editar_pedido",
    "recalcular_estado_por_imputaciones",
    "revertir_transicion_por_anulacion_op",
    "transicionar",
    "vincular_factura",
]
