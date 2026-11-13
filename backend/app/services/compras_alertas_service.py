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
from sqlalchemy.orm import Session, joinedload

from app.core.logging import get_logger
from app.models.notificacion import EstadoNotificacion, Notificacion, SeveridadNotificacion
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.usuario import Usuario
from app.services.notificacion_service import (
    crear_notificaciones_para_permisos,
    resolver_usuarios_con_algun_permiso,
)

logger = get_logger(__name__)

TIPO_FACTURA_CARGADA: Final[str] = "compras.factura_cargada"
TIPO_FALTANTES: Final[str] = "compras.faltantes"
TIPO_FALTANTES_RESUELTO: Final[str] = "compras.faltantes_resuelto"

SNOOZE_MARKER: Final[str] = "compras.faltantes.snooze"
SNOOZE_WINDOW: Final[timedelta] = timedelta(hours=1)
# Windows that became due longer ago than this are drained silently (mark
# disparada, no Notificacion / auto-vínculo). Prevents a first worker run (or a
# long outage) from fan-out-notifying the whole historical cargada backlog.
MAX_FACTURA_ALERT_LAG: Final[timedelta] = timedelta(hours=1)
PERMISO_VER_ALERTAS_FACTURA: Final[str] = "administracion.ver_alertas_factura"
PERMISO_DEPOSITO_RECEPCION: Final[str] = "deposito.recibir_mercaderia"
# Belt-and-suspenders: Gabriel DeMarco always receives factura_cargada (brief).
# ponytail: Gabe user id hardcoded for factura_cargada belt-and-suspenders — move to config/env when multi-env needs it
FACTURA_ALERTA_ALWAYS_USER_IDS: Final[frozenset[int]] = frozenset({3})
DEEP_LINK_OBSERVACIONES: Final[str] = "/administracion/compras?tab=pedidos&pedido={pedido_id}&focus=observaciones"
DEEP_LINK_DEPOSITO: Final[str] = "/administracion/compras?tab=deposito&pedido={pedido_id}&eje=faltantes_con_res"


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
    return (
        f"Factura {factura_numero} marcada cargada en ERP en {pedido_numero} "
        f"({proveedor_nombre}). Revisá el pedido en Compras."
    )


def copy_faltantes(*, pedido_numero: str, proveedor_nombre: str, texto: str, pedido_id: int) -> str:
    link = DEEP_LINK_OBSERVACIONES.format(pedido_id=pedido_id)
    return f"Faltantes en {pedido_numero} ({proveedor_nombre}): {texto} — {link}"


def copy_faltantes_resuelto(*, pedido_numero: str, proveedor_nombre: str, texto: str, pedido_id: int) -> str:
    texto_norm = (texto or "").strip()
    link = DEEP_LINK_DEPOSITO.format(pedido_id=pedido_id)
    return f"Faltantes resueltos en {pedido_numero} ({proveedor_nombre}): {texto_norm} — {link}"


def destinatarios_factura(session: Session) -> list[Usuario]:
    """Active holders of administracion.ver_alertas_factura, plus always-notify ids.

    Permission fan-out stays the primary path. ``FACTURA_ALERTA_ALWAYS_USER_IDS``
    (Gabe / user id 3) is unioned in when that user is active, even if the
    hybrid resolver somehow omits them.
    """
    holders = resolver_usuarios_con_algun_permiso(
        session,
        permisos_requeridos=[PERMISO_VER_ALERTAS_FACTURA],
    )
    by_id: dict[int, Usuario] = {int(u.id): u for u in holders}
    missing = [uid for uid in FACTURA_ALERTA_ALWAYS_USER_IDS if uid not in by_id]
    if missing:
        extras = session.query(Usuario).filter(Usuario.id.in_(missing), Usuario.activo.is_(True)).all()
        for user in extras:
            by_id[int(user.id)] = user
    return list(by_id.values())


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


