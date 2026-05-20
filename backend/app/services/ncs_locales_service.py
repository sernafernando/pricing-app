"""
ncs_locales_service — flujo de notas de crédito locales (compras v2).

Implementa el ciclo de vida de `notas_credito_local` con un patrón análogo
a `pedidos_service`:
  - Creación en estado `borrador` con numeración correlativa NC-XX-YYYY-NNNNN.
  - Edición restringida por estado (solo borrador).
  - Matriz de transiciones manuales (enviar_aprobacion, aprobar, rechazar,
    reabrir, cancelar, cancelar_aprobado).
  - Transiciones automáticas desde imputaciones (aprobado → aplicada_parcial
    → aplicada, y reversos al desimputar).
  - Eventos polimórficos en `compras_eventos` con
    `entidad_tipo='nota_credito_local'`.
  - Vinculación manual con factura ERP + ajuste controlado de monto
    (mismo patrón que pedidos — Batch I previo).

DECISIÓN CLAVE DE DISEÑO (T.6 del spec):
========================================
Cuando la NC pasa a 'aprobado', NO se inserta movimiento en CC proveedor.
La NC es CRÉDITO DISPONIBLE — solo impacta CC cuando se imputa a un pedido
o factura específica vía `imputaciones_service`.

Patrón análogo a OPs: la OP creada NO toca caja hasta `ejecutar_pago`.
Distinto de pedidos: pedido aprobado SÍ inserta DEBE en CC porque
representa deuda reconocida.

Esta asimetría es intencional:
  - pedidos: deuda = se debe al proveedor (DEBE).
  - ncs_locales: crédito = el proveedor nos debe reducir deuda (HABER que
    se realiza al imputar).

Responsabilidad del caller:
  - Ejecutar dentro de una transacción (`session.commit()` / `rollback()`).
  - Validar permisos vía dependency FastAPI antes de llamar al servicio.

Referencias:
  - Spec compras v2 (T.1 — T.6, T.10).
  - Patrón base: `pedidos_service.py`, `ordenes_pago_service.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import VARIANZA_TC_THRESHOLD_ARS
from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.services import numeracion_service

logger = get_logger("services.ncs_locales_service")


# ──────────────────────────────────────────────────────────────────────────
# Tipos y constantes
# ──────────────────────────────────────────────────────────────────────────


EstadoNCLocal = Literal[
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "aplicada_parcial",
    "aplicada",
]

# Estados terminales (no admiten transición salvo cancelar_definitivo desde rechazado).
ESTADOS_TERMINALES: Final[frozenset[str]] = frozenset({"cancelado", "aplicada"})

# Campos editables por estado.
CAMPOS_EDITABLES_BORRADOR: Final[frozenset[str]] = frozenset(
    {
        "moneda",
        "monto",
        "tipo_cambio",
        "fecha_emision",
        "numero_nc_proveedor",
        "motivo",
        "observaciones",
    }
)


# Matriz de transiciones manuales.
#   clave: (estado_origen, accion) → estado_destino
TRANSICIONES_VALIDAS: Final[dict[tuple[str, str], str]] = {
    ("borrador", "enviar_aprobacion"): "pendiente_aprobacion",
    ("borrador", "cancelar"): "cancelado",
    ("pendiente_aprobacion", "aprobar"): "aprobado",
    ("pendiente_aprobacion", "rechazar_devolver"): "rechazado",
    ("pendiente_aprobacion", "rechazar_cancelar"): "cancelado",
    ("rechazado", "reabrir"): "borrador",
    ("rechazado", "cancelar_definitivo"): "cancelado",
    ("aprobado", "cancelar_aprobado"): "cancelado",
    ("aplicada_parcial", "cancelar_aprobado"): "cancelado",
}


class TiposEventoNC:
    """Tipos de evento (compras_eventos.tipo) para NCs locales."""

    CREADA: Final[str] = "nc_creada"
    EDITADA: Final[str] = "nc_editada"
    ENVIADA_APROBACION: Final[str] = "nc_enviada_aprobacion"
    APROBADA: Final[str] = "nc_aprobada"
    RECHAZADA: Final[str] = "nc_rechazada"
    REABIERTA: Final[str] = "nc_reabierta"
    CANCELADA: Final[str] = "nc_cancelada"
    CANCELACION_APROBADA: Final[str] = "nc_cancelacion_aprobada"
    APLICADA_PARCIAL: Final[str] = "nc_aplicada_parcial"
    APLICADA: Final[str] = "nc_aplicada"
    REABIERTA_POR_REVERSAL: Final[str] = "nc_reabierta_por_reversal"
    FACTURA_ERP_VINCULADA: Final[str] = "nc_factura_erp_vinculada"
    FACTURA_ERP_DESVINCULADA: Final[str] = "nc_factura_erp_desvinculada"
    MONTO_AJUSTADO_POR_ERP: Final[str] = "nc_monto_ajustado_por_erp"
    MONTO_DIFIERE_AL_MATCHEAR_ERP: Final[str] = "nc_monto_difiere_al_matchear_erp"


# ──────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────


def _registrar_evento(
    session: Session,
    *,
    nc: NotaCreditoLocal,
    tipo: str,
    usuario_id: int,
    payload: Optional[dict[str, Any]] = None,
) -> CompraEvento:
    """Inserta evento polimórfico en `compras_eventos`."""
    evento = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_NC_LOCAL,
        entidad_id=nc.id,
        tipo=tipo,
        usuario_id=usuario_id,
        payload=payload,
    )
    session.add(evento)
    session.flush()
    return evento


def _obtener_nc_o_404(session: Session, nc_id: int) -> NotaCreditoLocal:
    nc = session.get(NotaCreditoLocal, nc_id)
    if nc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NotaCreditoLocal id={nc_id} no encontrada.",
        )
    return nc


def _serializar_valor(valor: Any) -> Any:
    """Convierte tipos no-JSON-serializables a string."""
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def _resolver_tipo_cambio(
    session: Session,
    *,
    moneda: str,
    tipo_cambio: Optional[Decimal],
) -> Optional[Decimal]:
    """
    Valida coherencia `moneda` ↔ `tipo_cambio` y autollena el TC del día
    cuando corresponde (mismo helper que pedidos_service).

    Reglas:
      - moneda='ARS' + tipo_cambio!=None  → HTTP 400.
      - moneda='ARS' + tipo_cambio=None   → return None.
      - moneda='USD' + tipo_cambio>0      → return tipo_cambio.
      - moneda='USD' + tipo_cambio<=0     → HTTP 400.
      - moneda='USD' + tipo_cambio=None   → intenta leer TC del día (best-effort).
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
                "ncs_locales_service: TC del día no disponible para USD (fecha=%s). "
                "NC se creará con tipo_cambio=NULL — el usuario deberá editarlo.",
                hoy,
            )
            return None
        return Decimal(str(tc_row.venta))

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"moneda inválida: '{moneda}' (esperado ARS|USD).",
    )


