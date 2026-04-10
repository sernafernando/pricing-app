import math
import os
import uuid
from datetime import UTC, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.sse import sse_publish
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.tickets.models.adjunto_ticket import AdjuntoTicket
from app.tickets.models.sector_usuario import SectorUsuario
from app.tickets.models.asignacion_ticket import AsignacionTicket, TipoAsignacion
from app.tickets.models.comentario_ticket import ComentarioTicket
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from app.tickets.schemas.ticket_schemas import (
    AdjuntoResponse,
    AsignarTicketRequest,
    ComentarioCreate,
    ComentarioResponse,
    HistorialResponse,
    TicketBadgeCount,
    TicketCreate,
    TicketListPaginatedResponse,
    TicketResponse,
    TicketUpdate,
    TransicionRequest,
)

router = APIRouter()

# Allowed MIME types for ticket attachments
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Raise 403 if user lacks the required permission."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


def _tiene_permiso(db: Session, user: Usuario, permiso: str) -> bool:
    """Check if user has a permission without raising."""
    return PermisosService(db).tiene_permiso(user, permiso)


def _check_acceso_ticket(db: Session, user: Usuario, ticket: Ticket) -> None:
    """
    Verifica que el usuario puede acceder a un ticket.
    - Si tiene tickets.ver → acceso a todos
    - Si es el creador → acceso a su ticket
    - Sino → 403
    """
    if _tiene_permiso(db, user, "tickets.ver"):
        return
    if ticket.creador_id == user.id:
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a este ticket")


# ── Badge count (MUST be before /{ticket_id} to avoid path capture) ──


