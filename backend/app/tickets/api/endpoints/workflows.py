from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.tickets.models.sector import Sector
from app.tickets.models.workflow import Workflow, EstadoTicket, TransicionEstado
from app.tickets.schemas.workflow_schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    EstadoTicketCreate,
    EstadoTicketResponse,
    TransicionEstadoCreate,
    TransicionEstadoResponse
)

router = APIRouter()


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def obtener_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene un workflow con todos sus estados y transiciones.
    
    Un workflow define el flujo de estados por el que pasa un ticket:
    - Estados disponibles (ej: Abierto, En Revisión, Aprobado, Rechazado)
    - Transiciones permitidas entre estados
    - Validaciones y permisos para cada transición
    - Acciones automáticas al cambiar de estado
    
    Returns:
        Workflow completo con estados ordenados y todas sus transiciones
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")
    
    return workflow


@router.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def crear_workflow(
    workflow_data: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea un nuevo workflow para un sector.
    
    REQUIERE: Permiso de administrador del sistema o del sector.
    
    Un workflow define el flujo de trabajo para un tipo de ticket.
    Después de crear el workflow, debes agregar:
    1. Estados (POST /workflows/{id}/estados)
    2. Transiciones entre estados (POST /workflows/{id}/transiciones)
    
    Ejemplo: Crear workflow "Cambio de Precio" para sector Pricing
    """
    # TODO: Verificar permisos
    # if not current_user.tiene_permiso("tickets.workflows.crear"):
    #     raise HTTPException(status_code=403, detail="No tienes permisos")
    
    # Validar que el sector existe
    sector = db.query(Sector).filter(Sector.id == workflow_data.sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {workflow_data.sector_id} no encontrado")
    
    # Si se marca como default, desmarcar otros workflows del sector
    if workflow_data.es_default:
        db.query(Workflow).filter(
            Workflow.sector_id == workflow_data.sector_id,
            Workflow.es_default == True
        ).update({"es_default": False})
    
    nuevo_workflow = Workflow(
        sector_id=workflow_data.sector_id,
        nombre=workflow_data.nombre,
        descripcion=workflow_data.descripcion,
        es_default=workflow_data.es_default,
        activo=workflow_data.activo
    )
    
    db.add(nuevo_workflow)
    db.commit()
    db.refresh(nuevo_workflow)
    
    return nuevo_workflow


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def actualizar_workflow(
    workflow_id: int,
    workflow_data: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Actualiza un workflow existente.
    
    REQUIERE: Permiso de administrador del sistema o del sector.
    """
    # TODO: Verificar permisos
    
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")
    
    # Actualizar campos
    if workflow_data.nombre is not None:
        workflow.nombre = workflow_data.nombre
    
    if workflow_data.descripcion is not None:
        workflow.descripcion = workflow_data.descripcion
    
    if workflow_data.activo is not None:
        workflow.activo = workflow_data.activo
    
    if workflow_data.es_default is not None:
        if workflow_data.es_default:
            # Desmarcar otros workflows del sector
            db.query(Workflow).filter(
                Workflow.sector_id == workflow.sector_id,
                Workflow.id != workflow.id,
                Workflow.es_default == True
            ).update({"es_default": False})
        workflow.es_default = workflow_data.es_default
    
    db.commit()
    db.refresh(workflow)
    
    return workflow


@router.post("/workflows/{workflow_id}/estados", response_model=EstadoTicketResponse, status_code=201)
async def crear_estado(
    workflow_id: int,
    estado_data: EstadoTicketCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea un nuevo estado para un workflow.
    
    REQUIERE: Permiso de administrador del sistema o del sector.
    
    Un estado representa una etapa en el ciclo de vida del ticket.
    Ejemplos:
    - "Abierto" (es_inicial=True)
    - "En Revisión"
    - "Aprobado" (es_final=True)
    - "Rechazado" (es_final=True)
    
    Flags importantes:
    - es_inicial: Solo debe haber un estado inicial por workflow (se crea automáticamente con este estado)
    - es_final: Estados terminales (cerrado, resuelto, rechazado). Al llegar aquí, el ticket se marca como cerrado
    """
    # TODO: Verificar permisos
    
    # Validar que el workflow existe
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")
    
    # Si se marca como inicial, desmarcar otros estados iniciales del workflow
    if estado_data.es_inicial:
        db.query(EstadoTicket).filter(
            EstadoTicket.workflow_id == workflow_id,
            EstadoTicket.es_inicial == True
        ).update({"es_inicial": False})
    
    # Validar que no exista un estado con el mismo código en este workflow
    estado_existente = db.query(EstadoTicket).filter(
        EstadoTicket.workflow_id == workflow_id,
        EstadoTicket.codigo == estado_data.codigo
    ).first()
    
    if estado_existente:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un estado con código '{estado_data.codigo}' en este workflow"
        )
    
    nuevo_estado = EstadoTicket(
        workflow_id=workflow_id,
        codigo=estado_data.codigo,
        nombre=estado_data.nombre,
        descripcion=estado_data.descripcion,
        orden=estado_data.orden,
        color=estado_data.color,
        es_inicial=estado_data.es_inicial,
        es_final=estado_data.es_final,
        acciones_on_enter=estado_data.acciones_on_enter
    )
    
    db.add(nuevo_estado)
    db.commit()
    db.refresh(nuevo_estado)
    
    return nuevo_estado


@router.post("/workflows/{workflow_id}/transiciones", response_model=TransicionEstadoResponse, status_code=201)
async def crear_transicion(
    workflow_id: int,
    transicion_data: TransicionEstadoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea una nueva transición entre dos estados de un workflow.
    
    REQUIERE: Permiso de administrador del sistema o del sector.
    
    Una transición define:
    - Estado origen y destino
    - Quién puede ejecutarla (permisos, solo asignado, solo creador)
    - Validaciones que deben cumplirse
    - Acciones a ejecutar al realizar la transición
    
    Ejemplo: De "En Revisión" a "Aprobado"
    - requiere_permiso: "tickets.pricing.aprobar"
    - solo_asignado: True (solo quien está asignado puede aprobar)
    - acciones: [{"tipo": "ejecutar_callback", "funcion": "apply_price_change"}]
    """
    # TODO: Verificar permisos
    
    # Validar que el workflow existe
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")
    
    # Validar que ambos estados existen y pertenecen al workflow
    estado_origen = db.query(EstadoTicket).filter(
        EstadoTicket.id == transicion_data.estado_origen_id,
        EstadoTicket.workflow_id == workflow_id
    ).first()
    
    if not estado_origen:
        raise HTTPException(
            status_code=404,
            detail=f"Estado origen {transicion_data.estado_origen_id} no encontrado en workflow {workflow_id}"
        )
    
    estado_destino = db.query(EstadoTicket).filter(
        EstadoTicket.id == transicion_data.estado_destino_id,
        EstadoTicket.workflow_id == workflow_id
    ).first()
    
    if not estado_destino:
        raise HTTPException(
            status_code=404,
            detail=f"Estado destino {transicion_data.estado_destino_id} no encontrado en workflow {workflow_id}"
        )
    
    # Validar que no sea autotransición (mismo estado origen y destino)
    if transicion_data.estado_origen_id == transicion_data.estado_destino_id:
        raise HTTPException(
            status_code=400,
            detail="No se puede crear una transición del mismo estado a sí mismo"
        )
    
    # Validar que no exista ya una transición idéntica
    transicion_existente = db.query(TransicionEstado).filter(
        TransicionEstado.workflow_id == workflow_id,
        TransicionEstado.estado_origen_id == transicion_data.estado_origen_id,
        TransicionEstado.estado_destino_id == transicion_data.estado_destino_id
    ).first()
    
    if transicion_existente:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una transición de '{estado_origen.nombre}' a '{estado_destino.nombre}'"
        )
    
    nueva_transicion = TransicionEstado(
        workflow_id=workflow_id,
        estado_origen_id=transicion_data.estado_origen_id,
        estado_destino_id=transicion_data.estado_destino_id,
        nombre=transicion_data.nombre,
        descripcion=transicion_data.descripcion,
        requiere_permiso=transicion_data.requiere_permiso,
        solo_asignado=transicion_data.solo_asignado,
        solo_creador=transicion_data.solo_creador,
        validaciones=transicion_data.validaciones,
        acciones=transicion_data.acciones
    )
    
    db.add(nueva_transicion)
    db.commit()
    db.refresh(nueva_transicion)
    
    return nueva_transicion