# ──────────────────────────────────────────────────────────────────────────
# Saldo pendiente
# ──────────────────────────────────────────────────────────────────────────


def calcular_saldo_pendiente(session: Session, nc_id: int) -> Decimal:
    """
    Saldo pendiente = monto - (imputaciones no-reversal - imputaciones reversal)
    donde origen = ('nota_credito_local', nc_id).

    Append-only compliant: las desimputaciones SUMAN al saldo pendiente
    (porque inserta una fila reversal que compensa la original).
    """
    nc = _obtener_nc_o_404(session, nc_id)

    imputado_no_reversal = session.execute(
        select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.origen_id == nc.id,
            Imputacion.es_reversal.is_(False),
        )
    ).scalar_one()
    imputado_reversal = session.execute(
        select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.origen_id == nc.id,
            Imputacion.es_reversal.is_(True),
        )
    ).scalar_one()

    imputado_efectivo = Decimal(imputado_no_reversal) - Decimal(imputado_reversal)
    return Decimal(nc.monto) - imputado_efectivo


# ──────────────────────────────────────────────────────────────────────────
# Alta (creación)
# ──────────────────────────────────────────────────────────────────────────


def crear(
    session: Session,
    *,
    empresa_id: int,
    proveedor_id: int,
    moneda: Literal["ARS", "USD"],
    monto: Decimal,
    fecha_emision: date,
    motivo: str,
    creado_por_id: int,
    tipo_cambio: Optional[Decimal] = None,
    numero_nc_proveedor: Optional[str] = None,
    observaciones: Optional[str] = None,
    tipo: Literal["credito", "debito"] = "credito",
) -> NotaCreditoLocal:
    """
    Crea una NC local en estado `borrador` con número correlativo.

    Validaciones:
      - `monto > 0`.
      - Coherencia `moneda` ↔ `tipo_cambio` (vía `_resolver_tipo_cambio`).
      - `motivo` no vacío.

    Genera número via `numeracion_service.generar_siguiente_numero(tipo='nota_credito')`.
    Inserta evento `nc_creada` en `compras_eventos`.

    NO commit — responsabilidad del caller.

    Args:
        session: tx activa.
        empresa_id, proveedor_id: FKs.
        moneda: 'ARS' o 'USD'.
        monto: Decimal > 0.
        fecha_emision: fecha en que el proveedor emitió la NC.
        motivo: texto obligatorio.
        creado_por_id: FK usuarios.
        tipo_cambio: opcional, solo USD (autollena del día si es None).
        numero_nc_proveedor: opcional, llave de matching contra ERP.
        observaciones: texto libre opcional.
        tipo: 'credito' (HABER, default) o 'debito' (DEBE, Nota de Débito por varianza TC).

    Returns:
        La `NotaCreditoLocal` recién creada con `id` asignado.

    Raises:
        HTTPException 400: por validaciones de monto/moneda/motivo/TC.
    """
    if monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto debe ser > 0 (recibido: {monto}).",
        )

    motivo_norm = (motivo or "").strip()
    if not motivo_norm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="motivo es obligatorio (texto no vacío).",
        )

    tc_resuelto = _resolver_tipo_cambio(session, moneda=moneda, tipo_cambio=tipo_cambio)

    numero, _ = numeracion_service.generar_siguiente_numero(
        session,
        tipo="nota_credito",
        empresa_id=empresa_id,
    )

    nc = NotaCreditoLocal(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda=moneda,
        monto=monto,
        tipo_cambio=tc_resuelto,
        fecha_emision=fecha_emision,
        numero_nc_proveedor=numero_nc_proveedor,
        motivo=motivo_norm,
        observaciones=observaciones,
        estado="borrador",
        creado_por_id=creado_por_id,
        # F2 — directional tipo: 'credito' (HABER) or 'debito' (DEBE).
        tipo=tipo,
    )
    session.add(nc)
    session.flush()

    _registrar_evento(
        session,
        nc=nc,
        tipo=TiposEventoNC.CREADA,
        usuario_id=creado_por_id,
        payload={
            "numero": numero,
            "proveedor_id": proveedor_id,
            "empresa_id": empresa_id,
            "moneda": moneda,
            "monto": str(monto),
            "tipo_cambio": str(tc_resuelto) if tc_resuelto is not None else None,
            "fecha_emision": fecha_emision.isoformat(),
            "numero_nc_proveedor": numero_nc_proveedor,
            "tipo": tipo,
        },
    )

    logger.info(
        "nc_local_creada id=%s numero=%s proveedor_id=%s empresa_id=%s monto=%s %s",
        nc.id,
        numero,
        proveedor_id,
        empresa_id,
        monto,
        moneda,
    )
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Edición
# ──────────────────────────────────────────────────────────────────────────


