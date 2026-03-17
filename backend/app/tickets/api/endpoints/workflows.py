from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.tickets.models.sector import Sector
from app.tickets.models.workflow import Workflow, EstadoTicket, TransicionEstado
from app.tickets.schemas.workflow_schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    EstadoTicketCreate,
    EstadoTicketUpdate,
    EstadoTicketResponse,
    TransicionEstadoCreate,
    TransicionEstadoUpdate,
    TransicionEstadoResponse,
)

router = APIRouter()


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Raise 403 if user lacks the required permission."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def obtener_workflow(
    workflow_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene un workflow con todos sus estados y transiciones.

    Un workflow define el flujo de estados por el que pasa un ticket:
    - Estados disponibles (ej: Abierto, En Revisión, Aprobado, Rechazado)
    - Transiciones permitidas entre estados
    - Validaciones y permisos para cada transición
    - Acciones automáticas al cambiar de estado

    Requiere: tickets.ver
    """
    _check_permiso(db, current_user, "tickets.ver")

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")

    return workflow


@router.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def crear_workflow(
    workflow_data: WorkflowCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Crea un nuevo workflow para un sector.

    REQUIERE: Permiso de administrador del sistema o del sector.

    Un workflow define el flujo de trabajo para un tipo de ticket.
    Después de crear el workflow, debes agregar:
    1. Estados (POST /workflows/{id}/estados)
    2. Transiciones entre estados (POST /workflows/{id}/transiciones)

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    # Validar que el sector existe
    sector = db.query(Sector).filter(Sector.id == workflow_data.sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {workflow_data.sector_id} no encontrado")

    # Si se marca como default, desmarcar otros workflows del sector
    if workflow_data.es_default:
        db.query(Workflow).filter(Workflow.sector_id == workflow_data.sector_id, Workflow.es_default == True).update(
            {"es_default": False}
        )

    nuevo_workflow = Workflow(
        sector_id=workflow_data.sector_id,
        nombre=workflow_data.nombre,
        descripcion=workflow_data.descripcion,
        es_default=workflow_data.es_default,
        activo=workflow_data.activo,
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
    current_user: Usuario = Depends(get_current_user),
):
    """
    Actualiza un workflow existente.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

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
                Workflow.sector_id == workflow.sector_id, Workflow.id != workflow.id, Workflow.es_default == True
            ).update({"es_default": False})
        workflow.es_default = workflow_data.es_default

    db.commit()
    db.refresh(workflow)

    return workflow


@router.delete("/workflows/{workflow_id}", status_code=204)
async def eliminar_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Elimina un workflow y todos sus estados y transiciones.

    No se puede eliminar si hay tickets activos usando este workflow.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")

    # Verificar que no hay tickets usando estados de este workflow
    from app.tickets.models.ticket import Ticket

    tickets_count = (
        db.query(Ticket)
        .join(EstadoTicket, Ticket.estado_id == EstadoTicket.id)
        .filter(EstadoTicket.workflow_id == workflow_id)
        .count()
    )
    if tickets_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: hay {tickets_count} ticket(s) usando este workflow",
        )

    # Eliminar transiciones, luego estados, luego workflow
    db.query(TransicionEstado).filter(TransicionEstado.workflow_id == workflow_id).delete(synchronize_session="fetch")
    db.query(EstadoTicket).filter(EstadoTicket.workflow_id == workflow_id).delete(synchronize_session="fetch")
    db.delete(workflow)
    db.commit()


