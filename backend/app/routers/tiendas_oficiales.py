"""Router: official-store names, editable from the Admin panel.

- `GET /tiendas-oficiales`: any authenticated user (display data). Returns
  EVERY store, inactive ones included: a deactivated store still has sales
  that need a name. Callers that build a picker filter on `activa`.
- `POST` / `PUT`: permission `admin.tiendas_oficiales` (migration
  `20261006_ml_tiendas_oficiales`). There is no DELETE on purpose: deactivate
  instead, a removed row would turn the store's history back into "Tienda <id>".
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.usuario import Usuario
from app.schemas.tiendas_oficiales import TiendaOficialCreate, TiendaOficialResponse, TiendaOficialUpdate
from app.services.permisos_service import PermisosService

PERMISO_ADMIN = "admin.tiendas_oficiales"

router = APIRouter(prefix="/tiendas-oficiales", tags=["tiendas-oficiales"])


def require_admin(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not PermisosService(db).tiene_permiso(current_user, PERMISO_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Falta el permiso {PERMISO_ADMIN}")
    return current_user


@router.get("", response_model=List[TiendaOficialResponse])
def listar_tiendas_oficiales(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[MlTiendaOficial]:
    """Lists every official store ordered by `orden`, then name. Any authenticated user."""
    return db.query(MlTiendaOficial).order_by(MlTiendaOficial.orden, MlTiendaOficial.nombre).all()


@router.post("", response_model=TiendaOficialResponse, status_code=status.HTTP_201_CREATED)
def crear_tienda_oficial(
    body: TiendaOficialCreate,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MlTiendaOficial:
    """Registers a store id with its display name. 409 when the id already exists."""
    if db.get(MlTiendaOficial, body.store_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Ya existe la tienda {body.store_id}")
    tienda = MlTiendaOficial(**body.model_dump())
    db.add(tienda)
    db.commit()
    db.refresh(tienda)
    return tienda


@router.put("/{store_id}", response_model=TiendaOficialResponse)
def actualizar_tienda_oficial(
    store_id: int,
    body: TiendaOficialUpdate,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MlTiendaOficial:
    """Updates the fields sent (name, clave, order, active)."""
    tienda = db.get(MlTiendaOficial, store_id)
    if tienda is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("nombre") is None:
        changes.pop("nombre", None)
    for field in ("orden", "activa"):
        if changes.get(field) is None:
            changes.pop(field, None)
    for field, value in changes.items():
        setattr(tienda, field, value)
    db.commit()
    db.refresh(tienda)
    return tienda