def editar(
    session: Session,
    *,
    nc_id: int,
    user_id: int,
    **campos: Any,
) -> NotaCreditoLocal:
    """
    Edita una NC local. SOLO permitido en estado 'borrador'.

    Otros estados → HTTP 409 (NO se editan NCs aprobadas; si hay error,
    cancelar y crear nueva).

    Args:
        session: tx activa.
        nc_id: PK.
        user_id: usuario (auditoría).
        **campos: campos a actualizar (filtra a `CAMPOS_EDITABLES_BORRADOR`).

    Returns:
        La NC actualizada.

    Raises:
        HTTPException 404: NC inexistente.
        HTTPException 409: NC fuera de estado 'borrador'.
        HTTPException 400: validaciones de monto/moneda/motivo/TC.
    """
    nc = _obtener_nc_o_404(session, nc_id)

    if nc.estado != "borrador":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"NC local id={nc.id} en estado '{nc.estado}' no es editable. "
                f"Solo se editan NCs en 'borrador'. Si el dato es incorrecto, "
                f"cancelá y creá una nueva NC."
            ),
        )

    aplicables = {k: v for k, v in campos.items() if k in CAMPOS_EDITABLES_BORRADOR and v is not None}
    rechazados = {k: v for k, v in campos.items() if k not in CAMPOS_EDITABLES_BORRADOR and v is not None}
    if rechazados:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Campos no editables: {sorted(rechazados.keys())}. "
                f"Editables en borrador: {sorted(CAMPOS_EDITABLES_BORRADOR)}."
            ),
        )

    # Validaciones puntuales
    if "monto" in aplicables:
        nuevo_monto = Decimal(str(aplicables["monto"]))
        if nuevo_monto <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"monto debe ser > 0 (recibido: {nuevo_monto}).",
            )
        aplicables["monto"] = nuevo_monto

    if "moneda" in aplicables and aplicables["moneda"] not in {"ARS", "USD"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"moneda inválida: '{aplicables['moneda']}'.",
        )

    if "motivo" in aplicables:
        motivo_norm = str(aplicables["motivo"]).strip()
        if not motivo_norm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="motivo no puede ser vacío.",
            )
        aplicables["motivo"] = motivo_norm

    # Coherencia moneda ↔ tipo_cambio
    if "tipo_cambio" in aplicables or "moneda" in aplicables:
        moneda_final = aplicables.get("moneda", nc.moneda)
        if "tipo_cambio" in aplicables:
            aplicables["tipo_cambio"] = _resolver_tipo_cambio(
                session,
                moneda=moneda_final,
                tipo_cambio=aplicables.get("tipo_cambio"),
            )
        elif "moneda" in aplicables and moneda_final == "ARS" and nc.tipo_cambio is not None:
            aplicables["tipo_cambio"] = None
        elif "moneda" in aplicables and moneda_final == "USD" and nc.tipo_cambio is None:
            aplicables["tipo_cambio"] = _resolver_tipo_cambio(session, moneda="USD", tipo_cambio=None)

    diff: dict[str, dict[str, Any]] = {}
    for campo, nuevo_valor in aplicables.items():
        anterior = getattr(nc, campo)
        if anterior != nuevo_valor:
            diff[campo] = {"antes": _serializar_valor(anterior), "despues": _serializar_valor(nuevo_valor)}
            setattr(nc, campo, nuevo_valor)

    if not diff:
        return nc

    session.flush()
    _registrar_evento(
        session,
        nc=nc,
        tipo=TiposEventoNC.EDITADA,
        usuario_id=user_id,
        payload={"campos_cambiados": diff},
    )

    logger.info(
        "nc_local_editada id=%s campos=%s",
        nc.id,
        sorted(diff.keys()),
    )
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Transiciones (state machine)
# ──────────────────────────────────────────────────────────────────────────