@router.post("/workflows/{workflow_id}/estados", response_model=EstadoTicketResponse, status_code=201)
async def crear_estado(
    workflow_id: int,
    estado_data: EstadoTicketCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    # Validar que el workflow existe
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")

    # Si se marca como inicial, desmarcar otros estados iniciales del workflow
    if estado_data.es_inicial:
        db.query(EstadoTicket).filter(EstadoTicket.workflow_id == workflow_id, EstadoTicket.es_inicial == True).update(
            {"es_inicial": False}
        )

    # Validar que no exista un estado con el mismo código en este workflow
    estado_existente = (
        db.query(EstadoTicket)
        .filter(EstadoTicket.workflow_id == workflow_id, EstadoTicket.codigo == estado_data.codigo)
        .first()
    )

    if estado_existente:
        raise HTTPException(
            status_code=400, detail=f"Ya existe un estado con código '{estado_data.codigo}' en este workflow"
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
        acciones_on_enter=estado_data.acciones_on_enter,
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
    current_user: Usuario = Depends(get_current_user),
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

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    # Validar que el workflow existe
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} no encontrado")

    # Validar que ambos estados existen y pertenecen al workflow
    estado_origen = (
        db.query(EstadoTicket)
        .filter(EstadoTicket.id == transicion_data.estado_origen_id, EstadoTicket.workflow_id == workflow_id)
        .first()
    )

    if not estado_origen:
        raise HTTPException(
            status_code=404,
            detail=f"Estado origen {transicion_data.estado_origen_id} no encontrado en workflow {workflow_id}",
        )

    estado_destino = (
        db.query(EstadoTicket)
        .filter(EstadoTicket.id == transicion_data.estado_destino_id, EstadoTicket.workflow_id == workflow_id)
        .first()
    )

    if not estado_destino:
        raise HTTPException(
            status_code=404,
            detail=f"Estado destino {transicion_data.estado_destino_id} no encontrado en workflow {workflow_id}",
        )

    # Validar que no sea autotransición (mismo estado origen y destino)
    if transicion_data.estado_origen_id == transicion_data.estado_destino_id:
        raise HTTPException(status_code=400, detail="No se puede crear una transición del mismo estado a sí mismo")

    # Validar que no exista ya una transición idéntica
    transicion_existente = (
        db.query(TransicionEstado)
        .filter(
            TransicionEstado.workflow_id == workflow_id,
            TransicionEstado.estado_origen_id == transicion_data.estado_origen_id,
            TransicionEstado.estado_destino_id == transicion_data.estado_destino_id,
        )
        .first()
    )

    if transicion_existente:
        raise HTTPException(
            status_code=400, detail=f"Ya existe una transición de '{estado_origen.nombre}' a '{estado_destino.nombre}'"
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
        acciones=transicion_data.acciones,
    )

    db.add(nueva_transicion)
    db.commit()
    db.refresh(nueva_transicion)

    return nueva_transicion


@router.patch("/workflows/{workflow_id}/estados/{estado_id}", response_model=EstadoTicketResponse)
async def actualizar_estado(
    workflow_id: int,
    estado_id: int,
    estado_data: EstadoTicketUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EstadoTicketResponse:
    """
    Actualiza un estado existente de un workflow.

    Permite modificar nombre, descripcion, orden, color y flags (es_inicial, es_final).
    El código del estado NO se puede cambiar (es identificador único).

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    estado = (
        db.query(EstadoTicket).filter(EstadoTicket.id == estado_id, EstadoTicket.workflow_id == workflow_id).first()
    )
    if not estado:
        raise HTTPException(status_code=404, detail=f"Estado {estado_id} no encontrado en workflow {workflow_id}")

    # Si se marca como inicial, desmarcar otros estados iniciales del workflow
    if estado_data.es_inicial is True:
        db.query(EstadoTicket).filter(
            EstadoTicket.workflow_id == workflow_id,
            EstadoTicket.id != estado_id,
            EstadoTicket.es_inicial == True,
        ).update({"es_inicial": False})

    for field, value in estado_data.model_dump(exclude_unset=True).items():
        setattr(estado, field, value)

    db.commit()
    db.refresh(estado)
    return estado


@router.delete("/workflows/{workflow_id}/estados/{estado_id}", status_code=204)
async def eliminar_estado(
    workflow_id: int,
    estado_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Elimina un estado de un workflow.

    No se puede eliminar si hay tickets activos usando este estado.
    También elimina las transiciones asociadas a este estado.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    estado = (
        db.query(EstadoTicket).filter(EstadoTicket.id == estado_id, EstadoTicket.workflow_id == workflow_id).first()
    )
    if not estado:
        raise HTTPException(status_code=404, detail=f"Estado {estado_id} no encontrado en workflow {workflow_id}")

    # Verificar que no hay tickets usando este estado
    from app.tickets.models.ticket import Ticket

    tickets_con_estado = db.query(Ticket).filter(Ticket.estado_id == estado_id).count()
    if tickets_con_estado > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: hay {tickets_con_estado} ticket(s) en este estado",
        )

    # Eliminar transiciones asociadas
    db.query(TransicionEstado).filter(
        (TransicionEstado.estado_origen_id == estado_id) | (TransicionEstado.estado_destino_id == estado_id)
    ).delete(synchronize_session="fetch")

    db.delete(estado)
    db.commit()


@router.patch("/workflows/{workflow_id}/transiciones/{transicion_id}", response_model=TransicionEstadoResponse)
async def actualizar_transicion(
    workflow_id: int,
    transicion_id: int,
    transicion_data: TransicionEstadoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TransicionEstadoResponse:
    """
    Actualiza una transición existente de un workflow.

    Permite modificar nombre, descripcion, permisos y restricciones.
    Los estados origen/destino NO se pueden cambiar (eliminar y recrear).

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    transicion = (
        db.query(TransicionEstado)
        .filter(TransicionEstado.id == transicion_id, TransicionEstado.workflow_id == workflow_id)
        .first()
    )
    if not transicion:
        raise HTTPException(
            status_code=404, detail=f"Transición {transicion_id} no encontrada en workflow {workflow_id}"
        )

    for field, value in transicion_data.model_dump(exclude_unset=True).items():
        setattr(transicion, field, value)

    db.commit()
    db.refresh(transicion)
    return transicion


@router.delete("/workflows/{workflow_id}/transiciones/{transicion_id}", status_code=204)
async def eliminar_transicion(
    workflow_id: int,
    transicion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Elimina una transición de un workflow.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    transicion = (
        db.query(TransicionEstado)
        .filter(TransicionEstado.id == transicion_id, TransicionEstado.workflow_id == workflow_id)
        .first()
    )
    if not transicion:
        raise HTTPException(
            status_code=404, detail=f"Transición {transicion_id} no encontrada en workflow {workflow_id}"
        )

    db.delete(transicion)
    db.commit()
