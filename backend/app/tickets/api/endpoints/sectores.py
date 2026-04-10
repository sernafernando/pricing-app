from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.tickets.models.sector import Sector
from app.tickets.models.sector_usuario import SectorUsuario
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import Workflow
from app.tickets.schemas.sector_schemas import SectorCreate, SectorUpdate, SectorResponse
from app.tickets.schemas.ticket_schemas import (
    SectorUsuarioCreate,
    SectorUsuarioResponse,
    TipoTicketCreate,
    TipoTicketResponse,
    TipoTicketUpdate,
)
from app.tickets.schemas.workflow_schemas import WorkflowResponse


router = APIRouter()


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Raise 403 if user lacks the required permission."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


@router.get("/sectores", response_model=List[SectorResponse])
def listar_sectores(
    activos_solo: bool = True,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[SectorResponse]:
    """
    Lista todos los sectores disponibles.

    Cualquier usuario logueado puede ver sectores (necesario para crear tickets).
    """

    query = db.query(Sector)

    if activos_solo:
        query = query.filter(Sector.activo == True)

    sectores = query.order_by(Sector.nombre).all()

    return sectores


@router.post("/sectores", response_model=SectorResponse, status_code=201)
def crear_sector(
    sector_data: SectorCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SectorResponse:
    """
    Crea un nuevo sector.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    # Validar que no exista un sector con el mismo código
    sector_existente = db.query(Sector).filter(Sector.codigo == sector_data.codigo).first()
    if sector_existente:
        raise HTTPException(status_code=400, detail=f"Ya existe un sector con código '{sector_data.codigo}'")

    nuevo_sector = Sector(
        codigo=sector_data.codigo,
        nombre=sector_data.nombre,
        descripcion=sector_data.descripcion,
        icono=sector_data.icono,
        color=sector_data.color,
        activo=sector_data.activo,
        configuracion=sector_data.configuracion.model_dump(),
    )

    db.add(nuevo_sector)
    db.commit()
    db.refresh(nuevo_sector)

    return nuevo_sector


@router.get("/sectores/{sector_id}", response_model=SectorResponse)
def obtener_sector(sector_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Obtiene un sector por ID con su configuración completa.

    Requiere: tickets.ver
    """
    _check_permiso(db, current_user, "tickets.ver")

    sector = db.query(Sector).filter(Sector.id == sector_id).first()

    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    return sector


@router.patch("/sectores/{sector_id}", response_model=SectorResponse)
def actualizar_sector(
    sector_id: int,
    sector_data: SectorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SectorResponse:
    """
    Actualiza la configuración de un sector.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    sector = db.query(Sector).filter(Sector.id == sector_id).first()

    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    # Actualizar campos
    if sector_data.nombre is not None:
        sector.nombre = sector_data.nombre

    if sector_data.descripcion is not None:
        sector.descripcion = sector_data.descripcion

    if sector_data.icono is not None:
        sector.icono = sector_data.icono

    if sector_data.color is not None:
        sector.color = sector_data.color

    if sector_data.activo is not None:
        sector.activo = sector_data.activo

    if sector_data.configuracion is not None:
        # Merge configuración (no reemplazar completo)
        current_config = sector.configuracion or {}
        new_config = sector_data.configuracion.dict(exclude_unset=True)
        current_config.update(new_config)
        sector.configuracion = current_config

    db.commit()
    db.refresh(sector)

    return sector


@router.get("/sectores/{sector_id}/workflows", response_model=List[WorkflowResponse])
def listar_workflows_sector(
    sector_id: int,
    activos_solo: bool = True,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista los workflows de un sector.

    Un sector puede tener múltiples workflows para diferentes tipos de tickets.
    Por ejemplo, Pricing puede tener:
    - Workflow "Cambio de Precio"
    - Workflow "Activación de Rebate"

    Args:
        sector_id: ID del sector
        activos_solo: Si True, solo devuelve workflows activos

    Returns:
        Lista de workflows con sus estados y transiciones
    """
    sector = db.query(Sector).filter(Sector.id == sector_id).first()

    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    query = db.query(Workflow).filter(Workflow.sector_id == sector_id)

    if activos_solo:
        query = query.filter(Workflow.activo == True)

    workflows = query.order_by(Workflow.es_default.desc(), Workflow.nombre).all()

    return workflows


# ── Sector-User management endpoints ─────────────────────────────


@router.get("/sectores/{sector_id}/usuarios", response_model=List[SectorUsuarioResponse])
def listar_usuarios_sector(
    sector_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[SectorUsuarioResponse]:
    """
    Lista los usuarios asignados a un sector.

    Requiere: tickets.ver
    """
    _check_permiso(db, current_user, "tickets.ver")

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    usuarios = db.query(SectorUsuario).filter(SectorUsuario.sector_id == sector_id, SectorUsuario.activo == True).all()

    return usuarios


@router.post("/sectores/{sector_id}/usuarios", response_model=SectorUsuarioResponse, status_code=201)
def agregar_usuario_sector(
    sector_id: int,
    data: SectorUsuarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SectorUsuarioResponse:
    """
    Agrega un usuario a un sector.

    Si ya existe la relación pero está inactiva, la reactiva.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    usuario = db.query(Usuario).filter(Usuario.id == data.usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail=f"Usuario {data.usuario_id} no encontrado")

    # Check if already exists (possibly inactive)
    existente = (
        db.query(SectorUsuario)
        .filter(SectorUsuario.sector_id == sector_id, SectorUsuario.usuario_id == data.usuario_id)
        .first()
    )

    if existente:
        if existente.activo:
            raise HTTPException(status_code=400, detail="El usuario ya pertenece a este sector")
        existente.activo = True
        db.commit()
        db.refresh(existente)
        return existente

    nuevo = SectorUsuario(
        sector_id=sector_id,
        usuario_id=data.usuario_id,
        activo=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.delete("/sectores/{sector_id}/usuarios/{usuario_id}", status_code=204)
def remover_usuario_sector(
    sector_id: int,
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Remueve un usuario de un sector (soft-delete: activo=False).

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    relacion = (
        db.query(SectorUsuario)
        .filter(
            SectorUsuario.sector_id == sector_id,
            SectorUsuario.usuario_id == usuario_id,
            SectorUsuario.activo == True,
        )
        .first()
    )

    if not relacion:
        raise HTTPException(status_code=404, detail="Relación sector-usuario no encontrada")

    relacion.activo = False
    db.commit()


@router.get("/sectores/{sector_id}/tipos-ticket", response_model=List[TipoTicketResponse])
def listar_tipos_ticket_sector(
    sector_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[TipoTicketResponse]:
    """
    Lista los tipos de ticket disponibles para un sector.

    Cada tipo incluye schema_campos para generar formularios dinámicos.

    Cualquier usuario logueado puede ver los tipos (necesario para crear tickets).
    """

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    tipos = db.query(TipoTicket).filter(TipoTicket.sector_id == sector_id).order_by(TipoTicket.nombre).all()

    return tipos


@router.post("/sectores/{sector_id}/tipos-ticket", response_model=TipoTicketResponse, status_code=201)
def crear_tipo_ticket(
    sector_id: int,
    tipo_data: TipoTicketCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TipoTicketResponse:
    """
    Crea un nuevo tipo de ticket para un sector.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    # Verificar código único dentro del sector
    existente = (
        db.query(TipoTicket).filter(TipoTicket.sector_id == sector_id, TipoTicket.codigo == tipo_data.codigo).first()
    )
    if existente:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un tipo de ticket con código '{tipo_data.codigo}' en este sector",
        )

    # Validar workflow_id si se proporcionó
    if tipo_data.workflow_id:
        workflow = (
            db.query(Workflow).filter(Workflow.id == tipo_data.workflow_id, Workflow.sector_id == sector_id).first()
        )
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow no encontrado para este sector")

    nuevo_tipo = TipoTicket(
        sector_id=sector_id,
        codigo=tipo_data.codigo,
        nombre=tipo_data.nombre,
        descripcion=tipo_data.descripcion,
        icono=tipo_data.icono,
        color=tipo_data.color,
        workflow_id=tipo_data.workflow_id,
        schema_campos=tipo_data.schema_campos,
    )
    db.add(nuevo_tipo)
    db.commit()
    db.refresh(nuevo_tipo)

    return nuevo_tipo


@router.patch("/sectores/{sector_id}/tipos-ticket/{tipo_id}", response_model=TipoTicketResponse)
def actualizar_tipo_ticket(
    sector_id: int,
    tipo_id: int,
    tipo_data: TipoTicketUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TipoTicketResponse:
    """
    Actualiza un tipo de ticket existente.

    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    tipo = db.query(TipoTicket).filter(TipoTicket.id == tipo_id, TipoTicket.sector_id == sector_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de ticket no encontrado en este sector")

    if tipo_data.nombre is not None:
        tipo.nombre = tipo_data.nombre
    if tipo_data.descripcion is not None:
        tipo.descripcion = tipo_data.descripcion
    if tipo_data.icono is not None:
        tipo.icono = tipo_data.icono
    if tipo_data.color is not None:
        tipo.color = tipo_data.color
    if tipo_data.workflow_id is not None:
        workflow = (
            db.query(Workflow).filter(Workflow.id == tipo_data.workflow_id, Workflow.sector_id == sector_id).first()
        )
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow no encontrado para este sector")
        tipo.workflow_id = tipo_data.workflow_id
    if tipo_data.schema_campos is not None:
        tipo.schema_campos = tipo_data.schema_campos

    db.commit()
    db.refresh(tipo)

    return tipo


@router.delete("/sectores/{sector_id}/tipos-ticket/{tipo_id}", status_code=204)
def eliminar_tipo_ticket(
    sector_id: int,
    tipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Elimina un tipo de ticket.

    No se puede eliminar si tiene tickets asociados.
    Requiere: tickets.admin
    """
    _check_permiso(db, current_user, "tickets.admin")

    tipo = db.query(TipoTicket).filter(TipoTicket.id == tipo_id, TipoTicket.sector_id == sector_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de ticket no encontrado en este sector")

    # Verificar que no tenga tickets asociados
    from app.tickets.models.ticket import Ticket

    tickets_count = db.query(Ticket).filter(Ticket.tipo_ticket_id == tipo_id).count()
    if tickets_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: tiene {tickets_count} ticket(s) asociado(s)",
        )

    db.delete(tipo)
    db.commit()
