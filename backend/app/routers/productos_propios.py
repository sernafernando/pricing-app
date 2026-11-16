"""Our own product (Publicaciones ML T6, T7): read and edit the SKU and EAN of an ERP product, keyed by its `item_id`,
and copy its data (title, description, pictures, attributes) from one of its publications. Also the product master
(abm-productos T4: `/maestro`): GBP data with overrides, texts and units per box, permissions described there.

Reading needs the Publicaciones ML screen's permission (`productos.ver` OR `ml_ops.ver`, `PERMISOS_PUBLICACIONES_ML`:
its product panel always reads it); editing and choosing the source need `ml_publicaciones.editar_producto`. The
values are computed in `producto_propio_service`; only what an operator types or copies is stored.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import require_algun_permiso, require_permiso
from app.core.constants import PERMISOS_PUBLICACIONES_ML
from app.core.database import get_db
from app.models.producto_propio import MAX_CODE_LENGTH
from app.models.usuario import Usuario
from app.schemas.publication_data import (
    MAX_ATRIBUTO_VALUE_LENGTH,
    MAX_DESCRIPCION_LENGTH,
    MAX_TITULO_LENGTH,
    NonBlank,
)
from app.services import producto_maestro
from app.services.permisos_service import PermisosService
from app.services.ml_publications import admin
from app.services.ml_publications.publication_data import DatosNoValidos
from app.services.producto_propio_service import (
    FuenteNoValida,
    SinFuente,
    ProductoPropioView,
    choose_source,
    edit_datos,
    read_producto_propio,
    save_producto_propio,
)

PERMISO_EDITAR = "ml_publicaciones.editar_producto"

router = APIRouter(prefix="/productos-propios", tags=["Productos propios"])

# Trimmed before the length check: surrounding spaces typed in the panel do not count against the column width.
Code = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_CODE_LENGTH)]]


def get_productos_propios_db(db: Session = Depends(get_db)) -> Session:
    """The session the product tables are read and written through: the request's own (same database as the
    permission check). A separate dependency only so a test can point those tables elsewhere."""
    return db


class DatosCopiadosResponse(BaseModel):
    fuente_mla: str
    titulo: Optional[str]
    descripcion: Optional[str]
    fotos: list[dict[str, Any]]
    atributos: list[dict[str, Any]]
    copiado_at: Optional[datetime]


class ProductoPropioResponse(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    ean: Optional[str]
    ean_manual: bool
    sku: Optional[str]
    sku_manual: bool
    sku_candidatos: list[str]
    datos: Optional[DatosCopiadosResponse]  # None until a source publication is chosen
    can_edit: bool


class FuenteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mla: Annotated[str, StringConstraints(pattern=admin.ITEM_ID_PATTERN)]


class AtributoEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonBlank
    value_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ATRIBUTO_VALUE_LENGTH)
    ]


class DatosRequest(BaseModel):
    """Every field is required: the edit is the whole copy, not a patch."""

    model_config = ConfigDict(extra="forbid")

    titulo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITULO_LENGTH)]
    descripcion: Optional[Annotated[str, StringConstraints(max_length=MAX_DESCRIPCION_LENGTH)]]
    fotos: list[NonBlank]  # copied picture ids, in the new order
    atributos: list[AtributoEdit]  # copied attributes with their new value


class ProductoPropioRequest(BaseModel):
    """Both values are required: null or blank drops the manual one (back to the computed value)."""

    model_config = ConfigDict(extra="forbid")

    sku: Code
    ean: Code


def _not_found(item_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No se encontró el producto {item_id}")


def _response(view: ProductoPropioView, can_edit: bool) -> ProductoPropioResponse:
    return ProductoPropioResponse(**asdict(view), can_edit=can_edit)


# ---------------------------------------------------------------------------------------------------------------
# Product master (abm-productos T4): GBP data, overrides, texts and units per box of every ERP product.
# Reading needs `productos.ver`; editing `productos.editar_maestro`; units per box also `gestion_full.depositos`
# (the permission Gestión Full edits them with). Registered before `/{item_id}` so `/maestro` is not read as an id.
# ---------------------------------------------------------------------------------------------------------------

PERMISO_VER_MAESTRO = "productos.ver"
PERMISO_EDITAR_MAESTRO = "productos.editar_maestro"
PERMISO_UNIDADES_CAJA = "gestion_full.depositos"

FuenteTexto = Literal["ml", "tn", "gbp", "nombre", "propio"]


class MaestroListaItem(BaseModel):
    item_id: int
    codigo: Optional[str]
    ean: Optional[str]
    nombre: Optional[str]
    marca: Optional[str]
    stock: Optional[int]
    tipo: Optional[str]  # notebook / pc: the products with specs
    specs_completos: Optional[int]
    specs_total: Optional[int]


class MaestroListaResponse(BaseModel):
    total: int
    items: list[MaestroListaItem]


class MaestroResponse(BaseModel):
    item_id: int
    codigo: Optional[str]
    tipo_specs: Optional[str]
    campos: dict[str, dict[str, Any]]  # {valor, gbp, overrideado} (+ nombre, gbp_nombre for marca / categorías)
    unidades_caja: Optional[int]
    textos: dict[str, dict[str, Any]]  # {fuente, elegida, valor, fuentes}
    mla_ganadora: Optional[str]
    lectura: dict[str, Any]
    can_edit: bool
    can_edit_unidades: bool


class TextoEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuente: Optional[FuenteTexto]  # null: back to the default source
    texto: Optional[Annotated[str, StringConstraints(max_length=MAX_DESCRIPCION_LENGTH)]] = None  # for `propio`


Medida = Optional[Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]]


class MaestroRequest(BaseModel):
    """A patch: only the fields sent change; null goes back to the GBP value."""

    model_config = ConfigDict(extra="forbid")

    nombre: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None
    ean: Code = None
    codigo_fabricante: Code = None
    marca_id: Optional[Annotated[int, Field(ge=1)]] = None
    categoria_id: Optional[Annotated[int, Field(ge=1)]] = None
    subcategoria_id: Optional[Annotated[int, Field(ge=1)]] = None
    garantia_dias: Optional[Annotated[int, Field(ge=0, le=3650)]] = None
    peso_g: Optional[Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]] = None
    ancho_cm: Medida = None
    largo_cm: Medida = None
    alto_cm: Medida = None
    unidades_caja: Optional[Annotated[int, Field(ge=1)]] = None
    textos: dict[Literal["titulo_ml", "titulo_web", "descripcion_ml", "descripcion_web"], TextoEdit] = {}


def _maestro(body: dict, auth_db: Session, user: Usuario) -> MaestroResponse:
    permisos = PermisosService(auth_db)
    return MaestroResponse(
        **body,
        can_edit=permisos.tiene_permiso(user, PERMISO_EDITAR_MAESTRO),
        can_edit_unidades=permisos.tiene_permiso(user, PERMISO_UNIDADES_CAJA),
    )


@router.get("/maestro", response_model=MaestroListaResponse)
def listar_maestro(
    tipo: Optional[Literal["notebook", "pc"]] = None,
    marca: Optional[str] = Query(None, max_length=100),
    q: Optional[str] = Query(None, max_length=200),
    incompletos: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: Usuario = Depends(require_permiso(PERMISO_VER_MAESTRO)),
    db: Session = Depends(get_productos_propios_db),
) -> MaestroListaResponse:
    """Every ERP product with its effective name, EAN and brand, ordered by stock; notebooks and PCs with how many
    spec fields are complete (`incompletos`: some still empty)."""
    total, rows = producto_maestro.listar(
        db, tipo=tipo, marca=marca, q=q, incompletos=incompletos, limit=limit, offset=offset
    )
    return MaestroListaResponse(total=total, items=[MaestroListaItem(**row) for row in rows])


@router.get("/{item_id}/maestro", response_model=MaestroResponse)
def get_maestro(
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_VER_MAESTRO)),
    auth_db: Session = Depends(get_db),
    db: Session = Depends(get_productos_propios_db),
) -> MaestroResponse:
    """The product's GBP data with its overrides, texts and their sources, units per box and read-only data."""
    body = producto_maestro.leer(db, item_id)
    if body is None:
        raise _not_found(item_id)
    return _maestro(body, auth_db, user)


