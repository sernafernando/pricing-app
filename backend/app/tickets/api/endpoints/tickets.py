from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.sector import Sector
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket
from app.tickets.models.comentario_ticket import ComentarioTicket
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.schemas.ticket_schemas import (
    TicketCreate,
    TicketUpdate,
    TicketResponse,
    TicketListResponse,
    ComentarioCreate,
    ComentarioResponse,
    HistorialResponse,
    TransicionRequest,
    AsignarTicketRequest
)

router = APIRouter()


@router.post("/tickets", response_model=TicketResponse, status_code=201)
async def crear_ticket(
    ticket_data: TicketCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea un nuevo ticket.
    
    Pasos:
    1. Valida que el sector y tipo de ticket existan
    2. Obtiene el workflow y estado inicial
    3. Crea el ticket
    4. TODO: Llamar a WorkflowService para asignación automática si configurado
    5. TODO: Disparar eventos de creación
    
    Returns:
        Ticket creado con sus relaciones cargadas
    """
    # Validar sector
    sector = db.query(Sector).filter(Sector.id == ticket_data.sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {ticket_data.sector_id} no encontrado")
    
    if not sector.activo:
        raise HTTPException(status_code=400, detail=f"Sector {sector.nombre} está inactivo")
    
    # Validar tipo de ticket
    tipo_ticket = db.query(TipoTicket).filter(
        TipoTicket.id == ticket_data.tipo_ticket_id,
        TipoTicket.sector_id == ticket_data.sector_id
    ).first()
    if not tipo_ticket:
        raise HTTPException(
            status_code=404, 
            detail=f"Tipo de ticket {ticket_data.tipo_ticket_id} no encontrado para sector {sector.codigo}"
        )
    
    # Obtener workflow (del tipo o default del sector)
    workflow = tipo_ticket.workflow if tipo_ticket.workflow_id else None
    if not workflow:
        # Buscar workflow default del sector
        from app.tickets.models.workflow import Workflow
        workflow = db.query(Workflow).filter(
            Workflow.sector_id == sector.id,
            Workflow.es_default == True,
            Workflow.activo == True
        ).first()
    
    if not workflow:
        raise HTTPException(
            status_code=400,
            detail=f"No hay workflow configurado para sector {sector.codigo}"
        )
    
    # Obtener estado inicial del workflow
    estado_inicial = db.query(EstadoTicket).filter(
        EstadoTicket.workflow_id == workflow.id,
        EstadoTicket.es_inicial == True
    ).first()
    
    if not estado_inicial:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow {workflow.nombre} no tiene estado inicial definido"
        )
    
    # Crear ticket
    nuevo_ticket = Ticket(
        titulo=ticket_data.titulo,
        descripcion=ticket_data.descripcion,
        prioridad=ticket_data.prioridad,
        sector_id=sector.id,
        tipo_ticket_id=tipo_ticket.id,
        estado_id=estado_inicial.id,
        creador_id=current_user.id,
        metadata=ticket_data.metadata
    )
    
    db.add(nuevo_ticket)
    db.commit()
    db.refresh(nuevo_ticket)
    
    # TODO: Llamar a WorkflowService.on_ticket_created() para:
    # - Asignación automática según configuración del sector
    # - Disparar eventos de notificación
    # - Ejecutar acciones on_enter del estado inicial
    
    return nuevo_ticket


@router.get("/tickets", response_model=List[TicketListResponse])
async def listar_tickets(
    sector_id: Optional[int] = Query(None, description="Filtrar por sector"),
    estado_id: Optional[int] = Query(None, description="Filtrar por estado"),
    asignado_a_id: Optional[int] = Query(None, description="Filtrar por usuario asignado"),
    creador_id: Optional[int] = Query(None, description="Filtrar por creador"),
    prioridad: Optional[PrioridadTicket] = Query(None, description="Filtrar por prioridad"),
    esta_cerrado: Optional[bool] = Query(None, description="Filtrar por cerrado/abierto"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Lista tickets con filtros opcionales.
    
    Permite filtrar por:
    - Sector
    - Estado
    - Usuario asignado
    - Creador
    - Prioridad
    - Si está cerrado o no
    
    Implementa paginación.
    """
    query = db.query(Ticket)
    
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
        # Filtrar por tickets con asignación activa a este usuario
        from app.tickets.models.asignacion_ticket import AsignacionTicket
        query = query.join(AsignacionTicket).filter(
            AsignacionTicket.asignado_a_id == asignado_a_id,
            AsignacionTicket.fecha_finalizacion.is_(None)
        )
    
    if esta_cerrado is not None:
        query = query.join(EstadoTicket).filter(
            EstadoTicket.es_final == esta_cerrado
        )
    
    # Ordenar por fecha de creación (más recientes primero)
    query = query.order_by(Ticket.created_at.desc())
    
    # Paginación
    offset = (page - 1) * page_size
    tickets = query.offset(offset).limit(page_size).all()
    
    return tickets


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def obtener_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene un ticket por ID con todas sus relaciones cargadas.
    
    Returns:
        Ticket completo con sector, tipo, estado, creador, asignado_a, etc.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    # TODO: Verificar permisos (puede ver solo si es creador, asignado, o tiene permiso en el sector)
    
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
async def actualizar_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Actualiza campos de un ticket.
    
    Permite actualizar:
    - Título
    - Descripción
    - Prioridad
    - Metadata (campos dinámicos)
    
    NO permite cambiar estado (usar POST /tickets/{id}/transicion)
    NO permite cambiar asignación (usar POST /tickets/{id}/asignar)
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    # TODO: Verificar permisos (solo creador, asignado, o admin del sector)
    
    # Registrar cambios en historial
    cambios_realizados = {}
    
    if ticket_data.titulo is not None and ticket_data.titulo != ticket.titulo:
        cambios_realizados["titulo"] = {
            "valor_anterior": ticket.titulo,
            "valor_nuevo": ticket_data.titulo
        }
        ticket.titulo = ticket_data.titulo
    
    if ticket_data.descripcion is not None and ticket_data.descripcion != ticket.descripcion:
        cambios_realizados["descripcion"] = {
            "valor_anterior": ticket.descripcion,
            "valor_nuevo": ticket_data.descripcion
        }
        ticket.descripcion = ticket_data.descripcion
    
    if ticket_data.prioridad is not None and ticket_data.prioridad != ticket.prioridad:
        cambios_realizados["prioridad"] = {
            "valor_anterior": ticket.prioridad.value,
            "valor_nuevo": ticket_data.prioridad.value
        }
        ticket.prioridad = ticket_data.prioridad
    
    if ticket_data.metadata is not None:
        # Merge metadata (no reemplazar completo)
        for key, value in ticket_data.metadata.items():
            if key not in ticket.metadata or ticket.metadata[key] != value:
                cambios_realizados[f"metadata.{key}"] = {
                    "valor_anterior": ticket.metadata.get(key),
                    "valor_nuevo": value
                }
        ticket.metadata.update(ticket_data.metadata)
    
    if cambios_realizados:
        # Crear entrada en historial
        historial_entry = HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=current_user.id,
            accion="metadata_updated",
            descripcion=f"Actualización de campos del ticket",
            cambios=cambios_realizados
        )
        db.add(historial_entry)
    
    db.commit()
    db.refresh(ticket)
    
    return ticket