def transicionar(
    session: Session,
    *,
    nc_id: int,
    accion: str,
    user_id: int,
    motivo: Optional[str] = None,
) -> NotaCreditoLocal:
    """
    Aplica una transición manual según `TRANSICIONES_VALIDAS`.

    Acciones (matriz):
      - `enviar_aprobacion`, `cancelar` (desde borrador)
      - `aprobar`, `rechazar_devolver`, `rechazar_cancelar` (desde pendiente_aprobacion)
      - `reabrir`, `cancelar_definitivo` (desde rechazado)
      - `cancelar_aprobado` (desde aprobado o aplicada_parcial — revierte imputaciones)

    SIDE EFFECTS — DECISIÓN DE DISEÑO (ver docstring del módulo):
    ============================================================
    Cuando la NC pasa a 'aprobado', NO se inserta movimiento en CC proveedor.
    La NC es crédito DISPONIBLE — solo impacta CC cuando se imputa a un pedido
    o factura específica vía imputaciones_service.

    Patrón análogo a OPs: la OP creada no toca caja hasta ejecutar_pago.
    Distinto de pedidos: pedido aprobado SÍ inserta DEBE en CC porque
    representa deuda reconocida.

    Esta asimetría es intencional:
      - pedidos: deuda = se debe al proveedor (DEBE).
      - ncs_locales: crédito = el proveedor nos debe reducir deuda (HABER que
        se realiza al imputar).

    Side effects en `cancelar_aprobado`:
      - Si la NC tiene imputaciones activas (es_reversal=False), invoca
        `imputaciones_service.revertir_imputaciones_de_origen` que crea los
        reversals correspondientes y dispara los DEBE compensatorios en CC.
      - Para cada destino `pedido_compra` afectado, recalcula el estado del
        pedido vía `pedidos_service.aplicar_imputacion_a_pedido` (igual al
        flujo de `ordenes_pago_service.anular`).

    Args:
        session: tx activa.
        nc_id: PK.
        accion: clave de la matriz.
        user_id: ejecutor (auditoría + aprobador).
        motivo: texto libre — obligatorio para `rechazar_*`, `cancelar_*`.

    Returns:
        La NC con el nuevo estado.

    Raises:
        HTTPException 404: NC inexistente.
        HTTPException 400: transición inválida.
    """
    nc = _obtener_nc_o_404(session, nc_id)

    clave = (nc.estado, accion)
    if clave not in TRANSICIONES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transición no permitida: estado='{nc.estado}' accion='{accion}'. "
                f"Combos válidos: {sorted(TRANSICIONES_VALIDAS.keys())}."
            ),
        )

    nuevo_estado = TRANSICIONES_VALIDAS[clave]
    estado_previo = nc.estado
    payload: dict[str, Any] = {"estado_previo": estado_previo, "estado_nuevo": nuevo_estado}
    if motivo:
        payload["motivo"] = motivo

    # Side effects específicos por acción
    if accion == "aprobar":
        nc.aprobado_por_id = user_id
        # NO se inserta movimiento CC. Ver docstring (decisión T.6).

    elif accion == "cancelar_aprobado":
        # Revertir imputaciones activas (si existen) en append-only.
        # Capturamos los pedidos afectados ANTES del reversal para luego
        # recalcular su estado (mismo patrón que ordenes_pago_service.anular).
        from app.services import imputaciones_service, pedidos_service  # noqa: PLC0415

        imps_activas_stmt = select(Imputacion).where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.origen_id == nc.id,
            Imputacion.es_reversal.is_(False),
        )
        imps_activas = list(session.execute(imps_activas_stmt).scalars().all())
        pedidos_afectados: set[int] = set()
        for imp in imps_activas:
            if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None:
                pedidos_afectados.add(int(imp.destino_id))

        reversals = imputaciones_service.revertir_imputaciones_de_origen(
            session,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            user_id=user_id,
            motivo=f"cancelacion_aprobada_nc: {motivo or 'sin motivo'}",
        )
        payload["reversals_creados"] = [r.id for r in reversals]
        payload["pedidos_afectados"] = sorted(pedidos_afectados)

        # Recalcular estado de pedidos afectados (puede volver a aprobado o
        # quedar pagado_parcial dependiendo de otras imputaciones vivas).
        for ped_id in pedidos_afectados:
            pedidos_service.revertir_transicion_por_anulacion_op(
                session,
                pedido_id=ped_id,
                user_id=user_id,
            )

    nc.estado = nuevo_estado
    session.flush()

    tipo_evento = _tipo_evento_para_accion(accion)
    _registrar_evento(
        session,
        nc=nc,
        tipo=tipo_evento,
        usuario_id=user_id,
        payload=payload,
    )

    logger.info(
        "nc_local_transicion id=%s %s --(%s)--> %s user_id=%s",
        nc.id,
        estado_previo,
        accion,
        nuevo_estado,
        user_id,
    )
    return nc


