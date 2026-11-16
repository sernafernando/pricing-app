"""Product specs ABM (abm-specs-productos S6): list, read and edit the technical specs of notebooks and PCs, read and
grow the normalized value lists, and re-pre-load one product.

Reading needs `productos.ver` (anyone who can see products); editing, adding list values and re-pre-loading need
`productos.editar_specs`. The logic lives in `app.services.producto_specs.store`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.producto_specs import store
from app.services.producto_specs.campos import CAMPOS, NOMBRES, POR_NOMBRE, campos_de

PERMISO_VER = "productos.ver"
PERMISO_EDITAR = "productos.editar_specs"

router = APIRouter(prefix="/producto-specs", tags=["Specs de productos"])

Tipo = Literal["notebook", "pc"]


def get_producto_specs_db(db: Session = Depends(get_db)) -> Session:
    """The session the spec tables are read and written through: the request's own. A separate dependency only so a
    test can point those tables at a Postgres store."""
    return db


class CampoInfo(BaseModel):
    nombre: str
    grupo: str
    etiqueta: str
    tipo: str
    unidad: Optional[str]
    minimo: Optional[float]
    maximo: Optional[float]
    decimales: int
    tipos_producto: list[str]


class ValorCampo(BaseModel):
    campo: str
    grupo: str
    etiqueta: str
    valor: Any
    origen: Optional[str]  # ml | erp_name | combo | manual; None: empty and never set by hand


class ProductoSpecsResponse(BaseModel):
    item_id: int
    tipo: str
    codigo: Optional[str]
    descripcion: Optional[str]
    marca: Optional[str]
    campos: list[ValorCampo]
    completos: int
    total: int
    fuente_mla: Optional[str]
    precargado_at: Optional[datetime]
    updated_at: Optional[datetime]
    can_edit: bool


class ListaItem(BaseModel):
    item_id: int
    tipo: str
    codigo: Optional[str]
    descripcion: Optional[str]
    marca: Optional[str]
    stock: Optional[int]
    completos: int
    total: int
    updated_at: Optional[datetime]


class ListaResponse(BaseModel):
    total: int
    items: list[ListaItem]


class EditarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valores: dict[str, Optional[Any]] = Field(min_length=1)


class ValorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor: str = Field(min_length=1, max_length=200)


def _can_edit(db: Session, user: Usuario) -> bool:
    return PermisosService(db).tiene_permiso(user, PERMISO_EDITAR)


def _response(prod: store.Producto, row: Optional[dict], can_edit: bool) -> ProductoSpecsResponse:
    row = row or {}
    origenes = row.get("origenes") or {}
    campos = [
        ValorCampo(
            campo=c.nombre,
            grupo=c.grupo,
            etiqueta=c.etiqueta,
            valor=store.numero_json(row.get(c.nombre)),
            origen=origenes.get(c.nombre),
        )
        for c in campos_de(prod.tipo)
    ]
    return ProductoSpecsResponse(
        item_id=prod.item_id,
        tipo=prod.tipo,
        codigo=prod.codigo,
        descripcion=prod.descripcion,
        marca=prod.marca,
        campos=campos,
        completos=sum(1 for c in campos if c.valor is not None),
        total=len(campos),
        fuente_mla=row.get("fuente_mla"),
        precargado_at=row.get("precargado_at"),
        updated_at=row.get("updated_at"),
        can_edit=can_edit,
    )


def _read(store_db: Session, item_id: int, can_edit: bool) -> ProductoSpecsResponse:
    try:
        prod, row = store.leer(store_db, item_id)
    except store.ProductoNoEncontrado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El producto no es una notebook ni una PC") from None
    return _response(prod, row, can_edit)


def _campo(campo: str) -> str:
    if campo not in POR_NOMBRE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Campo desconocido: {campo}")
    return campo


@router.get("/campos", response_model=list[CampoInfo])
def listar_campos(_user: Usuario = Depends(require_permiso(PERMISO_VER))):
    return [
        CampoInfo(
            nombre=c.nombre,
            grupo=c.grupo,
            etiqueta=c.etiqueta,
            tipo=c.tipo,
            unidad=c.unidad,
            minimo=float(c.minimo) if c.minimo is not None else None,
            maximo=float(c.maximo) if c.maximo is not None else None,
            decimales=c.decimales,
            tipos_producto=[t for t in ("notebook", "pc") if c.aplica(t)],
        )
        for c in CAMPOS
    ]


@router.get("/marcas", response_model=list[str])
def listar_marcas(
    tipo: Optional[Tipo] = None,
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    store_db: Session = Depends(get_producto_specs_db),
):
    return store.marcas(store_db, tipo)


@router.get("/valores/{campo}", response_model=list[Any])
def listar_valores(
    campo: str,
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    store_db: Session = Depends(get_producto_specs_db),
):
    return store.valores(store_db, _campo(campo))


@router.post("/valores/{campo}", status_code=status.HTTP_201_CREATED)
def agregar_valor(
    campo: str,
    body: ValorRequest,
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    store_db: Session = Depends(get_producto_specs_db),
) -> dict:
    try:
        valor = store.agregar_valor(store_db, _campo(campo), body.valor, user.id)
    except store.ValorNoValido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.detalle) from None
    store_db.commit()
    return {"campo": campo, "valor": valor}


@router.get("", response_model=ListaResponse)
def listar(
    tipo: Optional[Tipo] = None,
    marca: Optional[str] = None,
    incompletos: bool = False,
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    store_db: Session = Depends(get_producto_specs_db),
):
    total, rows = store.listar(
        store_db, tipo=tipo, marca=marca, incompletos=incompletos, q=q, limit=limit, offset=offset
    )
    return ListaResponse(total=total, items=[ListaItem(**row) for row in rows])


@router.get("/{item_id}", response_model=ProductoSpecsResponse)
def leer(
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_db),
    store_db: Session = Depends(get_producto_specs_db),
):
    return _read(store_db, item_id, _can_edit(db, user))


@router.put("/{item_id}", response_model=ProductoSpecsResponse)
def editar(
    body: EditarRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    store_db: Session = Depends(get_producto_specs_db),
):
    unknown = sorted(set(body.valores) - set(NOMBRES))
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Campos desconocidos: {', '.join(unknown)}")
    try:
        store.editar(store_db, item_id, body.valores, user.id)
    except store.ProductoNoEncontrado:
        store_db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El producto no es una notebook ni una PC") from None
    except store.ValorNoValido as exc:
        store_db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    store_db.commit()
    return _read(store_db, item_id, True)


@router.post("/{item_id}/precargar", response_model=ProductoSpecsResponse)
def precargar(
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    store_db: Session = Depends(get_producto_specs_db),
):
    """Re-pre-load one product from ML, its ERP name and its combo. Manual fields are kept as they are."""
    try:
        store.producto(store_db, item_id)
    except store.ProductoNoEncontrado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El producto no es una notebook ni una PC") from None
    store.precargar(store_db, [item_id])
    store_db.commit()
    return _read(store_db, item_id, True)