def _docs_auto_vinculo_pendientes(session: Session, *, limit: int = 50) -> list[PedidoFacturaDocumento]:
    """Cargada docs whose auto-link already failed (retry after mirror sync)."""
    from app.services.erp_matching_service import AUTO_VINCULO_PENDIENTES  # noqa: PLC0415

    return (
        session.query(PedidoFacturaDocumento)
        .options(joinedload(PedidoFacturaDocumento.pedido).joinedload(PedidoCompra.proveedor))
        .filter(
            PedidoFacturaDocumento.cargada.is_(True),
            PedidoFacturaDocumento.alerta_disparada_at.isnot(None),
            PedidoFacturaDocumento.auto_vinculo_estado.in_(sorted(AUTO_VINCULO_PENDIENTES)),
        )
        .order_by(PedidoFacturaDocumento.auto_vinculo_intentado_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )


def _sync_espejo_antes_autolink(session: Session) -> None:
    """Best-effort short CT mirror pull. Releases the txn before HTTP."""
    from app.services import ct_mirror_sync_service  # noqa: PLC0415

    # Pool-safety: do not hold an open transaction across GBP (idle_in_transaction).
    session.commit()
    try:
        ct_mirror_sync_service.sync_recent_cts(session)
    except Exception:  # noqa: BLE001 — mirror lag must not block alerts / retries
        logger.exception("ct_mirror_sync before auto-vínculo failed; matching with current mirror")
        session.rollback()


def disparar_alertas_factura_pendientes(session: Session, *, ahora: datetime | None = None) -> int:
    """Fire pending ERP-check alerts whose window has been reached. Idempotent.

    Selects `cargada AND alerta_pendiente_hasta <= ahora AND alerta_disparada_at IS NULL`.
    Persist / Match / manual alta never call this. Uncheck before fire cancels
    by nulling `alerta_pendiente_hasta`.

    Stale due rows (`alerta_pendiente_hasta` older than `MAX_FACTURA_ALERT_LAG`)
    skip the Notificacion fan-out but still auto-link and mark disparada —
    historical backlog must not spam the bell when the worker first comes up,
    yet a late sweep must not permanently skip the ERP vínculo.

    Before matching, pulls a short CT mirror window (and retries prior
    sin_match/ambiguo/sin_mapeo rows) so GBP lag after cargada does not
    permanently strand the vínculo.
    """
    stamp = _ahora_utc(ahora)
    lag_floor = stamp - MAX_FACTURA_ALERT_LAG
    rows = (
        session.query(PedidoFacturaDocumento)
        .options(joinedload(PedidoFacturaDocumento.pedido).joinedload(PedidoCompra.proveedor))
        .filter(
            PedidoFacturaDocumento.cargada.is_(True),
            PedidoFacturaDocumento.alerta_pendiente_hasta.isnot(None),
            PedidoFacturaDocumento.alerta_pendiente_hasta <= stamp,
            PedidoFacturaDocumento.alerta_disparada_at.is_(None),
        )
        .all()
    )
    retries = _docs_auto_vinculo_pendientes(session)
    if rows or retries:
        _sync_espejo_antes_autolink(session)
        # Identity map expired after commit — reload work sets.
        rows = (
            session.query(PedidoFacturaDocumento)
            .options(joinedload(PedidoFacturaDocumento.pedido).joinedload(PedidoCompra.proveedor))
            .filter(
                PedidoFacturaDocumento.cargada.is_(True),
                PedidoFacturaDocumento.alerta_pendiente_hasta.isnot(None),
                PedidoFacturaDocumento.alerta_pendiente_hasta <= stamp,
                PedidoFacturaDocumento.alerta_disparada_at.is_(None),
            )
            .all()
        )
        retries = _docs_auto_vinculo_pendientes(session)

    from app.services import erp_matching_service  # noqa: PLC0415

    fired = 0
    drained = 0
    for row in rows:
        pedido = row.pedido
        if pedido is None:
            continue
        pending_until = _as_aware_utc(row.alerta_pendiente_hasta)
        is_stale = pending_until < lag_floor
        if is_stale:
            # Historical / long-outage backlog: no bell spam.
            drained += 1
        else:
            notificar_factura_cargada(session, pedido=pedido, factura=row, ahora=stamp)
            fired += 1
        # After the regret window: documental auto-link by constancia numero (M:N),
        # including drained rows (otherwise the vínculo is lost forever).
        # Failures must not abort the outer transaction (alert still marks fired).
        try:
            with session.begin_nested():
                erp_matching_service.auto_vincular_por_constancia_cargada(session, row, ahora=stamp)
        except Exception:  # noqa: BLE001
            logger.exception(
                "auto_vincular_constancia falló para documento_id=%s pedido_id=%s",
                row.id,
                pedido.id,
            )
        row.alerta_disparada_at = stamp

    for row in retries:
        if row.pedido is None:
            continue
        try:
            with session.begin_nested():
                erp_matching_service.auto_vincular_por_constancia_cargada(session, row, ahora=stamp)
        except Exception:  # noqa: BLE001
            logger.exception(
                "auto_vincular_constancia retry falló documento_id=%s pedido_id=%s",
                row.id,
                row.pedido_id,
            )

    if rows or retries:
        session.flush()
    if drained:
        logger.warning(
            "disparar_alertas_factura_pendientes: drained %s stale cargada alert(s) without notify (lag > %s)",
            drained,
            MAX_FACTURA_ALERT_LAG,
        )
    return fired


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


def pedido_admite_alerta_faltantes(pedido: PedidoCompra | None) -> bool:
    """True while the pedido still needs a faltantes resolve (banner must stick)."""
    if pedido is None:
        return False
    if pedido.faltantes_resuelto_en is not None:
        return False
    return pedido.estado == "con_faltantes"


def retractar_faltantes(
    session: Session,
    *,
    pedido_id: int,
    ahora: datetime | None = None,
) -> int:
    """Mark open compras.faltantes for this pedido DESCARTADA (resolve / leave faltantes)."""
    stamp = _ahora_utc(ahora)
    notifs = (
        session.query(Notificacion)
        .filter(
            Notificacion.tipo == TIPO_FALTANTES,
            Notificacion.item_id == int(pedido_id),
            Notificacion.estado != EstadoNotificacion.DESCARTADA,
        )
        .all()
    )
    for notif in notifs:
        notif.estado = EstadoNotificacion.DESCARTADA
        notif.fecha_descarte = stamp
        notif.leida = True
    return len(notifs)


def faltantes_obsoletas_ids(session: Session, notifs: list[Notificacion]) -> set[int]:
    """Ids of open compras.faltantes in ``notifs`` whose pedido no longer admits resolve.

    Read-only: safe on GET hot paths (listings hide these without writing).
    """
    faltantes = [n for n in notifs if n.tipo == TIPO_FALTANTES and n.estado != EstadoNotificacion.DESCARTADA]
    if not faltantes:
        return set()
    ids = {int(n.item_id) for n in faltantes if n.item_id is not None}
    pedidos_by_id: dict[int, PedidoCompra] = {}
    if ids:
        pedidos_by_id = {int(p.id): p for p in session.query(PedidoCompra).filter(PedidoCompra.id.in_(ids)).all()}
    obsoletas: set[int] = set()
    for notif in faltantes:
        pedido = pedidos_by_id.get(int(notif.item_id)) if notif.item_id is not None else None
        if not pedido_admite_alerta_faltantes(pedido):
            obsoletas.add(int(notif.id))
    return obsoletas


def retractar_faltantes_obsoletas(
    session: Session,
    *,
    ahora: datetime | None = None,
    pedido_ids: set[int] | None = None,
) -> int:
    """Discard open compras.faltantes whose pedido no longer admits resolve.

    Covers controlado / already-resolved / missing pedido so snoozed banners
    do not revive after the logistics deadlock (resolver requires con_faltantes).

    When ``pedido_ids`` is provided, only those pedidos are inspected (list
    self-heal). Omit it for a full sweep (tests / one-shot repair).
    """
    stamp = _ahora_utc(ahora)
    query = session.query(Notificacion).filter(
        Notificacion.tipo == TIPO_FALTANTES,
        Notificacion.estado != EstadoNotificacion.DESCARTADA,
    )
    if pedido_ids is not None:
        if not pedido_ids:
            return 0
        query = query.filter(Notificacion.item_id.in_(pedido_ids))
    notifs = query.all()
    obsoletas = faltantes_obsoletas_ids(session, notifs)
    closed = 0
    for notif in notifs:
        if notif.id not in obsoletas:
            continue
        notif.estado = EstadoNotificacion.DESCARTADA
        notif.fecha_descarte = stamp
        notif.leida = True
        closed += 1
    return closed


def notificar_faltantes_resuelto(
    session: Session,
    *,
    pedido: PedidoCompra,
    texto: str,
) -> list[Notificacion]:
    """G31: every user with deposito.recibir_mercaderia. Copy includes PM texto + Depósito link."""
    mensaje = copy_faltantes_resuelto(
        pedido_numero=pedido.numero,
        proveedor_nombre=_proveedor_nombre(pedido),
        texto=texto,
        pedido_id=int(pedido.id),
    )
    return crear_notificaciones_para_permisos(
        session,
        permisos_requeridos=[PERMISO_DEPOSITO_RECEPCION],
        tipo=TIPO_FALTANTES_RESUELTO,
        mensaje=mensaje,
        severidad=SeveridadNotificacion.INFO,
        item_id=int(pedido.id),
        codigo_producto=DEEP_LINK_DEPOSITO.format(pedido_id=int(pedido.id)),
    )


def rechazar_cierre_faltantes(session: Session, notificacion: Notificacion) -> None:
    """Block OK/dismiss of compras.faltantes only while the pedido still admits resolve.

    If the pedido left con_faltantes (controlado / already resolved / missing),
    allow dismiss so the banner is not stuck behind snooze.
    """
    if notificacion.tipo != TIPO_FALTANTES:
        return
    pedido = None
    if notificacion.item_id is not None:
        pedido = session.get(PedidoCompra, int(notificacion.item_id))
    if pedido_admite_alerta_faltantes(pedido):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La alerta de faltantes solo se cierra al resolver.",
        )


def marcar_ok(session: Session, notificacion: Notificacion, *, ahora: datetime | None = None) -> Notificacion:
    """Per-user OK → DESCARTADA. Active compras.faltantes → 409; stale → allow."""
    rechazar_cierre_faltantes(session, notificacion)
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
