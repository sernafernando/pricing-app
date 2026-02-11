"""
Endpoints para el sistema de asignaciones.

Sistema genérico diseñado para escalar:
- Actualmente: asignaciones manuales de items sin MLA (por lista de precio)
- Futuro: asignaciones automáticas, otros tipos de asignación

Permisos:
- admin.asignar_items_sin_mla: Auto-asignarse items
- admin.gestionar_asignaciones: Asignar/desasignar a cualquier usuario

Tracking de productividad:
- estado_hash: fingerprint SHA-256 de las listas faltantes al momento de asignar
- Cuando el hash actual difiere del hash al asignar → el item fue resuelto
- Se mide fecha_asignacion → fecha_resolucion para métricas de performance
"""

import hashlib
import uuid
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, aliased
from sqlalchemy import and_
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.asignacion import Asignacion
from app.models.usuario import Usuario

router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================


class AsignarItemRequest(BaseModel):
    """Asignar listas específicas de un item a un usuario."""

    item_id: int
    listas: List[str]  # ['Clásica', '3 Cuotas', ...]
    usuario_id: Optional[int] = None  # None = auto-asignarse
    notas: Optional[str] = None
    # Snapshot de todas las listas faltantes (para metadata, no para hash)
    listas_sin_mla: Optional[List[str]] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "item_id": 12345,
                "listas": ["Clásica", "3 Cuotas"],
                "listas_sin_mla": ["Clásica", "3 Cuotas", "6 Cuotas"],
                "notas": "Producto nuevo, prioridad alta",
            }
        }
    )


class AsignarMasivoRequest(BaseModel):
    """Asignar múltiples items de una vez (multi-selección)."""

    items: List[dict]  # [{'item_id': 123, 'listas': ['Clásica'], 'listas_sin_mla': [...]}, ...]
    usuario_id: Optional[int] = None
    notas: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {"item_id": 123, "listas": ["Clásica"], "listas_sin_mla": ["Clásica", "3 Cuotas"]},
                    {"item_id": 456, "listas": ["6 Cuotas"], "listas_sin_mla": ["6 Cuotas"]},
                ],
                "notas": "Lote asignado masivamente",
            }
        }
    )


class DesasignarRequest(BaseModel):
    """Desasignar una o más asignaciones."""

    asignacion_ids: List[int]


class ReasignarRequest(BaseModel):
    """Reasignar asignaciones a otro usuario."""

    asignacion_ids: List[int]
    usuario_id: int  # Nuevo usuario destino


class AsignacionResponse(BaseModel):
    """Respuesta con datos de una asignación."""

    id: int
    tracking_id: str
    tipo: str
    referencia_id: int
    subtipo: Optional[str]
    usuario_id: int
    usuario_nombre: str
    asignado_por_id: int
    asignado_por_nombre: str
    estado: str
    estado_hash: Optional[str]
    origen: str
    fecha_asignacion: str
    fecha_resolucion: Optional[str]
    notas: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class VerificarHashResponse(BaseModel):
    """Resultado de verificación de hash de estado."""

    asignacion_id: int
    item_id: int
    subtipo: str
    hash_original: Optional[str]
    hash_actual: str
    cambio_detectado: bool
    resuelta: bool
    tiempo_resolucion_horas: Optional[float]

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Helpers
# =============================================================================


def _verificar_permiso_asignacion(db: Session, current_user: Usuario, usuario_destino_id: Optional[int] = None) -> None:
    """
    Verifica permisos de asignación:
    - Si usuario_destino_id es None o es el propio usuario: requiere admin.asignar_items_sin_mla
    - Si es otro usuario: requiere admin.gestionar_asignaciones
    """
    from app.services.permisos_service import verificar_permiso

    es_auto_asignacion = usuario_destino_id is None or usuario_destino_id == current_user.id

    if es_auto_asignacion:
        if not verificar_permiso(db, current_user, "admin.asignar_items_sin_mla"):
            raise HTTPException(status_code=403, detail="No tenés permiso para asignarte items sin MLA")
    else:
        if not verificar_permiso(db, current_user, "admin.gestionar_asignaciones"):
            raise HTTPException(
                status_code=403, detail="No tenés permiso para gestionar asignaciones de otros usuarios"
            )