def _tipo_evento_para_accion(accion: str) -> str:
    """Mapea accion → tipo de evento."""
    mapping = {
        "enviar_aprobacion": TiposEventoNC.ENVIADA_APROBACION,
        "aprobar": TiposEventoNC.APROBADA,
        "rechazar_devolver": TiposEventoNC.RECHAZADA,
        "rechazar_cancelar": TiposEventoNC.CANCELADA,
        "reabrir": TiposEventoNC.REABIERTA,
        "cancelar_definitivo": TiposEventoNC.CANCELADA,
        "cancelar": TiposEventoNC.CANCELADA,
        "cancelar_aprobado": TiposEventoNC.CANCELACION_APROBADA,
    }
    return mapping.get(accion, accion)


# ──────────────────────────────────────────────────────────────────────────
# Transiciones automáticas (disparadas por imputaciones)
# ──────────────────────────────────────────────────────────────────────────


def aplicar_imputacion_a_nc(
    session: Session,
    *,
    nc_id: int,
    monto_imputado: Decimal,  # noqa: ARG001 — informativo, el cálculo usa saldo
) -> NotaCreditoLocal:
    """
    Llamada INTERNA desde `imputaciones_service.crear_imputacion` cuando una
    NC local se usa como origen.

    Transiciones automáticas:
      - `aprobado` + imp parcial → `aplicada_parcial`
      - `aprobado` + imp total   → `aplicada`
      - `aplicada_parcial` + imp que cubre el resto → `aplicada`
      - Otros estados → no-op (defensivo).

    NO toca CC (el HABER lo proyecta `cc_proveedor_service.aplicar_imputacion`
    invocado por el orquestador, no por este servicio).

    Args:
        session: tx activa.
        nc_id: PK.
        monto_imputado: informativo — el cálculo real usa
            `calcular_saldo_pendiente(nc_id)`.

    Returns:
        La NC con estado potencialmente actualizado.
    """
    nc = _obtener_nc_o_404(session, nc_id)
    if nc.estado not in {"aprobado", "aplicada_parcial"}:
        # Estado fuera de la matriz automática — no-op defensivo.
        return nc

    saldo = calcular_saldo_pendiente(session, nc.id)
    estado_previo = nc.estado

    if saldo <= Decimal("0"):
        nuevo_estado = "aplicada"
        tipo_evento = TiposEventoNC.APLICADA
    else:
        if nc.estado == "aprobado":
            nuevo_estado = "aplicada_parcial"
            tipo_evento = TiposEventoNC.APLICADA_PARCIAL
        else:
            # Ya estaba aplicada_parcial y todavía hay saldo → no-op.
            return nc

    if nuevo_estado == estado_previo:
        return nc

    nc.estado = nuevo_estado  # type: ignore[assignment]
    session.flush()

    _registrar_evento(
        session,
        nc=nc,
        tipo=tipo_evento,
        usuario_id=nc.creado_por_id,  # auto-transición sin user explícito
        payload={
            "estado_previo": estado_previo,
            "estado_nuevo": nuevo_estado,
            "saldo_pendiente": str(saldo),
        },
    )
    logger.info(
        "nc_local_auto_transicion id=%s %s -> %s (saldo=%s)",
        nc.id,
        estado_previo,
        nuevo_estado,
        saldo,
    )
    return nc


