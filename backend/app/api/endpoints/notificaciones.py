from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.models.notificacion import Notificacion, SeveridadNotificacion, EstadoNotificacion
from app.services.notificacion_service import NotificacionService

router = APIRouter()


class NotificacionResponse(BaseModel):
    id: int
    tipo: str
    item_id: Optional[int]
    id_operacion: Optional[int]
    ml_id: Optional[str]
    pack_id: Optional[int]
    codigo_producto: Optional[str]
    descripcion_producto: Optional[str]
    mensaje: str
    markup_real: Optional[float]
    markup_objetivo: Optional[float]
    monto_venta: Optional[float]
    fecha_venta: Optional[datetime]
    pm: Optional[str]
    costo_operacion: Optional[float]
    costo_actual: Optional[float]
    precio_venta_unitario: Optional[float]
    precio_publicacion: Optional[float]
    tipo_publicacion: Optional[str]
    comision_ml: Optional[float]
    iva_porcentaje: Optional[float]
    cantidad: Optional[int]
    costo_envio: Optional[float]
    leida: bool
    fecha_creacion: datetime
    fecha_lectura: Optional[datetime]

    # Nuevos campos
    severidad: Optional[SeveridadNotificacion] = None
    estado: Optional[EstadoNotificacion] = None
    fecha_revision: Optional[datetime] = None
    fecha_descarte: Optional[datetime] = None
    fecha_resolucion: Optional[datetime] = None
    notas_revision: Optional[str] = None
    diferencia_markup: Optional[float] = None
    diferencia_markup_porcentual: Optional[float] = None
    es_critica: Optional[bool] = None
    requiere_atencion: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class NotificacionStats(BaseModel):
    total: int
    no_leidas: int
    por_tipo: dict


class NotificacionAgrupada(BaseModel):
    # Clave de agrupación
    item_id: Optional[int]
    tipo: str
    markup_real: Optional[float]

    # Información del producto
    codigo_producto: Optional[str]
    descripcion_producto: Optional[str]
    pm: Optional[str]

    # Agregaciones
    count: int
    primera_fecha: datetime
    ultima_fecha: datetime

    # Representante (notificación más reciente del grupo)
    notificacion_reciente: NotificacionResponse

    # IDs de todas las notificaciones del grupo
    notificaciones_ids: List[int]

    model_config = ConfigDict(from_attributes=True)


