from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.tickets.models.sector import Sector
from app.tickets.models.workflow import Workflow
from app.tickets.schemas.sector_schemas import SectorCreate, SectorUpdate, SectorResponse
from app.tickets.schemas.workflow_schemas import WorkflowResponse

router = APIRouter()


@router.get("/sectores", response_model=List[SectorResponse])
async def listar_sectores(
    activos_solo: bool = True, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Lista todos los sectores disponibles.

    Por defecto solo muestra sectores activos.
    Los sectores definen las áreas que manejan tickets (Pricing, Soporte, Ventas, etc).

    Args:
        activos_solo: Si True, solo devuelve sectores activos

    Returns:
        Lista de sectores con su configuración
    """
    query = db.query(Sector)

    if activos_solo:
        query = query.filter(Sector.activo == True)

    sectores = query.order_by(Sector.nombre).all()

    return sectores


@router.post("/sectores", response_model=SectorResponse, status_code=201)
async def crear_sector(
    sector_data: SectorCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Crea un nuevo sector.

    REQUIERE: Permiso de administrador del sistema.

    Un sector define:
    - Área de la empresa que maneja tickets
    - Configuración de asignación automática
    - Configuración de notificaciones
    - SLAs (tiempos de respuesta/resolución)
    - Campos requeridos en metadata

    Ejemplo: Crear sector "Pricing" para manejar solicitudes de cambio de precio.
    """
    # TODO: Verificar que el usuario sea administrador
    # if not current_user.tiene_permiso("tickets.sectores.crear"):
    #     raise HTTPException(status_code=403, detail="No tienes permisos para crear sectores")

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
async def obtener_sector(
    sector_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene un sector por ID con su configuración completa.

    Returns:
        Sector con toda su configuración de asignación, notificaciones, SLA, etc.
    """
    sector = db.query(Sector).filter(Sector.id == sector_id).first()

    if not sector:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id} no encontrado")

    return sector


@router.patch("/sectores/{sector_id}", response_model=SectorResponse)
async def actualizar_sector(
    sector_id: int,
    sector_data: SectorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Actualiza la configuración de un sector.

    REQUIERE: Permiso de administrador del sistema.

    Permite actualizar:
    - Nombre y descripción
    - Configuración de asignación
    - Configuración de notificaciones
    - SLAs
    - Estado activo/inactivo
    """
    # TODO: Verificar permisos de admin
    # if not current_user.tiene_permiso("tickets.sectores.actualizar"):
    #     raise HTTPException(status_code=403, detail="No tienes permisos")

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
async def listar_workflows_sector(
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