def recalcular_estado_por_imputaciones(
    session: Session,
    *,
    nc_id: int,
) -> NotaCreditoLocal:
    """
    Recalcula el estado de una NC local en base al saldo pendiente actual.
    Llamado por `imputaciones_service.desimputar` cuando el reversal afecta
    a una NC local (puede subir el saldo y bajar el estado de aplicada al
    nivel anterior).

    Matriz simétrica a `aplicar_imputacion_a_nc`:
      - `aplicada` con saldo > 0 → `aplicada_parcial`
      - `aplicada_parcial` con saldo == monto (todas reversadas) → `aprobado`
      - Otros estados → no-op.

    Útil cuando se desimputa una NC ya aplicada y necesitamos "reabrirla"
    para nuevas imputaciones.
    """
    nc = _obtener_nc_o_404(session, nc_id)
    if nc.estado not in {"aplicada", "aplicada_parcial"}:
        return nc

    saldo = calcular_saldo_pendiente(session, nc.id)
    estado_previo = nc.estado

    if saldo >= Decimal(nc.monto):
        # Todas las imputaciones reversadas → vuelve a 'aprobado'.
        nuevo_estado = "aprobado"
    elif saldo > Decimal("0"):
        nuevo_estado = "aplicada_parcial"
    else:
        # saldo <= 0 → sigue 'aplicada'.
        return nc

    if nuevo_estado == estado_previo:
        return nc

    nc.estado = nuevo_estado  # type: ignore[assignment]
    session.flush()
    _registrar_evento(
        session,
        nc=nc,
        tipo=TiposEventoNC.REABIERTA_POR_REVERSAL,
        usuario_id=nc.creado_por_id,
        payload={
            "estado_previo": estado_previo,
            "estado_nuevo": nuevo_estado,
            "saldo_pendiente": str(saldo),
            "motivo": "desimputacion",
        },
    )
    logger.info(
        "nc_local_recalculo id=%s %s -> %s (saldo=%s)",
        nc.id,
        estado_previo,
        nuevo_estado,
        saldo,
    )
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Vinculación con factura ERP
# ──────────────────────────────────────────────────────────────────────────


def _buscar_nc_erp_para_proveedor(
    session: Session,
    *,
    ct_transaction: int,
    supp_id: int,
) -> Optional[tuple[str, Decimal, int]]:
    """
    Busca en `tb_commercial_transactions` una NC de compra (sd_iscreditnote=true
    AND sd_ispurchase=true) que matchee con la ct dada Y pertenezca al supp_id.

    Returns:
        Tupla `(ct_docnumber, ct_total, curr_id_transaction)` o None.
    """
    from sqlalchemy import text  # noqa: PLC0415

    stmt = text(
        """
        SELECT ct.ct_docnumber, ct.ct_total, ct.curr_id_transaction
        FROM tb_commercial_transactions ct
        JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
        WHERE ct.ct_transaction = :ct
          AND ct.supp_id = :supp_id
          AND sd.sd_iscreditnote = TRUE
          AND sd.sd_ispurchase = TRUE
          AND COALESCE(ct.ct_iscancelled, FALSE) = FALSE
        LIMIT 1
        """
    )
    fila = session.execute(stmt, {"ct": ct_transaction, "supp_id": supp_id}).first()
    if fila is None:
        return None
    ct_docnumber, ct_total, curr_id = fila
    return str(ct_docnumber or ""), Decimal(str(ct_total or 0)), int(curr_id or 0)