@router.get("/tickets/mis-pendientes/count", response_model=TicketBadgeCount)
async def badge_count(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketBadgeCount:
    """
    Retorna la cantidad de tickets con actividad no leída para el usuario.

    Lógica:
    Un ticket cuenta como "pendiente" si tiene actividad (comentario,
    cambio de estado, asignación) POSTERIOR a la última vez que el usuario
    lo marcó como revisado.  Si nunca lo revisó, cuenta siempre.

    Alcance:
    - tickets.ver → tickets de sus sectores (asignados o no) + los que creó
    - sin tickets.ver → solo tickets que creó el usuario

    Usado por TicketBadge en el TopBar.
    """
    from sqlalchemy import func, or_

    puede_ver = PermisosService(db).tiene_permiso(current_user, "tickets.ver")

    # ── Sub-query: última revisión del usuario por ticket ────────────
    ultima_revision = (
        db.query(
            HistorialTicket.ticket_id,
            func.max(HistorialTicket.fecha).label("ultima_fecha"),
        )
        .filter(
            HistorialTicket.accion == "revisado",
            HistorialTicket.usuario_id == current_user.id,
        )
        .group_by(HistorialTicket.ticket_id)
        .subquery()
    )

    # ── Sub-query: última actividad real por ticket ──────────────────
    # Actividad = cualquier acción que NO sea "revisado"
    ultima_actividad = (
        db.query(
            HistorialTicket.ticket_id,
            func.max(HistorialTicket.fecha).label("ultima_fecha"),
        )
        .filter(HistorialTicket.accion != "revisado")
        .group_by(HistorialTicket.ticket_id)
        .subquery()
    )

    # ── Query base: tickets abiertos ─────────────────────────────────
    query = (
        db.query(func.count(Ticket.id))
        .join(EstadoTicket, Ticket.estado_id == EstadoTicket.id)
        .outerjoin(ultima_revision, Ticket.id == ultima_revision.c.ticket_id)
        .outerjoin(ultima_actividad, Ticket.id == ultima_actividad.c.ticket_id)
        .filter(
            EstadoTicket.es_final.is_(False),
            # Tiene actividad Y (nunca revisado O actividad posterior a revisión)
            ultima_actividad.c.ultima_fecha.isnot(None),
            or_(
                ultima_revision.c.ultima_fecha.is_(None),
                ultima_actividad.c.ultima_fecha > ultima_revision.c.ultima_fecha,
            ),
        )
    )

    if puede_ver:
        # Gestores: tickets de sus sectores + los que crearon
        mis_sectores = (
            db.query(SectorUsuario.sector_id)
            .filter(
                SectorUsuario.usuario_id == current_user.id,
                SectorUsuario.activo.is_(True),
            )
            .scalar_subquery()
        )
        query = query.filter(
            or_(
                Ticket.sector_id.in_(mis_sectores),
                Ticket.creador_id == current_user.id,
            )
        )
    else:
        # Usuarios normales: solo sus tickets
        query = query.filter(Ticket.creador_id == current_user.id)

    pendientes = query.scalar() or 0
    return TicketBadgeCount(pendientes=pendientes)


@router.post("/tickets/marcar-revisado/{ticket_id}")
async def marcar_revisado(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca un ticket como revisado por el usuario actual.

    Crea una entrada 'revisado' en el historial. La siguiente actividad
    (comentario, cambio de estado, asignación) invalidará esta marca
    y el badge volverá a contar el ticket.

    Acceso: gestores con tickets.ver O el creador del ticket.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    # Gestores o creador del ticket pueden marcar como revisado
    _check_acceso_ticket(db, current_user, ticket)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="revisado",
        descripcion="Ticket marcado como revisado",
        cambios={},
    )
    db.add(historial_entry)
    db.commit()

    await sse_publish("tickets:badge", {"hint": "reload"})

    return {"ok": True}


# ── CRUD de tickets ──────────────────────────────────────────────


@router.post("/tickets", response_model=TicketResponse, status_code=201)
async def crear_ticket(
    ticket_data: TicketCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Crea un nuevo ticket.

    Cualquier usuario logueado puede crear tickets.
    """

    # Validar sector
    sector = db.query(Sector).filter(Sector.id == ticket_data.sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {ticket_data.sector_id} no encontrado")

    if not sector.activo:
        raise HTTPException(status_code=400, detail=f"Sector {sector.nombre} está inactivo")

    # Validar tipo de ticket
    tipo_ticket = (
        db.query(TipoTicket)
        .filter(TipoTicket.id == ticket_data.tipo_ticket_id, TipoTicket.sector_id == ticket_data.sector_id)
        .first()
    )
    if not tipo_ticket:
        raise HTTPException(
            status_code=404,
            detail=f"Tipo de ticket {ticket_data.tipo_ticket_id} no encontrado para sector {sector.codigo}",
        )

    # Obtener workflow (del tipo o default del sector)
    workflow = tipo_ticket.workflow if tipo_ticket.workflow_id else None
    if not workflow:
        workflow = (
            db.query(Workflow)
            .filter(Workflow.sector_id == sector.id, Workflow.es_default == True, Workflow.activo == True)
            .first()
        )

    if not workflow:
        raise HTTPException(status_code=400, detail=f"No hay workflow configurado para sector {sector.codigo}")

    # Obtener estado inicial del workflow
    estado_inicial = (
        db.query(EstadoTicket).filter(EstadoTicket.workflow_id == workflow.id, EstadoTicket.es_inicial == True).first()
    )

    if not estado_inicial:
        raise HTTPException(status_code=400, detail=f"Workflow {workflow.nombre} no tiene estado inicial definido")

    # Crear ticket
    nuevo_ticket = Ticket(
        titulo=ticket_data.titulo,
        descripcion=ticket_data.descripcion,
        prioridad=ticket_data.prioridad,
        sector_id=sector.id,
        tipo_ticket_id=tipo_ticket.id,
        estado_id=estado_inicial.id,
        creador_id=current_user.id,
        campos_metadata=ticket_data.metadata,
    )

    db.add(nuevo_ticket)
    db.flush()

    # Historial entry for creation
    historial_entry = HistorialTicket(
        ticket_id=nuevo_ticket.id,
        usuario_id=current_user.id,
        accion="created",
        descripcion=f"Ticket creado en sector {sector.nombre}",
        estado_nuevo_id=estado_inicial.id,
        cambios={},
    )
    db.add(historial_entry)

    db.commit()
    db.refresh(nuevo_ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return nuevo_ticket


@router.get("/tickets", response_model=TicketListPaginatedResponse)
async def listar_tickets(
    sector_id: Optional[int] = Query(None, description="Filtrar por sector"),
    estado_id: Optional[int] = Query(None, description="Filtrar por estado"),
    asignado_a_id: Optional[int] = Query(None, description="Filtrar por usuario asignado"),
    creador_id: Optional[int] = Query(None, description="Filtrar por creador"),
    prioridad: Optional[PrioridadTicket] = Query(None, description="Filtrar por prioridad"),
    esta_cerrado: Optional[bool] = Query(None, description="Filtrar por cerrado/abierto"),
    busqueda: Optional[str] = Query(None, description="Buscar en título"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketListPaginatedResponse:
    """
    Lista tickets con filtros opcionales y paginación completa.

    - Sin tickets.ver → solo ve tickets que creó
    - Con tickets.ver → ve tickets de sus sectores asignados + los que creó
    - Con tickets.admin → ve todos los tickets
    """
    puede_ver_sector = _tiene_permiso(db, current_user, "tickets.ver")
    es_admin = _tiene_permiso(db, current_user, "tickets.admin")

    query = db.query(Ticket)

    if es_admin:
        # Admin ve todo
        pass
    elif puede_ver_sector:
        # Ve tickets de sus sectores + los que creó
        from sqlalchemy import or_

        mis_sectores = (
            db.query(SectorUsuario.sector_id)
            .filter(SectorUsuario.usuario_id == current_user.id, SectorUsuario.activo.is_(True))
            .scalar_subquery()
        )
        query = query.filter(
            or_(
                Ticket.sector_id.in_(mis_sectores),
                Ticket.creador_id == current_user.id,
            )
        )
    else:
        # Solo ve sus propios tickets
        query = query.filter(Ticket.creador_id == current_user.id)

    # Aplicar filtros
    if sector_id:
        query = query.filter(Ticket.sector_id == sector_id)

    if estado_id:
        query = query.filter(Ticket.estado_id == estado_id)

    if prioridad:
        query = query.filter(Ticket.prioridad == prioridad)

    if creador_id:
        query = query.filter(Ticket.creador_id == creador_id)

    if asignado_a_id:
        query = query.join(AsignacionTicket).filter(
            AsignacionTicket.asignado_a_id == asignado_a_id,
            AsignacionTicket.fecha_finalizacion.is_(None),
        )

    if esta_cerrado is not None:
        if not estado_id:
            query = query.join(EstadoTicket).filter(EstadoTicket.es_final == esta_cerrado)

    if busqueda:
        query = query.filter(Ticket.titulo.ilike(f"%{busqueda}%"))

    # Total count
    from sqlalchemy import func

    total = query.with_entities(func.count(Ticket.id)).scalar() or 0

    # Ordenar por fecha de creación (más recientes primero)
    query = query.order_by(Ticket.created_at.desc())

    # Paginación
    offset = (page - 1) * page_size
    tickets = query.offset(offset).limit(page_size).all()

    pages = math.ceil(total / page_size) if page_size > 0 else 0

    return TicketListPaginatedResponse(
        items=tickets,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def obtener_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Obtiene un ticket por ID con todas sus relaciones cargadas.

    - Usuarios con tickets.ver → acceso a cualquier ticket
    - Creador del ticket → acceso a su ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
async def actualizar_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Actualiza campos de un ticket.

    - Creador puede editar su propio ticket
    - Usuarios con tickets.gestionar pueden editar cualquier ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    es_creador = ticket.creador_id == current_user.id
    puede_gestionar = _tiene_permiso(db, current_user, "tickets.gestionar")
    if not es_creador and not puede_gestionar:
        raise HTTPException(status_code=403, detail="No tenés acceso a este ticket")

    # Registrar cambios en historial
    cambios_realizados = {}

    if ticket_data.titulo is not None and ticket_data.titulo != ticket.titulo:
        cambios_realizados["titulo"] = {"valor_anterior": ticket.titulo, "valor_nuevo": ticket_data.titulo}
        ticket.titulo = ticket_data.titulo

    if ticket_data.descripcion is not None and ticket_data.descripcion != ticket.descripcion:
        cambios_realizados["descripcion"] = {
            "valor_anterior": ticket.descripcion,
            "valor_nuevo": ticket_data.descripcion,
        }
        ticket.descripcion = ticket_data.descripcion

    if ticket_data.prioridad is not None and ticket_data.prioridad != ticket.prioridad:
        cambios_realizados["prioridad"] = {
            "valor_anterior": ticket.prioridad.value,
            "valor_nuevo": ticket_data.prioridad.value,
        }
        ticket.prioridad = ticket_data.prioridad

    if ticket_data.metadata is not None:
        for key, value in ticket_data.metadata.items():
            if key not in ticket.campos_metadata or ticket.campos_metadata[key] != value:
                cambios_realizados[f"metadata.{key}"] = {
                    "valor_anterior": ticket.campos_metadata.get(key),
                    "valor_nuevo": value,
                }
        ticket.campos_metadata.update(ticket_data.metadata)

    if cambios_realizados:
        historial_entry = HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=current_user.id,
            accion="metadata_updated",
            descripcion="Actualización de campos del ticket",
            cambios=cambios_realizados,
        )
        db.add(historial_entry)

    db.commit()
    db.refresh(ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})

    return ticket


@router.post("/tickets/{ticket_id}/transicion", response_model=TicketResponse)
async def cambiar_estado_ticket(
    ticket_id: int,
    transicion_data: TransicionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Cambia el estado de un ticket siguiendo las transiciones del workflow.

    Requiere: tickets.gestionar
    """
    _check_permiso(db, current_user, "tickets.gestionar")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    nuevo_estado = db.query(EstadoTicket).filter(EstadoTicket.id == transicion_data.nuevo_estado_id).first()

    if not nuevo_estado:
        raise HTTPException(status_code=404, detail=f"Estado {transicion_data.nuevo_estado_id} no encontrado")

    if ticket.estado.workflow_id != nuevo_estado.workflow_id:
        raise HTTPException(status_code=400, detail="El nuevo estado no pertenece al workflow del ticket")

    estado_anterior = ticket.estado
    ticket.estado_id = nuevo_estado.id

    if nuevo_estado.es_final:
        ticket.closed_at = datetime.now(UTC)

    if transicion_data.metadata:
        ticket.campos_metadata.update(transicion_data.metadata)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="estado_changed",
        descripcion=f"Estado cambiado de {estado_anterior.nombre} a {nuevo_estado.nombre}",
        estado_anterior_id=estado_anterior.id,
        estado_nuevo_id=nuevo_estado.id,
        cambios={"comentario": transicion_data.comentario} if transicion_data.comentario else {},
    )
    db.add(historial_entry)

    if transicion_data.comentario:
        comentario = ComentarioTicket(
            ticket_id=ticket.id,
            usuario_id=current_user.id,
            contenido=transicion_data.comentario,
            es_interno=False,
        )
        db.add(comentario)

    db.commit()
    db.refresh(ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return ticket


@router.post("/tickets/{ticket_id}/asignar", response_model=TicketResponse)
async def asignar_ticket(
    ticket_id: int,
    asignacion_data: AsignarTicketRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Asigna un ticket a un usuario.

    Requiere: tickets.gestionar
    """
    _check_permiso(db, current_user, "tickets.gestionar")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    usuario_asignar = db.query(Usuario).filter(Usuario.id == asignacion_data.usuario_id).first()
    if not usuario_asignar:
        raise HTTPException(status_code=404, detail=f"Usuario {asignacion_data.usuario_id} no encontrado")

    asignacion_actual = ticket.asignacion_actual
    if asignacion_actual:
        asignacion_actual.fecha_finalizacion = datetime.now(UTC)

    nueva_asignacion = AsignacionTicket(
        ticket_id=ticket.id,
        asignado_a_id=asignacion_data.usuario_id,
        asignado_por_id=current_user.id,
        tipo=TipoAsignacion.MANUAL,
        motivo=asignacion_data.motivo,
    )
    db.add(nueva_asignacion)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="asignado",
        descripcion=f"Ticket asignado a {usuario_asignar.nombre}",
        cambios={
            "asignado_a": {
                "valor_anterior": asignacion_actual.asignado_a.nombre if asignacion_actual else None,
                "valor_nuevo": usuario_asignar.nombre,
            },
            "motivo": asignacion_data.motivo,
        },
    )
    db.add(historial_entry)

    db.commit()
    db.refresh(ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return ticket


# ── Comentarios ──────────────────────────────────────────────────


@router.post("/tickets/{ticket_id}/comentarios", response_model=ComentarioResponse, status_code=201)
async def agregar_comentario(
    ticket_id: int,
    comentario_data: ComentarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ComentarioResponse:
    """
    Agrega un comentario a un ticket.

    - Creador puede comentar en su propio ticket (solo comentarios públicos)
    - Usuarios con tickets.ver pueden comentar en cualquier ticket
    - Comentarios internos requieren tickets.gestionar
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    # Solo gestores pueden crear comentarios internos
    if comentario_data.es_interno and not _tiene_permiso(db, current_user, "tickets.gestionar"):
        raise HTTPException(status_code=403, detail="Solo gestores pueden crear comentarios internos")

    nuevo_comentario = ComentarioTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        contenido=comentario_data.contenido,
        es_interno=comentario_data.es_interno,
    )

    db.add(nuevo_comentario)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="comentado",
        descripcion=f"Comentario {'interno' if comentario_data.es_interno else 'público'} agregado",
        cambios={},
    )
    db.add(historial_entry)

    db.commit()
    db.refresh(nuevo_comentario)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return nuevo_comentario


@router.get("/tickets/{ticket_id}/comentarios", response_model=List[ComentarioResponse])
async def listar_comentarios(
    ticket_id: int,
    incluir_internos: bool = Query(True, description="Incluir comentarios internos"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ComentarioResponse]:
    """
    Lista los comentarios de un ticket.

    - Creador ve solo comentarios públicos de su ticket
    - Usuarios con tickets.ver ven todos (internos según parámetro)
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    query = db.query(ComentarioTicket).filter(ComentarioTicket.ticket_id == ticket_id)

    # Creadores sin tickets.gestionar nunca ven comentarios internos
    puede_ver_internos = _tiene_permiso(db, current_user, "tickets.gestionar")
    if not incluir_internos or not puede_ver_internos:
        query = query.filter(ComentarioTicket.es_interno == False)

    comentarios = query.order_by(ComentarioTicket.created_at.asc()).all()

    return comentarios


# ── Historial ────────────────────────────────────────────────────


@router.get("/tickets/{ticket_id}/historial", response_model=List[HistorialResponse])
async def obtener_historial(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[HistorialResponse]:
    """
    Obtiene el historial completo de cambios de un ticket.

    - Creador puede ver historial de su ticket
    - Usuarios con tickets.ver pueden ver historial de cualquier ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    historial = (
        db.query(HistorialTicket)
        .filter(HistorialTicket.ticket_id == ticket_id)
        .order_by(HistorialTicket.fecha.desc())
        .all()
    )

    return historial


# ── Adjuntos (file upload/download/delete) ───────────────────────


@router.post("/tickets/{ticket_id}/adjuntos", response_model=AdjuntoResponse, status_code=201)
async def subir_adjunto(
    ticket_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdjuntoResponse:
    """
    Sube un archivo adjunto a un ticket.

    MIME types permitidos: imágenes, PDF, documentos Office.
    Tamaño máximo: TICKETS_MAX_FILE_SIZE_MB (default 5MB).

    Cualquier usuario logueado puede subir adjuntos a sus propios tickets.
    Usuarios con tickets.ver pueden subir a cualquier ticket.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    # Validar MIME type
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido: {file.content_type}",
        )

    # Leer archivo
    content = await file.read()
    max_bytes = settings.TICKETS_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo demasiado grande. Máximo: {settings.TICKETS_MAX_FILE_SIZE_MB}MB",
        )

    # Guardar en disco: uploads/tickets/{ticket_id}/{uuid}_{filename}
    upload_dir = os.path.join(settings.TICKETS_UPLOADS_DIR, str(ticket_id))
    os.makedirs(upload_dir, exist_ok=True)

    safe_filename = file.filename or "archivo"
    stored_name = f"{uuid.uuid4().hex}_{safe_filename}"
    full_path = os.path.join(upload_dir, stored_name)

    with open(full_path, "wb") as f:
        f.write(content)

    # Guardar en DB (path relativo)
    rel_path = os.path.join(str(ticket_id), stored_name)
    adjunto = AdjuntoTicket(
        ticket_id=ticket_id,
        nombre_archivo=safe_filename,
        path_archivo=rel_path,
        mime_type=file.content_type,
        tamano_bytes=len(content),
        subido_por_id=current_user.id,
    )
    db.add(adjunto)
    db.commit()
    db.refresh(adjunto)

    await sse_publish("tickets:changed", {"hint": "reload"})

    return adjunto


@router.get("/tickets/{ticket_id}/adjuntos", response_model=List[AdjuntoResponse])
async def listar_adjuntos(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[AdjuntoResponse]:
    """
    Lista los adjuntos de un ticket.

    - Creador puede ver adjuntos de su ticket
    - Usuarios con tickets.ver pueden ver adjuntos de cualquier ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    adjuntos = (
        db.query(AdjuntoTicket)
        .filter(AdjuntoTicket.ticket_id == ticket_id)
        .order_by(AdjuntoTicket.created_at.asc())
        .all()
    )

    return adjuntos


@router.get("/tickets/{ticket_id}/adjuntos/{adjunto_id}/descargar")
async def descargar_adjunto(
    ticket_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FileResponse:
    """
    Descarga un adjunto de ticket. Auth-gated (no StaticFiles).

    Requiere: tickets.ver
    """
    _check_permiso(db, current_user, "tickets.ver")

    adjunto = (
        db.query(AdjuntoTicket).filter(AdjuntoTicket.id == adjunto_id, AdjuntoTicket.ticket_id == ticket_id).first()
    )
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    full_path = os.path.join(settings.TICKETS_UPLOADS_DIR, adjunto.path_archivo)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")

    return FileResponse(
        path=full_path,
        filename=adjunto.nombre_archivo,
        media_type=adjunto.mime_type or "application/octet-stream",
    )


@router.delete("/tickets/{ticket_id}/adjuntos/{adjunto_id}", status_code=204)
async def eliminar_adjunto(
    ticket_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Elimina un adjunto de ticket (archivo + registro).

    Requiere: tickets.gestionar
    """
    _check_permiso(db, current_user, "tickets.gestionar")

    adjunto = (
        db.query(AdjuntoTicket).filter(AdjuntoTicket.id == adjunto_id, AdjuntoTicket.ticket_id == ticket_id).first()
    )
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    # Eliminar archivo de disco
    full_path = os.path.join(settings.TICKETS_UPLOADS_DIR, adjunto.path_archivo)
    if os.path.exists(full_path):
        os.remove(full_path)

    db.delete(adjunto)
    db.commit()

    await sse_publish("tickets:changed", {"hint": "reload"})
