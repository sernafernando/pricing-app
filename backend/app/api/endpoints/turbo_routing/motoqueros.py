"""
Endpoints CRUD de motoqueros.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.motoquero import Motoquero
from app.services.permisos_service import verificar_permiso

from ._shared import (
    DeleteResponse,
    MotoqueroCreate,
    MotoqueroResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/turbo/motoqueros", response_model=List[MotoqueroResponse])
def obtener_motoqueros(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    solo_activos: bool = Query(True, description="Solo motoqueros activos"),
):
    """Obtiene la lista de motoqueros."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    query = db.query(Motoquero)
    if solo_activos:
        query = query.filter(Motoquero.activo.is_(True))

    motoqueros = query.order_by(Motoquero.nombre).all()
    return motoqueros


@router.post("/turbo/motoqueros", response_model=MotoqueroResponse)
def crear_motoquero(
    motoquero: MotoqueroCreate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """Crea un nuevo motoquero."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    nuevo_motoquero = Motoquero(**motoquero.model_dump())
    db.add(nuevo_motoquero)
    db.commit()
    db.refresh(nuevo_motoquero)

    return nuevo_motoquero


@router.put("/turbo/motoqueros/{motoquero_id}", response_model=MotoqueroResponse)
def actualizar_motoquero(
    motoquero_id: int,
    motoquero: MotoqueroCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Actualiza un motoquero existente."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    db_motoquero = db.query(Motoquero).filter(Motoquero.id == motoquero_id).first()
    if not db_motoquero:
        raise HTTPException(status_code=404, detail="Motoquero no encontrado")

    for key, value in motoquero.model_dump().items():
        setattr(db_motoquero, key, value)

    db.commit()
    db.refresh(db_motoquero)

    return db_motoquero


@router.delete("/turbo/motoqueros/{motoquero_id}", response_model=DeleteResponse)
def desactivar_motoquero(
    motoquero_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """Desactiva un motoquero (no lo elimina físicamente)."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    db_motoquero = db.query(Motoquero).filter(Motoquero.id == motoquero_id).first()
    if not db_motoquero:
        raise HTTPException(status_code=404, detail="Motoquero no encontrado")

    db_motoquero.activo = False
    db.commit()

    return DeleteResponse(message="Motoquero desactivado", success=True)