def vincular_factura_erp(
    session: Session,
    *,
    nc_local_id: int,
    ct_transaction: int,
    user_id: int,
    ajustar_monto: bool = False,
    nuevo_monto: Optional[Decimal] = None,
    motivo_ajuste: Optional[str] = None,
) -> NotaCreditoLocal:
    """
    Vincula manual la NC local con una NC del ERP (sd_iscreditnote=true AND
    supp_id matchea), patrón análogo a `pedidos_service.vincular_factura` +
    `ajustar_monto_con_factura`.

    Si `ajustar_monto=True`:
      - Requiere permiso `administracion.ajustar_monto_pedido` (validado por
        el router — reusamos el mismo permiso para NCs por política de
        seguridad: quien ajusta plata, ajusta plata, sin importar la entidad).
      - Requiere `nuevo_monto > 0` y `motivo_ajuste` no vacío.
      - Si la NC ya tenía imputaciones activas y la diferencia altera el
        saldo, el caller debe ser consciente: el ajuste NO revierte
        imputaciones ya aplicadas (mismo patrón que pedidos — append-only).

    Inserta evento `nc_factura_erp_vinculada` o `nc_monto_ajustado_por_erp`.

    NO commit. NO se inserta movimiento CC en este flujo (la NC NO impacta
    CC al aprobarse; los ajustes de monto que sí afectan CC se canalizan
    via imputación posterior, no acá).

    Raises:
        HTTPException 404: NC inexistente.
        HTTPException 409: NC ya vinculada a otra ct.
        HTTPException 400: ct no existe en ERP para ese proveedor / args inválidos.
    """
    from sqlalchemy import text  # noqa: PLC0415

    nc = _obtener_nc_o_404(session, nc_local_id)

    if nc.ct_transaction_id is not None and int(nc.ct_transaction_id) != int(ct_transaction):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"NC local id={nc.id} ya está vinculada a "
                f"ct_transaction={nc.ct_transaction_id}. "
                f"Desvinculá antes de vincular otra."
            ),
        )

    supp_id = session.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": nc.proveedor_id},
    ).scalar_one_or_none()
    if supp_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Proveedor id={nc.proveedor_id} no tiene supp_id ERP — no se puede vincular NC del ERP."),
        )

    match = _buscar_nc_erp_para_proveedor(
        session,
        ct_transaction=ct_transaction,
        supp_id=int(supp_id),
    )
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ct_transaction={ct_transaction} no es una NC vigente del ERP "
                f"para el proveedor id={nc.proveedor_id} (supp_id={supp_id})."
            ),
        )
    ct_docnumber, ct_total, _curr_id = match

    if ajustar_monto:
        # Validaciones de ajuste
        if nuevo_monto is None or nuevo_monto <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ajustar_monto=True requiere nuevo_monto > 0 (recibido: {nuevo_monto}).",
            )
        motivo_norm = (motivo_ajuste or "").strip()
        if not motivo_norm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ajustar_monto=True requiere motivo_ajuste no vacío.",
            )

        monto_anterior = Decimal(nc.monto)
        nuevo_monto_dec = Decimal(str(nuevo_monto))
        diferencia = nuevo_monto_dec - monto_anterior

        nc.monto = nuevo_monto_dec  # type: ignore[assignment]
        nc.ct_transaction_id = int(ct_transaction)
        session.flush()

        _registrar_evento(
            session,
            nc=nc,
            tipo=TiposEventoNC.MONTO_AJUSTADO_POR_ERP,
            usuario_id=user_id,
            payload={
                "monto_anterior": str(monto_anterior),
                "monto_nuevo": str(nuevo_monto_dec),
                "diferencia": str(diferencia),
                "ct_transaction": int(ct_transaction),
                "ct_docnumber": ct_docnumber,
                "ct_total": str(ct_total),
                "motivo": motivo_norm,
            },
        )
        logger.info(
            "nc_local_ajuste_monto id=%s %s -> %s (dif=%s) ct=%s user=%s",
            nc.id,
            monto_anterior,
            nuevo_monto_dec,
            diferencia,
            ct_transaction,
            user_id,
        )
    else:
        nc.ct_transaction_id = int(ct_transaction)
        session.flush()

        _registrar_evento(
            session,
            nc=nc,
            tipo=TiposEventoNC.FACTURA_ERP_VINCULADA,
            usuario_id=user_id,
            payload={
                "ct_transaction": int(ct_transaction),
                "ct_docnumber": ct_docnumber,
                "ct_total": str(ct_total),
                "monto_nc": str(nc.monto),
                "modo": "manual",
            },
        )
        logger.info(
            "nc_local_vincular_factura id=%s ct=%s docnumber=%s",
            nc.id,
            ct_transaction,
            ct_docnumber,
        )

    return nc


def desvincular_factura_erp(
    session: Session,
    *,
    nc_local_id: int,
    user_id: int,
) -> NotaCreditoLocal:
    """
    Desvincula la NC del ERP. Análogo a `pedidos_service.desvincular_factura`.

    NO revierte ajustes de monto previos (los ajustes quedaron registrados
    en eventos; revertirlos requiere edición manual con motivo).

    Raises:
        HTTPException 404: NC inexistente.
        HTTPException 400: NC sin ct_transaction_id.
    """
    nc = _obtener_nc_o_404(session, nc_local_id)
    if nc.ct_transaction_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"NC local id={nc.id} no tiene factura ERP vinculada.",
        )

    ct_anterior = int(nc.ct_transaction_id)
    nc.ct_transaction_id = None
    session.flush()

    _registrar_evento(
        session,
        nc=nc,
        tipo=TiposEventoNC.FACTURA_ERP_DESVINCULADA,
        usuario_id=user_id,
        payload={"ct_transaction_anterior": ct_anterior},
    )
    logger.info(
        "nc_local_desvincular_factura id=%s ct_anterior=%s",
        nc.id,
        ct_anterior,
    )
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Helpers para futura papelera (v2.2)
# ──────────────────────────────────────────────────────────────────────────