def _generar_estado_hash(item_id: int, lista: str, existe_mla: bool = False) -> str:
    """
    Genera un SHA-256 del estado de UNA asignación específica (item + lista).

    El hash representa: "¿el item X tiene publicación en la lista Y?"
    - Al asignar: existe_mla=False → hash de "12345|Clásica|NO"
    - Al verificar: si ahora tiene MLA → hash de "12345|Clásica|SI" → DIFERENTE → resuelta

    Se hashea por asignación individual, no por todas las listas del item.
    Si asigné Clásica, que cambien 9 Cuotas no me importa.
    """
    estado = "SI" if existe_mla else "NO"
    canonical = f"{item_id}|{lista}|{estado}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_asignacion_response(
    asignacion: Asignacion, usuario_asignado: Usuario, usuario_creador: Usuario
) -> AsignacionResponse:
    """Construye la respuesta de asignación con datos de ambos usuarios."""
    return AsignacionResponse(
        id=asignacion.id,
        tracking_id=str(asignacion.tracking_id),
        tipo=asignacion.tipo,
        referencia_id=asignacion.referencia_id,
        subtipo=asignacion.subtipo,
        usuario_id=asignacion.usuario_id,
        usuario_nombre=usuario_asignado.nombre,
        asignado_por_id=asignacion.asignado_por_id,
        asignado_por_nombre=usuario_creador.nombre,
        estado=asignacion.estado,
        estado_hash=asignacion.estado_hash,
        origen=asignacion.origen,
        fecha_asignacion=asignacion.fecha_asignacion.isoformat(),
        fecha_resolucion=asignacion.fecha_resolucion.isoformat() if asignacion.fecha_resolucion else None,
        notas=asignacion.notas,
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/asignar", response_model=List[AsignacionResponse])
async def asignar_item(
    request: AsignarItemRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> List[AsignacionResponse]:
    """
    Asigna listas específicas de un item a un usuario.
    Cada lista genera una asignación independiente con su propio tracking_id.

    - Sin usuario_id: se auto-asigna al usuario actual
    - Con usuario_id: requiere permiso admin.gestionar_asignaciones
    - listas_sin_mla: snapshot de las listas faltantes para generar estado_hash
    """
    usuario_destino_id = request.usuario_id or current_user.id
    _verificar_permiso_asignacion(db, current_user, usuario_destino_id)

    # Verificar que el usuario destino existe
    usuario_destino = db.query(Usuario).filter(Usuario.id == usuario_destino_id).first()
    if not usuario_destino:
        raise HTTPException(status_code=404, detail="Usuario destino no encontrado")

    creadas = []
    duplicadas = []

    for lista in request.listas:
        # Verificar si ya existe una asignación PENDIENTE para este item+lista
        existente = (
            db.query(Asignacion)
            .filter(
                and_(
                    Asignacion.tipo == "item_sin_mla",
                    Asignacion.referencia_id == request.item_id,
                    Asignacion.subtipo == lista,
                    Asignacion.estado == "pendiente",
                )
            )
            .first()
        )

        if existente:
            duplicadas.append(lista)
            continue

        # Hash POR ASIGNACIÓN: item + lista específica + "no tiene MLA"
        estado_hash = _generar_estado_hash(request.item_id, lista, existe_mla=False)

        nueva = Asignacion(
            tracking_id=uuid.uuid4(),
            tipo="item_sin_mla",
            referencia_id=request.item_id,
            subtipo=lista,
            usuario_id=usuario_destino_id,
            asignado_por_id=current_user.id,
            estado="pendiente",
            estado_hash=estado_hash,
            origen="manual",
            notas=request.notas,
            metadata_asignacion={
                "listas_faltantes": request.listas_sin_mla or [],
                "listas_asignadas": request.listas,
            },
        )
        db.add(nueva)
        creadas.append(nueva)

    if not creadas and duplicadas:
        raise HTTPException(
            status_code=400, detail=f"Las listas ya están asignadas (pendientes): {', '.join(duplicadas)}"
        )

    db.commit()

    # Refresh y construir respuesta
    resultados = []
    for asignacion in creadas:
        db.refresh(asignacion)
        resultados.append(_build_asignacion_response(asignacion, usuario_destino, current_user))

    return resultados


@router.post("/asignar-masivo", response_model=List[AsignacionResponse])
async def asignar_masivo(
    request: AsignarMasivoRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> List[AsignacionResponse]:
    """
    Asigna múltiples items de una vez (multi-selección del frontend).
    Cada item puede tener diferentes listas para asignar.
    """
    usuario_destino_id = request.usuario_id or current_user.id
    _verificar_permiso_asignacion(db, current_user, usuario_destino_id)

    usuario_destino = db.query(Usuario).filter(Usuario.id == usuario_destino_id).first()
    if not usuario_destino:
        raise HTTPException(status_code=404, detail="Usuario destino no encontrado")

    creadas = []

    for item_data in request.items:
        item_id = item_data.get("item_id")
        listas = item_data.get("listas", [])
        listas_sin_mla = item_data.get("listas_sin_mla", [])

        if not item_id or not listas:
            continue

        for lista in listas:
            # Hash POR ASIGNACIÓN individual: item + lista específica
            estado_hash = _generar_estado_hash(item_id, lista, existe_mla=False)
            existente = (
                db.query(Asignacion)
                .filter(
                    and_(
                        Asignacion.tipo == "item_sin_mla",
                        Asignacion.referencia_id == item_id,
                        Asignacion.subtipo == lista,
                        Asignacion.estado == "pendiente",
                    )
                )
                .first()
            )

            if existente:
                continue

            nueva = Asignacion(
                tracking_id=uuid.uuid4(),
                tipo="item_sin_mla",
                referencia_id=item_id,
                subtipo=lista,
                usuario_id=usuario_destino_id,
                asignado_por_id=current_user.id,
                estado="pendiente",
                estado_hash=estado_hash,
                origen="manual",
                notas=request.notas,
                metadata_asignacion={
                    "listas_faltantes": listas_sin_mla,
                    "listas_asignadas": listas,
                },
            )
            db.add(nueva)
            creadas.append(nueva)

    db.commit()

    resultados = []
    for asignacion in creadas:
        db.refresh(asignacion)
        resultados.append(_build_asignacion_response(asignacion, usuario_destino, current_user))

    return resultados


@router.post("/desasignar")
async def desasignar(
    request: DesasignarRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> dict:
    """
    Desasigna (cancela) una o más asignaciones.

    - Propias: requiere admin.asignar_items_sin_mla
    - De otros: requiere admin.gestionar_asignaciones
    """
    canceladas = 0

    for asignacion_id in request.asignacion_ids:
        asignacion = (
            db.query(Asignacion).filter(and_(Asignacion.id == asignacion_id, Asignacion.estado == "pendiente")).first()
        )

        if not asignacion:
            continue

        # Verificar permisos según dueño
        _verificar_permiso_asignacion(db, current_user, asignacion.usuario_id)

        asignacion.estado = "cancelado"
        asignacion.fecha_resolucion = datetime.now(UTC)
        canceladas += 1

    db.commit()

    return {"success": True, "message": f"{canceladas} asignación(es) cancelada(s)", "canceladas": canceladas}


@router.post("/reasignar", response_model=List[AsignacionResponse])
async def reasignar(
    request: ReasignarRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> List[AsignacionResponse]:
    """
    Reasigna asignaciones pendientes a otro usuario.
    Cancela las originales y crea nuevas para el usuario destino.
    Preserva el estado_hash original para mantener la referencia de tracking.

    Requiere: admin.gestionar_asignaciones
    """
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "admin.gestionar_asignaciones"):
        raise HTTPException(status_code=403, detail="No tenés permiso para reasignar")

    # Verificar usuario destino
    usuario_destino = db.query(Usuario).filter(Usuario.id == request.usuario_id).first()
    if not usuario_destino:
        raise HTTPException(status_code=404, detail="Usuario destino no encontrado")

    nuevas = []

    for asignacion_id in request.asignacion_ids:
        original = (
            db.query(Asignacion).filter(and_(Asignacion.id == asignacion_id, Asignacion.estado == "pendiente")).first()
        )

        if not original:
            continue

        # Cancelar la original
        original.estado = "cancelado"
        original.fecha_resolucion = datetime.now(UTC)

        # Crear nueva para el destino (preserva hash y metadata)
        nueva = Asignacion(
            tracking_id=uuid.uuid4(),
            tipo=original.tipo,
            referencia_id=original.referencia_id,
            subtipo=original.subtipo,
            usuario_id=request.usuario_id,
            asignado_por_id=current_user.id,
            estado="pendiente",
            estado_hash=original.estado_hash,
            origen="manual",
            metadata_asignacion=original.metadata_asignacion,
            notas=f"Reasignado de {current_user.nombre}. {original.notas or ''}".strip(),
        )
        db.add(nueva)
        nuevas.append(nueva)

    db.commit()

    resultados = []
    for asignacion in nuevas:
        db.refresh(asignacion)
        resultados.append(_build_asignacion_response(asignacion, usuario_destino, current_user))

    return resultados


@router.get("/items-sin-mla", response_model=List[AsignacionResponse])
async def get_asignaciones_items_sin_mla(
    estado: Optional[str] = Query(
        "pendiente", description="Filtrar por estado: pendiente, completado, cancelado, todos"
    ),
    usuario_id: Optional[int] = Query(None, description="Filtrar por usuario asignado"),
    asignado_por_id: Optional[int] = Query(None, description="Filtrar por usuario que creó la asignación"),
    item_id: Optional[int] = Query(None, description="Filtrar por item_id específico"),
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (ISO format)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (ISO format)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[AsignacionResponse]:
    """
    Obtiene asignaciones de items sin MLA con filtros opcionales.
    Requiere al menos permiso de ver items sin MLA.
    """
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "admin.ver_items_sin_mla"):
        raise HTTPException(status_code=403, detail="No tenés permiso para ver items sin MLA")

    UsuarioAsignado = aliased(Usuario, name="usuario_asignado")
    UsuarioCreador = aliased(Usuario, name="usuario_creador")

    query = (
        db.query(Asignacion, UsuarioAsignado, UsuarioCreador)
        .join(UsuarioAsignado, UsuarioAsignado.id == Asignacion.usuario_id)
        .join(UsuarioCreador, UsuarioCreador.id == Asignacion.asignado_por_id)
        .filter(Asignacion.tipo == "item_sin_mla")
    )

    if estado and estado != "todos":
        query = query.filter(Asignacion.estado == estado)

    if usuario_id:
        query = query.filter(Asignacion.usuario_id == usuario_id)

    if asignado_por_id:
        query = query.filter(Asignacion.asignado_por_id == asignado_por_id)

    if item_id:
        query = query.filter(Asignacion.referencia_id == item_id)

    if fecha_desde:
        query = query.filter(Asignacion.fecha_asignacion >= fecha_desde)

    if fecha_hasta:
        query = query.filter(Asignacion.fecha_asignacion <= fecha_hasta)

    resultados = query.order_by(Asignacion.fecha_asignacion.desc()).all()

    return [_build_asignacion_response(a, ua, uc) for a, ua, uc in resultados]


@router.get("/mis-asignaciones", response_model=List[AsignacionResponse])
async def get_mis_asignaciones(
    tipo: Optional[str] = Query(None, description="Filtrar por tipo: item_sin_mla, etc."),
    estado: Optional[str] = Query("pendiente", description="Filtrar por estado"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[AsignacionResponse]:
    """
    Obtiene las asignaciones del usuario actual.
    Endpoint genérico que sirve para todos los tipos de asignación.
    Pensado para el futuro menú de asignaciones en la TopBar.
    """
    UsuarioAsignado = aliased(Usuario, name="usuario_asignado")
    UsuarioCreador = aliased(Usuario, name="usuario_creador")

    query = (
        db.query(Asignacion, UsuarioAsignado, UsuarioCreador)
        .join(UsuarioAsignado, UsuarioAsignado.id == Asignacion.usuario_id)
        .join(UsuarioCreador, UsuarioCreador.id == Asignacion.asignado_por_id)
        .filter(Asignacion.usuario_id == current_user.id)
    )

    if tipo:
        query = query.filter(Asignacion.tipo == tipo)

    if estado and estado != "todos":
        query = query.filter(Asignacion.estado == estado)

    resultados = query.order_by(Asignacion.fecha_asignacion.desc()).all()

    return [_build_asignacion_response(a, ua, uc) for a, ua, uc in resultados]


@router.get("/usuarios-asignables")
async def get_usuarios_asignables(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> List[dict]:
    """
    Obtiene la lista de usuarios activos que pueden recibir asignaciones.
    Para el dropdown de asignación/reasignación.

    Se permite ver la lista si tenés permiso de auto-asignarte O de gestionar.
    """
    from app.services.permisos_service import verificar_permiso

    puede_auto = verificar_permiso(db, current_user, "admin.asignar_items_sin_mla")
    puede_gestionar = verificar_permiso(db, current_user, "admin.gestionar_asignaciones")

    if not puede_auto and not puede_gestionar:
        raise HTTPException(status_code=403, detail="No tenés permiso para ver usuarios asignables")

    usuarios = db.query(Usuario).filter(Usuario.activo == True).order_by(Usuario.nombre).all()

    return [{"id": u.id, "nombre": u.nombre, "username": u.username} for u in usuarios]


@router.post("/verificar-estado", response_model=List[VerificarHashResponse])
async def verificar_estado_asignaciones(
    asignacion_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[VerificarHashResponse]:
    """
    Verifica si el estado de las asignaciones pendientes cambió desde que se asignaron.

    Compara el estado_hash guardado al asignar con el hash actual calculado
    desde las listas faltantes reales del item.

    Si cambió: el item fue resuelto (parcial o totalmente).
    Marca automáticamente como completada si la lista asignada ya no falta.

    Esto permite trackear métricas de productividad:
    - Tiempo desde asignación hasta resolución
    - Items resueltos por usuario
    - Velocidad de trabajo
    """
    from app.services.permisos_service import verificar_permiso
    from app.api.endpoints.items_sin_mla import LISTAS_PRECIOS, LISTAS_WEB_A_PVP
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

    if not verificar_permiso(db, current_user, "admin.ver_items_sin_mla"):
        raise HTTPException(status_code=403, detail="No tenés permiso")

    # Obtener asignaciones pendientes
    query = db.query(Asignacion).filter(and_(Asignacion.tipo == "item_sin_mla", Asignacion.estado == "pendiente"))

    if asignacion_ids:
        query = query.filter(Asignacion.id.in_(asignacion_ids))

    asignaciones = query.all()

    listas_relevantes = list(LISTAS_PRECIOS.keys())
    resultados = []

    for asignacion in asignaciones:
        item_id = asignacion.referencia_id
        lista_asignada = asignacion.subtipo

        if not lista_asignada:
            continue

        # Verificar si la lista ESPECÍFICA asignada ya tiene MLA
        listas_con_mla = (
            db.query(MercadoLibreItemPublicado.prli_id)
            .distinct()
            .filter(
                and_(
                    MercadoLibreItemPublicado.item_id == item_id,
                    MercadoLibreItemPublicado.prli_id.in_(listas_relevantes),
                )
            )
            .all()
        )

        listas_con_mla_ids = set([l[0] for l in listas_con_mla if l[0] is not None])

        # ¿La lista asignada ya tiene publicación? (verificar par Web/PVP)
        lista_tiene_mla = False
        for web_id, pvp_id in LISTAS_WEB_A_PVP.items():
            nombre_lista = LISTAS_PRECIOS[web_id]
            if nombre_lista == lista_asignada:
                tiene_web = web_id in listas_con_mla_ids
                tiene_pvp = pvp_id in listas_con_mla_ids
                lista_tiene_mla = tiene_web or tiene_pvp
                break

        # Hash actual: misma fórmula pero con el estado real de ESTA lista
        hash_actual = _generar_estado_hash(item_id, lista_asignada, existe_mla=lista_tiene_mla)

        cambio_detectado = asignacion.estado_hash is not None and hash_actual != asignacion.estado_hash

        # Resuelta = la lista asignada ahora SÍ tiene MLA
        resuelta = lista_tiene_mla

        tiempo_horas = None

        if resuelta:
            # Marcar como completada automáticamente
            asignacion.estado = "completado"
            asignacion.fecha_resolucion = datetime.now(UTC)

            # Calcular tiempo de resolución
            delta = asignacion.fecha_resolucion - asignacion.fecha_asignacion
            tiempo_horas = round(delta.total_seconds() / 3600, 2)

        resultados.append(
            VerificarHashResponse(
                asignacion_id=asignacion.id,
                item_id=item_id,
                subtipo=lista_asignada,
                hash_original=asignacion.estado_hash,
                hash_actual=hash_actual,
                cambio_detectado=cambio_detectado,
                resuelta=resuelta,
                tiempo_resolucion_horas=tiempo_horas,
            )
        )

    # Commit todas las resoluciones de una vez
    db.commit()

    return resultados
