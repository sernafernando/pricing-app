"""In-app factura / faltantes alerts for the Compras pipeline (PR2).

D-PERM: factura recipients via resolver(administracion.ver_alertas_factura).
D-BANNER: one Notificacion per recipient; AppLayout caps unread compras.*.
D-SNOOZE: REVISADA + snooze marker; hide while now < fecha_creacion + 1h (mark time).
Channel is in-app only — this module never sends email or Slack.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.notificacion import EstadoNotificacion, Notificacion, SeveridadNotificacion
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.usuario import Usuario
from app.services.notificacion_service import (
    crear_notificaciones_para_permisos,
    resolver_usuarios_con_algun_permiso,
)

TIPO_FACTURA_CARGADA: Final[str] = "compras.factura_cargada"
TIPO_FALTANTES: Final[str] = "compras.faltantes"
TIPO_FALTANTES_RESUELTO: Final[str] = "compras.faltantes_resuelto"

SNOOZE_MARKER: Final[str] = "compras.faltantes.snooze"
SNOOZE_WINDOW: Final[timedelta] = timedelta(hours=1)
PERMISO_VER_ALERTAS_FACTURA: Final[str] = "administracion.ver_alertas_factura"
PERMISO_DEPOSITO_RECEPCION: Final[str] = "deposito.recibir_mercaderia"
DEEP_LINK_OBSERVACIONES: Final[str] = "/administracion/compras?tab=pedidos&pedido={pedido_id}&focus=observaciones"


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is not None:
        return ahora if ahora.tzinfo else ahora.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _proveedor_nombre(pedido: PedidoCompra) -> str:
    proveedor = getattr(pedido, "proveedor", None)
    nombre = getattr(proveedor, "nombre", None)
    return (nombre or "").strip() or "proveedor"


def copy_factura_cargada(*, pedido_numero: str, proveedor_nombre: str, factura_numero: str) -> str:
    """Pricing P-number + proveedor + factura nº. Never pedidos_documento."""
    return f"Factura {factura_numero} cargada en {pedido_numero} ({proveedor_nombre}). Revisá el pedido en Compras."


def copy_faltantes(*, pedido_numero: str, proveedor_nombre: str, texto: str, pedido_id: int) -> str:
    link = DEEP_LINK_OBSERVACIONES.format(pedido_id=pedido_id)
    return f"Faltantes en {pedido_numero} ({proveedor_nombre}): {texto} — {link}"


def copy_faltantes_resuelto(*, pedido_numero: str, proveedor_nombre: str) -> str:
    return f"Faltantes resueltos en {pedido_numero} ({proveedor_nombre})."


def destinatarios_factura(session: Session) -> list[Usuario]:
    """Active users who hold administracion.ver_alertas_factura (hybrid resolver)."""
    return resolver_usuarios_con_algun_permiso(
        session,
        permisos_requeridos=[PERMISO_VER_ALERTAS_FACTURA],
    )


def notificar_factura_cargada(
    session: Session,
    *,
    pedido: PedidoCompra,
    factura: PedidoFacturaDocumento,
    ahora: datetime | None = None,
) -> list[Notificacion]:
    """Fan-out one Notificacion per factura recipient. Empty nº is a no-op."""
    numero = (factura.numero or "").strip()
    if not numero:
        return []

    mensaje = copy_factura_cargada(
        pedido_numero=pedido.numero,
        proveedor_nombre=_proveedor_nombre(pedido),
        factura_numero=numero,
    )
    created_at = _ahora_utc(ahora)
    creadas: list[Notificacion] = []
    for user in destinatarios_factura(session):
        notif = Notificacion(
            user_id=user.id,
            tipo=TIPO_FACTURA_CARGADA,
            item_id=int(pedido.id),
            id_operacion=int(factura.id),
            mensaje=mensaje,
            severidad=SeveridadNotificacion.INFO,
            estado=EstadoNotificacion.PENDIENTE,
            leida=False,
            fecha_creacion=created_at,
        )
        session.add(notif)
        creadas.append(notif)
    if creadas:
        session.flush()
    return creadas


def retractar_factura_cargada(
    session: Session,
    *,
    pedido_id: int,
    factura_row_id: int,
    ahora: datetime | None = None,
) -> int:
    """Mark factura-cargada notifs for this row DESCARTADA (undo ≤5m)."""
    stamp = _ahora_utc(ahora)
    notifs = (
        session.query(Notificacion)
        .filter(
            Notificacion.tipo == TIPO_FACTURA_CARGADA,
            Notificacion.item_id == int(pedido_id),
            Notificacion.id_operacion == int(factura_row_id),
            Notificacion.estado != EstadoNotificacion.DESCARTADA,
        )
        .all()
    )
    for notif in notifs:
        notif.estado = EstadoNotificacion.DESCARTADA
        notif.fecha_descarte = stamp
        notif.leida = True
    return len(notifs)


def notificar_faltantes(
    session: Session,
    *,
    pedido: PedidoCompra,
    texto: str,
    ahora: datetime | None = None,
) -> list[Notificacion]:
    """Alert pedido.responsable_id. Empty texto → 422 and no row."""
    texto_norm = (texto or "").strip()
    if not texto_norm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="faltantes_texto no puede estar vacío.",
        )
    if pedido.responsable_id is None:
        return []

    created_at = _ahora_utc(ahora)
    mensaje = copy_faltantes(
        pedido_numero=pedido.numero,
        proveedor_nombre=_proveedor_nombre(pedido),
        texto=texto_norm,
        pedido_id=int(pedido.id),
    )
    notif = Notificacion(
        user_id=pedido.responsable_id,
        tipo=TIPO_FALTANTES,
        item_id=int(pedido.id),
        codigo_producto=DEEP_LINK_OBSERVACIONES.format(pedido_id=int(pedido.id)),
        mensaje=mensaje,
        severidad=SeveridadNotificacion.WARNING,
        estado=EstadoNotificacion.PENDIENTE,
        leida=False,
        fecha_creacion=created_at,
    )
    session.add(notif)
    session.flush()
    return [notif]


def notificar_faltantes_resuelto(
    session: Session,
    *,
    pedido: PedidoCompra,
) -> list[Notificacion]:
    """G31: every user with deposito.recibir_mercaderia."""
    mensaje = copy_faltantes_resuelto(
        pedido_numero=pedido.numero,
        proveedor_nombre=_proveedor_nombre(pedido),
    )
    return crear_notificaciones_para_permisos(
        session,
        permisos_requeridos=[PERMISO_DEPOSITO_RECEPCION],
        tipo=TIPO_FALTANTES_RESUELTO,
        mensaje=mensaje,
        severidad=SeveridadNotificacion.INFO,
        item_id=int(pedido.id),
    )


def marcar_ok(_session: Session, notificacion: Notificacion, *, ahora: datetime | None = None) -> Notificacion:
    """Per-user OK → DESCARTADA."""
    stamp = _ahora_utc(ahora)
    notificacion.estado = EstadoNotificacion.DESCARTADA
    notificacion.fecha_descarte = stamp
    notificacion.leida = True
    if notificacion.fecha_lectura is None:
        notificacion.fecha_lectura = stamp
    return notificacion


def snooze_faltantes(
    _session: Session,
    notificacion: Notificacion,
    *,
    ahora: datetime | None = None,
) -> Notificacion:
    """Snooze faltantes: REVISADA + marker. Hide until mark (fecha_creacion) + 1h."""
    if notificacion.tipo != TIPO_FALTANTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede posponer una alerta de faltantes.",
        )
    stamp = _ahora_utc(ahora)
    notificacion.estado = EstadoNotificacion.REVISADA
    notificacion.fecha_revision = stamp
    notas = notificacion.notas_revision or ""
    if SNOOZE_MARKER not in notas:
        notificacion.notas_revision = f"{notas}\n{SNOOZE_MARKER}".strip()
    return notificacion


def esta_oculta_por_snooze(notificacion: Notificacion, *, ahora: datetime | None = None) -> bool:
    """True while REVISADA + snooze marker and now < fecha_creacion + 1h."""
    if notificacion.tipo != TIPO_FALTANTES:
        return False
    if notificacion.estado != EstadoNotificacion.REVISADA:
        return False
    notas = notificacion.notas_revision or ""
    if SNOOZE_MARKER not in notas:
        return False
    created = _as_aware_utc(notificacion.fecha_creacion)
    return _ahora_utc(ahora) < created + SNOOZE_WINDOW


def filtrar_visibles(
    notificaciones: list[Notificacion],
    *,
    ahora: datetime | None = None,
) -> list[Notificacion]:
    stamp = _ahora_utc(ahora)
    return [n for n in notificaciones if not esta_oculta_por_snooze(n, ahora=stamp)]