@router.post("/tickets/{ticket_id}/transicion", response_model=TicketResponse)
async def cambiar_estado_ticket(
    ticket_id: int,
    transicion_data: TransicionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Cambia el estado de un ticket siguiendo las transiciones del workflow.
    
    Valida:
    - Que la transición esté permitida por el workflow
    - Que el usuario tenga permisos para realizar la transición
    - Que se cumplan las validaciones requeridas
    
    Ejecuta:
    - Acciones de la transición
    - Acciones on_enter del nuevo estado
    - Registra en historial
    - Dispara notificaciones
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    nuevo_estado = db.query(EstadoTicket).filter(
        EstadoTicket.id == transicion_data.nuevo_estado_id
    ).first()
    
    if not nuevo_estado:
        raise HTTPException(
            status_code=404, 
            detail=f"Estado {transicion_data.nuevo_estado_id} no encontrado"
        )
    
    # Validar que ambos estados pertenecen al mismo workflow
    if ticket.estado.workflow_id != nuevo_estado.workflow_id:
        raise HTTPException(
            status_code=400,
            detail="El nuevo estado no pertenece al workflow del ticket"
        )
    
    # TODO: Llamar a WorkflowService.transition() para:
    # - Validar que la transición está permitida
    # - Verificar permisos del usuario
    # - Ejecutar validaciones
    # - Ejecutar acciones de la transición
    # - Ejecutar acciones on_enter del nuevo estado
    # - Registrar en historial
    # - Disparar notificaciones
    
    # Por ahora, solo cambiar el estado (simplificado)
    estado_anterior = ticket.estado
    ticket.estado_id = nuevo_estado.id
    
    # Si el nuevo estado es final, marcar closed_at
    if nuevo_estado.es_final:
        from datetime import datetime
        ticket.closed_at = datetime.utcnow()
    
    # Actualizar metadata si se proveyó
    if transicion_data.metadata:
        ticket.metadata.update(transicion_data.metadata)
    
    # Registrar en historial
    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="estado_changed",
        descripcion=f"Estado cambiado de {estado_anterior.nombre} a {nuevo_estado.nombre}",
        estado_anterior_id=estado_anterior.id,
        estado_nuevo_id=nuevo_estado.id,
        cambios={"comentario": transicion_data.comentario} if transicion_data.comentario else {}
    )
    db.add(historial_entry)
    
    # Si hay comentario, agregarlo
    if transicion_data.comentario:
        comentario = ComentarioTicket(
            ticket_id=ticket.id,
            usuario_id=current_user.id,
            contenido=transicion_data.comentario,
            es_interno=False
        )
        db.add(comentario)
    
    db.commit()
    db.refresh(ticket)
    
    return ticket