@router.patch("/{item_id}/maestro", response_model=MaestroResponse)
def patch_maestro(
    body: MaestroRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR_MAESTRO)),
    auth_db: Session = Depends(get_db),
    db: Session = Depends(get_productos_propios_db),
) -> MaestroResponse:
    """Override GBP fields (null goes back to GBP), choose each text's source or write an own text, and set units
    per box (null clears them). Nothing is written to GBP. 422 for an unknown brand or category, a subcategory of
    another category or a blank own text; 403 for units per box without `gestion_full.depositos`."""
    sent = body.model_fields_set
    cambios = {campo: getattr(body, campo) for campo in sent if campo in producto_maestro.OVERRIDES}
    unidades: Any = producto_maestro.SIN_CAMBIO
    if "unidades_caja" in sent:
        if not PermisosService(auth_db).tiene_permiso(user, PERMISO_UNIDADES_CAJA):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Editar unidades por caja requiere el permiso de Depósitos")
        unidades = body.unidades_caja
    textos = {clave: (edit.fuente, edit.texto) for clave, edit in body.textos.items()}
    try:
        result = producto_maestro.guardar(db, item_id, cambios, textos, user, unidades)
    except producto_maestro.DatoNoValido as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if result is None:
        raise _not_found(item_id)
    return _maestro(result, auth_db, user)


@router.get("/{item_id}", response_model=ProductoPropioResponse)
def get_producto_propio(
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_algun_permiso(PERMISOS_PUBLICACIONES_ML)),
    auth_db: Session = Depends(get_db),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """The product's SKU and EAN, which of them are manual, the SKUs its publications carry, and whether the user
    may edit them."""
    view = read_producto_propio(db, item_id)
    if view is None:
        raise _not_found(item_id)
    return _response(view, PermisosService(auth_db).tiene_permiso(user, PERMISO_EDITAR))


@router.put("/{item_id}", response_model=ProductoPropioResponse)
def put_producto_propio(
    body: ProductoPropioRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """Set the manual SKU and EAN (null or blank drops each one) and answer the values the panel now shows."""
    view = save_producto_propio(db, item_id, body.sku, body.ean, user.id)
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)


@router.post("/{item_id}/fuente", response_model=ProductoPropioResponse)
def post_fuente(
    body: FuenteRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """Copy the title, description, pictures and attributes of `mla` onto the product, replacing an earlier copy.
    409 when `mla` is not a live publication linked to the product."""
    try:
        view = choose_source(db, item_id, body.mla, user.id)
    except FuenteNoValida as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)


@router.put("/{item_id}/datos", response_model=ProductoPropioResponse)
def put_datos(
    body: DatosRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """Save the edited copy: title, description, the copied pictures kept (in order) and the copied attributes kept
    (with their values). 409 before a source is chosen; 422 for a picture or attribute that was not copied."""
    try:
        view = edit_datos(
            db,
            item_id,
            body.titulo,
            body.descripcion,
            body.fotos,
            [(atributo.id, atributo.value_name) for atributo in body.atributos],
            user.id,
        )
    except SinFuente as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DatosNoValidos as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)
