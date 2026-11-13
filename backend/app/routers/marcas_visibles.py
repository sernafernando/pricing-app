"""Router: the exception list of brands that stay visible without stock (Admin panel).

A brand with no product in stock is hidden from every brand filter and selector
(`app.services.marcas_visibles`), unless it is listed here.

- `GET /marcas-visibles`: the list plus EVERY brand of the catalog with its stock state
  (the admin's picker must offer the hidden ones too).
- `POST /marcas-visibles/excepciones` / `DELETE /marcas-visibles/excepciones/{id}`.

Every route needs `admin.marcas_visibles` (migration `20261114_marcas_visibles_excepciones`),
like `admin.tiendas_oficiales`. The option lists read the table directly: no permission.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.marca_visible_excepcion import MarcaVisibleExcepcion
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.schemas.marcas_visibles import (
    MarcaStockOption,
    MarcaVisibleCreate,
    MarcaVisibleExcepcionResponse,
    MarcasVisiblesResponse,
)
from app.services.marcas_visibles import brand_key
from app.services.permisos_service import PermisosService

PERMISO_ADMIN = "admin.marcas_visibles"

router = APIRouter(prefix="/marcas-visibles", tags=["marcas-visibles"])


def require_admin(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not PermisosService(db).tiene_permiso(current_user, PERMISO_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Falta el permiso {PERMISO_ADMIN}")
    return current_user


def _catalog(db: Session) -> Dict[str, MarcaStockOption]:
    """Every brand of the catalog by key, one spelling each, with whether any of its products has stock."""
    rows = db.execute(
        select(ProductoERP.marca, func.max(ProductoERP.stock))
        .where(ProductoERP.marca.isnot(None))
        .group_by(ProductoERP.marca)
    ).all()
    catalog: Dict[str, MarcaStockOption] = {}
    for marca, max_stock in rows:
        key = brand_key(marca)
        if not key:
            continue
        con_stock = (max_stock or 0) > 0
        known = catalog.get(key)
        if known is None:
            catalog[key] = MarcaStockOption(marca=marca.strip(), con_stock=con_stock, en_excepcion=False)
        elif con_stock:
            known.con_stock = True
    return catalog


def _response(db: Session) -> MarcasVisiblesResponse:
    catalog = _catalog(db)
    excepciones: List[MarcaVisibleExcepcionResponse] = []
    for row in db.query(MarcaVisibleExcepcion).order_by(func.upper(MarcaVisibleExcepcion.marca)).all():
        option = catalog.get(brand_key(row.marca))
        if option is not None:
            option.en_excepcion = True
        excepciones.append(
            MarcaVisibleExcepcionResponse(
                id=row.id,
                marca=row.marca,
                creado_por=row.creado_por.nombre if row.creado_por else None,
                created_at=row.created_at,
                con_stock=bool(option and option.con_stock),
            )
        )
    marcas = sorted(catalog.values(), key=lambda o: brand_key(o.marca))
    return MarcasVisiblesResponse(excepciones=excepciones, marcas=marcas)


@router.get("", response_model=MarcasVisiblesResponse)
def listar_marcas_visibles(
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MarcasVisiblesResponse:
    """The exception list (with who/when and the current stock state) and every brand of the catalog."""
    return _response(db)


@router.post("/excepciones", response_model=MarcaVisibleExcepcionResponse, status_code=status.HTTP_201_CREATED)
def agregar_excepcion(
    body: MarcaVisibleCreate,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MarcaVisibleExcepcionResponse:
    """Keeps a brand visible without stock. 404 for a brand the catalog does not have; 409 when already listed
    (case-insensitive)."""
    key = brand_key(body.marca)
    catalog = _catalog(db)
    option = catalog.get(key)
    if option is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No existe la marca {body.marca}")
    conflict = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=f"La marca {option.marca} ya está en la lista"
    )
    exists = db.execute(
        select(MarcaVisibleExcepcion.id).where(func.upper(func.trim(MarcaVisibleExcepcion.marca)) == key)
    ).first()
    if exists is not None:
        raise conflict
    row = MarcaVisibleExcepcion(marca=option.marca, creado_por_id=admin.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict from exc
    db.refresh(row)
    return MarcaVisibleExcepcionResponse(
        id=row.id,
        marca=row.marca,
        creado_por=admin.nombre,
        created_at=row.created_at,
        con_stock=option.con_stock,
    )


@router.delete("/excepciones/{excepcion_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_excepcion(
    excepcion_id: int,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    """Removes a brand from the list: with no stock it is hidden again."""
    row = db.get(MarcaVisibleExcepcion, excepcion_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Excepción no encontrada")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