@router.post("/tickets/{ticket_id}/asignar", response_model=TicketResponse)
async def asignar_ticket(
    ticket_id: int,
    asignacion_data: AsignarTicketRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Asigna un ticket a un usuario.
    
    Si el ticket ya tiene asignación activa, la finaliza y crea una nueva.
    Registra en historial y dispara notificaciones.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    # Validar que el usuario a asignar existe
    usuario_asignar = db.query(Usuario).filter(Usuario.id == asignacion_data.usuario_id).first()
    if not usuario_asignar:
        raise HTTPException(status_code=404, detail=f"Usuario {asignacion_data.usuario_id} no encontrado")
    
    # TODO: Validar permisos del usuario para ser asignado a este sector
    # TODO: Llamar a AssignmentService.assign() para manejar lógica compleja
    
    # Finalizar asignación activa si existe
    from app.tickets.models.asignacion_ticket import AsignacionTicket, TipoAsignacion
    from datetime import datetime
    
    asignacion_actual = ticket.asignacion_actual
    if asignacion_actual:
        asignacion_actual.fecha_finalizacion = datetime.utcnow()
    
    # Crear nueva asignación
    nueva_asignacion = AsignacionTicket(
        ticket_id=ticket.id,
        asignado_a_id=asignacion_data.usuario_id,
        asignado_por_id=current_user.id,
        tipo=TipoAsignacion.MANUAL,
        motivo=asignacion_data.motivo
    )
    db.add(nueva_asignacion)
    
    # Registrar en historial
    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="asignado",
        descripcion=f"Ticket asignado a {usuario_asignar.nombre}",
        cambios={
            "asignado_a": {
                "valor_anterior": asignacion_actual.asignado_a.nombre if asignacion_actual else None,
                "valor_nuevo": usuario_asignar.nombre
            },
            "motivo": asignacion_data.motivo
        }
    )
    db.add(historial_entry)
    
    db.commit()
    db.refresh(ticket)
    
    # TODO: Disparar notificación al usuario asignado
    
    return ticket


@router.post("/tickets/{ticket_id}/comentarios", response_model=ComentarioResponse, status_code=201)
async def agregar_comentario(
    ticket_id: int,
    comentario_data: ComentarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Agrega un comentario a un ticket.
    
    Los comentarios pueden ser internos (solo visibles para el equipo)
    o públicos (visibles también para el creador del ticket).
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    # TODO: Verificar permisos (puede comentar si es creador, asignado, o tiene permiso en el sector)
    
    nuevo_comentario = ComentarioTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        contenido=comentario_data.contenido,
        es_interno=comentario_data.es_interno
    )
    
    db.add(nuevo_comentario)
    
    # Registrar en historial
    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="comentado",
        descripcion=f"Comentario {'interno' if comentario_data.es_interno else 'público'} agregado",
        cambios={}
    )
    db.add(historial_entry)
    
    db.commit()
    db.refresh(nuevo_comentario)
    
    # TODO: Disparar notificaciones según configuración del sector
    
    return nuevo_comentario


@router.get("/tickets/{ticket_id}/comentarios", response_model=List[ComentarioResponse])
async def listar_comentarios(
    ticket_id: int,
    incluir_internos: bool = Query(True, description="Incluir comentarios internos"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Lista los comentarios de un ticket.
    
    Por defecto incluye comentarios internos. Si el usuario no tiene permisos
    para ver internos, se filtran automáticamente.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    query = db.query(ComentarioTicket).filter(ComentarioTicket.ticket_id == ticket_id)
    
    # TODO: Filtrar comentarios internos si el usuario no tiene permisos
    # Por ahora, si pide no incluir internos, los filtramos
    if not incluir_internos:
        query = query.filter(ComentarioTicket.es_interno == False)
    
    comentarios = query.order_by(ComentarioTicket.created_at.asc()).all()
    
    return comentarios


@router.get("/tickets/{ticket_id}/historial", response_model=List[HistorialResponse])
async def obtener_historial(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el historial completo de cambios de un ticket.
    
    Muestra todos los cambios de estado, asignaciones, modificaciones, etc.
    en orden cronológico inverso (más reciente primero).
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    
    historial = db.query(HistorialTicket).filter(
        HistorialTicket.ticket_id == ticket_id
    ).order_by(HistorialTicket.fecha.desc()).all()
    
    return historial