@router.get("/notificaciones", response_model=List[NotificacionResponse])
async def listar_notificaciones(
    limit: int = 50,
    offset: int = 0,
    solo_no_leidas: bool = False,
    tipo: Optional[str] = None,
    severidad: Optional[SeveridadNotificacion] = None,
    estado: Optional[EstadoNotificacion] = None,
    solo_criticas: bool = False,
    solo_pendientes: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista las notificaciones del usuario actual ordenadas por fecha de creación (más recientes primero)

    Filtros disponibles:
    - solo_no_leidas: Solo notificaciones no leídas
    - tipo: Filtrar por tipo específico
    - severidad: Filtrar por severidad (info, warning, critical, urgent)
    - estado: Filtrar por estado (pendiente, revisada, descartada, en_gestion, resuelta)
    - solo_criticas: Solo notificaciones críticas o urgentes
    - solo_pendientes: Solo notificaciones pendientes o en gestión
    """
    query = db.query(Notificacion).filter(Notificacion.user_id == current_user.id)

    if solo_no_leidas:
        query = query.filter(Notificacion.leida == False)

    if tipo:
        query = query.filter(Notificacion.tipo == tipo)

    if severidad:
        query = query.filter(Notificacion.severidad == severidad)

    if estado:
        query = query.filter(Notificacion.estado == estado)

    if solo_criticas:
        query = query.filter(Notificacion.severidad.in_([SeveridadNotificacion.CRITICAL, SeveridadNotificacion.URGENT]))

    if solo_pendientes:
        query = query.filter(Notificacion.estado.in_([EstadoNotificacion.PENDIENTE, EstadoNotificacion.EN_GESTION]))

    notificaciones = (
        query.order_by(
            # Ordenar primero por severidad (urgent > critical > warning > info)
            desc(Notificacion.severidad),
            # Luego por fecha de creación
            desc(Notificacion.fecha_creacion),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return notificaciones


@router.get("/notificaciones/agrupadas", response_model=List[NotificacionAgrupada])
async def listar_notificaciones_agrupadas(
    solo_no_leidas: bool = False,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista las notificaciones agrupadas por (item_id, tipo, markup_real)
    Cada grupo muestra la cantidad de notificaciones, rango de fechas, y la notificación más reciente
    """
    from app.models.producto import ProductoERP

    query = db.query(Notificacion).filter(Notificacion.user_id == current_user.id)

    if solo_no_leidas:
        query = query.filter(Notificacion.leida == False)

    if tipo:
        query = query.filter(Notificacion.tipo == tipo)

    # Obtener todas las notificaciones que cumplen el filtro
    notificaciones = query.order_by(desc(Notificacion.fecha_creacion)).all()

    # Agrupar en memoria por (item_id, tipo, markup_real_redondeado)
    grupos = {}
    for notif in notificaciones:
        # Redondear markup_real a 2 decimales para agrupar
        markup_key = round(float(notif.markup_real), 2) if notif.markup_real is not None else None
        key = (notif.item_id, notif.tipo, markup_key)

        if key not in grupos:
            grupos[key] = []
        grupos[key].append(notif)

    # Construir respuesta agrupada
    resultado = []
    for (item_id, tipo_notif, markup_real), notifs_grupo in grupos.items():
        # Ordenar por fecha para obtener primera y última
        notifs_ordenados = sorted(notifs_grupo, key=lambda n: n.fecha_creacion)
        notif_reciente = notifs_ordenados[-1]  # La más reciente

        # Si código o descripción están vacíos, buscar en productos_erp
        codigo_prod = notif_reciente.codigo_producto
        descripcion_prod = notif_reciente.descripcion_producto

        if (not codigo_prod or not descripcion_prod) and item_id:
            producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
            if producto_erp:
                if not codigo_prod:
                    codigo_prod = producto_erp.codigo
                if not descripcion_prod:
                    descripcion_prod = producto_erp.descripcion

        resultado.append(
            {
                "item_id": item_id,
                "tipo": tipo_notif,
                "markup_real": markup_real,
                "codigo_producto": codigo_prod,
                "descripcion_producto": descripcion_prod,
                "pm": notif_reciente.pm,
                "count": len(notifs_grupo),
                "primera_fecha": notifs_ordenados[0].fecha_creacion,
                "ultima_fecha": notifs_ordenados[-1].fecha_creacion,
                "notificacion_reciente": notif_reciente,
                "notificaciones_ids": [n.id for n in notifs_grupo],
            }
        )

    # Ordenar grupos por última fecha (más reciente primero)
    resultado.sort(key=lambda g: g["ultima_fecha"], reverse=True)

    return resultado


@router.get("/notificaciones/stats", response_model=NotificacionStats)
async def obtener_estadisticas_notificaciones(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene estadísticas de las notificaciones del usuario actual
    """
    total = db.query(Notificacion).filter(Notificacion.user_id == current_user.id).count()
    no_leidas = (
        db.query(Notificacion).filter(Notificacion.user_id == current_user.id, Notificacion.leida == False).count()
    )

    # Contar por tipo
    tipos_query = (
        db.query(Notificacion.tipo, func.count(Notificacion.id).label("count"))
        .filter(Notificacion.user_id == current_user.id, Notificacion.leida == False)
        .group_by(Notificacion.tipo)
        .all()
    )

    por_tipo = {tipo: count for tipo, count in tipos_query}

    return {"total": total, "no_leidas": no_leidas, "por_tipo": por_tipo}


@router.patch("/notificaciones/{notificacion_id}/marcar-leida")
async def marcar_notificacion_leida(
    notificacion_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Marca una notificación como leída (solo la del usuario actual)
    """
    notificacion = (
        db.query(Notificacion)
        .filter(Notificacion.id == notificacion_id, Notificacion.user_id == current_user.id)
        .first()
    )

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    if not notificacion.leida:
        notificacion.leida = True
        notificacion.fecha_lectura = datetime.now()
        db.commit()

    return {"mensaje": "Notificación marcada como leída"}


@router.patch("/notificaciones/{notificacion_id}/marcar-no-leida")
async def marcar_notificacion_no_leida(
    notificacion_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Marca una notificación como no leída
    """
    notificacion = (
        db.query(Notificacion)
        .filter(Notificacion.id == notificacion_id, Notificacion.user_id == current_user.id)
        .first()
    )

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    if notificacion.leida:
        notificacion.leida = False
        notificacion.fecha_lectura = None
        db.commit()

    return {"mensaje": "Notificación marcada como no leída"}


@router.post("/notificaciones/marcar-todas-leidas")
async def marcar_todas_leidas(
    tipo: Optional[str] = None, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Marca todas las notificaciones del usuario actual como leídas (opcionalmente filtradas por tipo)
    """
    query = db.query(Notificacion).filter(Notificacion.user_id == current_user.id, Notificacion.leida == False)

    if tipo:
        query = query.filter(Notificacion.tipo == tipo)

    count = query.update({"leida": True, "fecha_lectura": datetime.now()})

    db.commit()

    return {"mensaje": f"{count} notificaciones marcadas como leídas"}


@router.post("/notificaciones/marcar-todas-no-leidas")
async def marcar_todas_no_leidas(
    tipo: Optional[str] = None, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Marca todas las notificaciones del usuario actual como no leídas
    """
    query = db.query(Notificacion).filter(Notificacion.user_id == current_user.id, Notificacion.leida == True)

    if tipo:
        query = query.filter(Notificacion.tipo == tipo)

    count = query.update({"leida": False, "fecha_lectura": None})

    db.commit()

    return {"mensaje": f"{count} notificaciones marcadas como no leídas"}


@router.delete("/notificaciones/{notificacion_id}")
async def eliminar_notificacion(
    notificacion_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina una notificación del usuario actual
    """
    notificacion = (
        db.query(Notificacion)
        .filter(Notificacion.id == notificacion_id, Notificacion.user_id == current_user.id)
        .first()
    )

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    db.delete(notificacion)
    db.commit()

    return {"mensaje": "Notificación eliminada"}


@router.delete("/notificaciones/limpiar")
async def limpiar_notificaciones_leidas(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina todas las notificaciones leídas del usuario actual
    """
    count = db.query(Notificacion).filter(Notificacion.user_id == current_user.id, Notificacion.leida == True).delete()
    db.commit()

    return {"mensaje": f"{count} notificaciones leídas eliminadas"}


# ========== NUEVOS ENDPOINTS DE GESTIÓN ==========


class CambiarEstadoRequest(BaseModel):
    estado: EstadoNotificacion
    notas: Optional[str] = None


@router.patch("/notificaciones/{notificacion_id}/estado")
async def cambiar_estado_notificacion(
    notificacion_id: int,
    request: CambiarEstadoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Cambia el estado de una notificación (revisada, descartada, en_gestion, resuelta)
    """
    notificacion = (
        db.query(Notificacion)
        .filter(Notificacion.id == notificacion_id, Notificacion.user_id == current_user.id)
        .first()
    )

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    notificacion.estado = request.estado

    # Actualizar notas si se proveyeron
    if request.notas:
        notificacion.notas_revision = request.notas

    # Actualizar fechas según el estado
    ahora = datetime.now()
    if request.estado == EstadoNotificacion.REVISADA and not notificacion.fecha_revision:
        notificacion.fecha_revision = ahora
    elif request.estado == EstadoNotificacion.DESCARTADA:
        notificacion.fecha_descarte = ahora
    elif request.estado == EstadoNotificacion.RESUELTA:
        notificacion.fecha_resolucion = ahora

    db.commit()
    db.refresh(notificacion)

    return {"mensaje": f"Notificación marcada como {request.estado.value}", "notificacion": notificacion}


@router.patch("/notificaciones/{notificacion_id}/revisar")
async def revisar_notificacion(
    notificacion_id: int,
    notas: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Marca una notificación como revisada (atajo para cambiar a estado REVISADA)
    """
    request = CambiarEstadoRequest(estado=EstadoNotificacion.REVISADA, notas=notas)
    return await cambiar_estado_notificacion(notificacion_id, request, db, current_user)


@router.patch("/notificaciones/{notificacion_id}/descartar")
async def descartar_notificacion(
    notificacion_id: int,
    notas: Optional[str] = None,
    crear_regla_ignorar: bool = True,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Descarta una notificación y opcionalmente crea regla para ignorar futuras similares.

    Args:
        notificacion_id: ID de la notificación a descartar
        notas: Notas opcionales sobre el descarte
        crear_regla_ignorar: Si True, crea regla para ignorar futuras notificaciones
                            del mismo producto + tipo + markup (default: True)
    """
    # Obtener notificación antes de cambiar estado
    notificacion = (
        db.query(Notificacion)
        .filter(Notificacion.id == notificacion_id, Notificacion.user_id == current_user.id)
        .first()
    )

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    # Crear regla de ignorar si se solicitó y tenemos los datos necesarios
    if crear_regla_ignorar and notificacion.item_id and notificacion.markup_real is not None:
        servicio = NotificacionService(db)
        servicio.agregar_regla_ignorar(
            user_id=current_user.id,
            item_id=notificacion.item_id,
            tipo=notificacion.tipo,
            markup_real=notificacion.markup_real,
            codigo_producto=notificacion.codigo_producto,
            descripcion_producto=notificacion.descripcion_producto,
            notificacion_id=notificacion_id,
        )

    # Cambiar estado a descartada
    request = CambiarEstadoRequest(estado=EstadoNotificacion.DESCARTADA, notas=notas)
    return await cambiar_estado_notificacion(notificacion_id, request, db, current_user)


@router.patch("/notificaciones/{notificacion_id}/resolver")
async def resolver_notificacion(
    notificacion_id: int,
    notas: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Marca una notificación como resuelta
    """
    request = CambiarEstadoRequest(estado=EstadoNotificacion.RESUELTA, notas=notas)
    return await cambiar_estado_notificacion(notificacion_id, request, db, current_user)


@router.post("/notificaciones/bulk-descartar")
async def descartar_notificaciones_bulk(
    notificaciones_ids: List[int],
    notas: Optional[str] = None,
    crear_reglas_ignorar: bool = True,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Descarta múltiples notificaciones a la vez y opcionalmente crea reglas de ignorar.

    Args:
        notificaciones_ids: IDs de las notificaciones a descartar
        notas: Notas opcionales sobre el descarte
        crear_reglas_ignorar: Si True, crea reglas de ignorar para cada notificación (default: True)
    """
    # Si se solicitan reglas de ignorar, obtener las notificaciones primero
    if crear_reglas_ignorar:
        notificaciones = (
            db.query(Notificacion)
            .filter(Notificacion.id.in_(notificaciones_ids), Notificacion.user_id == current_user.id)
            .all()
        )

        servicio = NotificacionService(db)

        # Crear reglas de ignorar para cada una que tenga datos completos
        for notif in notificaciones:
            if notif.item_id and notif.markup_real is not None:
                servicio.agregar_regla_ignorar(
                    user_id=current_user.id,
                    item_id=notif.item_id,
                    tipo=notif.tipo,
                    markup_real=notif.markup_real,
                    codigo_producto=notif.codigo_producto,
                    descripcion_producto=notif.descripcion_producto,
                    notificacion_id=notif.id,
                )

    # Descartar las notificaciones
    ahora = datetime.now()

    count = (
        db.query(Notificacion)
        .filter(Notificacion.id.in_(notificaciones_ids), Notificacion.user_id == current_user.id)
        .update(
            {"estado": EstadoNotificacion.DESCARTADA, "fecha_descarte": ahora, "notas_revision": notas},
            synchronize_session=False,
        )
    )

    db.commit()

    return {"mensaje": f"{count} notificaciones descartadas"}


@router.get("/notificaciones/dashboard")
async def dashboard_notificaciones(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Dashboard con métricas clave de notificaciones
    """
    # Total
    total = db.query(Notificacion).filter(Notificacion.user_id == current_user.id).count()

    # Por estado
    estados = (
        db.query(Notificacion.estado, func.count(Notificacion.id).label("count"))
        .filter(Notificacion.user_id == current_user.id)
        .group_by(Notificacion.estado)
        .all()
    )

    por_estado = {estado.value: count for estado, count in estados}

    # Por severidad
    severidades = (
        db.query(Notificacion.severidad, func.count(Notificacion.id).label("count"))
        .filter(
            Notificacion.user_id == current_user.id,
            Notificacion.estado.in_([EstadoNotificacion.PENDIENTE, EstadoNotificacion.EN_GESTION]),
        )
        .group_by(Notificacion.severidad)
        .all()
    )

    por_severidad = {sev.value: count for sev, count in severidades}

    # Críticas pendientes
    criticas_pendientes = (
        db.query(Notificacion)
        .filter(
            Notificacion.user_id == current_user.id,
            Notificacion.severidad.in_([SeveridadNotificacion.CRITICAL, SeveridadNotificacion.URGENT]),
            Notificacion.estado.in_([EstadoNotificacion.PENDIENTE, EstadoNotificacion.EN_GESTION]),
        )
        .count()
    )

    # No leídas
    no_leidas = (
        db.query(Notificacion).filter(Notificacion.user_id == current_user.id, Notificacion.leida == False).count()
    )

    return {
        "total": total,
        "por_estado": por_estado,
        "por_severidad": por_severidad,
        "criticas_pendientes": criticas_pendientes,
        "no_leidas": no_leidas,
        "requieren_atencion": por_estado.get("pendiente", 0) + por_estado.get("en_gestion", 0),
    }


# ========== ENDPOINTS DE GESTIÓN DE REGLAS IGNORADAS ==========

from app.models.notificacion_ignorada import NotificacionIgnorada


class ReglaIgnoradaResponse(BaseModel):
    id: int
    user_id: int
    item_id: int
    tipo: str
    markup_real: float
    codigo_producto: Optional[str]
    descripcion_producto: Optional[str]
    fecha_creacion: datetime
    ignorado_por_notificacion_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)


@router.get("/notificaciones/ignoradas", response_model=List[ReglaIgnoradaResponse])
async def listar_reglas_ignoradas(
    limit: int = 100,
    offset: int = 0,
    tipo: Optional[str] = None,
    codigo_producto: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista todas las reglas de ignorar del usuario actual.

    Permite filtrar por:
    - tipo: Tipo de notificación
    - codigo_producto: Búsqueda parcial en código de producto
    """
    query = db.query(NotificacionIgnorada).filter(NotificacionIgnorada.user_id == current_user.id)

    if tipo:
        query = query.filter(NotificacionIgnorada.tipo == tipo)

    if codigo_producto:
        query = query.filter(NotificacionIgnorada.codigo_producto.ilike(f"%{codigo_producto}%"))

    reglas = query.order_by(desc(NotificacionIgnorada.fecha_creacion)).offset(offset).limit(limit).all()

    return reglas


@router.delete("/notificaciones/ignoradas/{regla_id}")
async def eliminar_regla_ignorada(
    regla_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina una regla de ignorar (re-habilita notificaciones para ese producto/tipo/markup).
    """
    regla = (
        db.query(NotificacionIgnorada)
        .filter(NotificacionIgnorada.id == regla_id, NotificacionIgnorada.user_id == current_user.id)
        .first()
    )

    if not regla:
        raise HTTPException(404, "Regla no encontrada")

    db.delete(regla)
    db.commit()

    return {
        "mensaje": "Regla eliminada. Ahora recibirás notificaciones para este caso.",
        "regla": {
            "item_id": regla.item_id,
            "tipo": regla.tipo,
            "markup_real": regla.markup_real,
            "codigo_producto": regla.codigo_producto,
        },
    }


@router.delete("/notificaciones/ignoradas/bulk")
async def eliminar_reglas_ignoradas_bulk(
    reglas_ids: List[int], db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina múltiples reglas de ignorar a la vez.
    """
    count = (
        db.query(NotificacionIgnorada)
        .filter(NotificacionIgnorada.id.in_(reglas_ids), NotificacionIgnorada.user_id == current_user.id)
        .delete(synchronize_session=False)
    )

    db.commit()

    return {"mensaje": f"{count} reglas eliminadas"}


@router.get("/notificaciones/ignoradas/stats")
async def stats_reglas_ignoradas(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Estadísticas sobre las reglas de ignorar del usuario.
    """
    # Total de reglas
    total = db.query(NotificacionIgnorada).filter(NotificacionIgnorada.user_id == current_user.id).count()

    # Por tipo
    tipos_query = (
        db.query(NotificacionIgnorada.tipo, func.count(NotificacionIgnorada.id).label("count"))
        .filter(NotificacionIgnorada.user_id == current_user.id)
        .group_by(NotificacionIgnorada.tipo)
        .all()
    )

    por_tipo = {tipo: count for tipo, count in tipos_query}

    # Productos más ignorados
    productos_query = (
        db.query(
            NotificacionIgnorada.item_id,
            NotificacionIgnorada.codigo_producto,
            NotificacionIgnorada.descripcion_producto,
            func.count(NotificacionIgnorada.id).label("count"),
        )
        .filter(NotificacionIgnorada.user_id == current_user.id)
        .group_by(
            NotificacionIgnorada.item_id,
            NotificacionIgnorada.codigo_producto,
            NotificacionIgnorada.descripcion_producto,
        )
        .order_by(desc("count"))
        .limit(10)
        .all()
    )

    productos_top = [
        {"item_id": item_id, "codigo_producto": codigo, "descripcion_producto": descripcion, "reglas_count": count}
        for item_id, codigo, descripcion, count in productos_query
    ]

    return {"total": total, "por_tipo": por_tipo, "productos_mas_ignorados": productos_top}