def puede_eliminar_nc_local(
    session: Session,  # noqa: ARG001
    nc: NotaCreditoLocal,
) -> tuple[bool, Optional[str]]:
    """
    Devuelve `(puede_eliminar, motivo_negacion)` para integrar con la papelera
    auditable en una versión futura.

    v1 de esta feature NO incluye hard-delete — las NCs se cancelan pero NO
    se borran. Esta función queda definida por consistencia con el patrón
    de pedidos/OPs y para que el frontend pueda mostrar el flag
    `puede_eliminar=False` con el motivo correcto.

    NOTA: papelera de NCs locales se implementa en v2.2 (futuro batch).
    """
    return False, "Hard-delete de NCs locales no implementado en v2.1 (futuro v2.2)."


def resolver_varianza_tc(
    session: Session,
    *,
    pedido_id: int,
    user_id: int,
) -> int:
    """
    F2 — Resolve TC variance for a USD pedido de compra by creating and imputing
    a ND (tipo='debito') when TC rose, or an NC (tipo='credito') when TC fell.

    Steps (atomic — caller owns the transaction):
      1. Load the pedido and compute varianza_tc_neta via pedidos_service.
      2. Raise ValueError if varianza == 0 (nothing to resolve).
      3. Determine tipo and monto_abs = abs(varianza).
      4. Create ND or NC in 'borrador', approve it (borrador → pendiente_aprobacion → aprobado).
      5. Create imputacion from the ND/NC to the pedido_compra.
      6. Apply the imputacion to CC (cc_proveedor_service.aplicar_imputacion).

    Args:
        session: active tx.
        pedido_id: PK of the PedidoCompra to resolve.
        user_id: FK to usuarios (creador / aprobador de la ND/NC).

    Returns:
        int — ID of the created NotaCreditoLocal (ND or NC).

    Raises:
        ValueError: if abs(varianza_tc_neta) <= 1.00 ARS (within threshold — nothing to resolve).
        HTTPException 404: if pedido_id not found.

    Note on permissions: the auto-approve step bypasses the normal aprobar_ncs_locales check
    because this ND/NC is system-derived (not hand-entered), and the resolver endpoint is
    already gated by administracion.gestionar_ordenes_compra.
    """
    from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415
    from app.services import cc_proveedor_service, imputaciones_service, pedidos_service  # noqa: PLC0415

    pedido = session.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PedidoCompra id={pedido_id} no encontrado.",
        )

    varianza = pedidos_service.calcular_varianza_tc(session, pedido)
    if abs(varianza) <= VARIANZA_TC_THRESHOLD_ARS:
        raise ValueError(
            f"PedidoCompra id={pedido_id}: varianza_tc_neta={varianza:.2f} ARS "
            f"está dentro del umbral de {VARIANZA_TC_THRESHOLD_ARS} ARS, no hay nada que resolver."
        )

    tipo_nc: Literal["credito", "debito"] = "debito" if varianza > 0 else "credito"
    monto_abs = abs(varianza)
    motivo = f"Varianza TC pedido {pedido.numero}: TC_orig={pedido.tipo_cambio_original} vs TC_ef; ARS {varianza:+.2f}"

    nd_nc = crear(
        session,
        empresa_id=pedido.empresa_id,
        proveedor_id=pedido.proveedor_id,
        moneda="ARS",
        monto=monto_abs,
        fecha_emision=date.today(),
        motivo=motivo,
        creado_por_id=user_id,
        tipo=tipo_nc,
    )
    # Auto-approve: borrador → pendiente_aprobacion → aprobado.
    transicionar(session, nc_id=nd_nc.id, accion="enviar_aprobacion", user_id=user_id)
    transicionar(session, nc_id=nd_nc.id, accion="aprobar", user_id=user_id)

    imp = imputaciones_service.crear_imputacion(
        session,
        origen_tipo="nota_credito_local",
        origen_id=nd_nc.id,
        destino_tipo="pedido_compra",
        destino_id=pedido_id,
        monto_imputado=monto_abs,
        moneda_imputada="ARS",
        proveedor_id=pedido.proveedor_id,
        creado_por_id=user_id,
    )
    cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp.id)

    logger.info(
        "resolver_varianza_tc pedido_id=%s varianza=%s tipo=%s nc_id=%s",
        pedido_id,
        varianza,
        tipo_nc,
        nd_nc.id,
    )
    return nd_nc.id


__all__ = [
    "CAMPOS_EDITABLES_BORRADOR",
    "ESTADOS_TERMINALES",
    "EstadoNCLocal",
    "TRANSICIONES_VALIDAS",
    "TiposEventoNC",
    "aplicar_imputacion_a_nc",
    "calcular_saldo_pendiente",
    "crear",
    "desvincular_factura_erp",
    "editar",
    "puede_eliminar_nc_local",
    "recalcular_estado_por_imputaciones",
    "resolver_varianza_tc",
    "transicionar",
    "vincular_factura_erp",
]
