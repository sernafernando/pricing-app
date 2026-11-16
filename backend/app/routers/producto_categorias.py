"""Categories and subcategories ABM (abm-productos S11): list the tree, create own rows, rename (override over GBP),
deactivate, link each one to a Tienda Nube category, suggest that link, and refresh the TN tree.

Reading needs `productos.ver`; every write, the TN suggestion and the TN refresh need `productos.editar_categorias`.
The logic lives in `app.services.producto_categorias`.

The TN suggestion and the TN refresh call the network (the embedder, the TN API). They hold no DB session meanwhile:
the user is authenticated with `get_current_user_transient`, what they need is read in a short `get_background_db()`
session that is closed before the call, and the result is written in a new short session after it.
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_transient, require_permiso
from app.core.database import get_background_db, get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.services import producto_categorias as service
from app.services.permisos_service import PermisosService
from app.services.tn_category_embedding_service import (
    embed_category_text,
    fetch_category_embeddings,
    store_category_embeddings,
)

PERMISO_VER = "productos.ver"
PERMISO_EDITAR = "productos.editar_categorias"

router = APIRouter(prefix="/producto-categorias", tags=["Categorías de productos"])


class Fila(BaseModel):
    id: int
    nombre: Optional[str]
    nombre_gbp: Optional[str]  # None for an own row
    overrideado: bool  # a local name that differs from GBP's
    propia: bool
    activa: bool
    productos: int


class SubcategoriaResponse(Fila):
    categoria_id: int
    tn_category_id: Optional[int]
    tn_categoria: Optional[str]
    tn_category_id_efectiva: Optional[int]  # own link, else the category's
    tn_categoria_efectiva: Optional[str]
    tn_heredada: bool


class CategoriaResponse(Fila):
    tn_category_id: Optional[int]
    tn_categoria: Optional[str]
    vinculo_tn: Literal["completo", "parcial", "ninguno"]
    subcategorias: list[SubcategoriaResponse]


class CrearRequest(BaseModel):
    nombre: str = Field(..., max_length=service.NOMBRE_MAX)


class EditarCategoriaRequest(BaseModel):
    """Only the fields sent change. `nombre: null` goes back to GBP's name; `tn_category_id: null` unlinks."""

    nombre: Optional[str] = Field(None, max_length=service.NOMBRE_MAX)
    activa: Optional[bool] = None
    tn_category_id: Optional[int] = None


class EditarSubcategoriaRequest(EditarCategoriaRequest):
    categoria_id: Optional[int] = None  # only an own subcategory can move


class TnCategoria(BaseModel):
    tn_category_id: int
    category_path: str


class Sugerencia(BaseModel):
    tn_category_id: int
    category_path_text: str
    similarity: float


class SugerenciaResponse(BaseModel):
    sugerencias: list[Sugerencia]
    top: Optional[Sugerencia]


class SyncTnResponse(BaseModel):
    synced: int
    skipped: bool
    reason: Optional[str] = None


def ejecutar(db: Session, accion: Callable[[], Any]) -> Any:
    """Run a write, commit it, and map the master rule errors to 404/422 and an id clash to 409."""
    try:
        result = accion()
    except service.NoEncontrado as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.Invalido as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Two own rows created at the same time took the same next id.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Otro cambio se guardó a la vez; reintentá"
        ) from exc
    db.commit()
    return result


@router.get("", response_model=list[CategoriaResponse])
def listar(
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Every category, active or not, with its subcategories, GBP and local names, product counts and TN links."""
    return service.listar_categorias(db)


@router.post("", response_model=CategoriaResponse, status_code=status.HTTP_201_CREATED)
def crear(
    body: CrearRequest,
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create an own category (id from 1,000,000 up, never sent to GBP)."""
    return ejecutar(db, lambda: service.crear_categoria(db, body.nombre, user.id))


@router.get("/tn-categorias", response_model=list[TnCategoria])
def listar_tn(
    q: str = Query("", description="Texto a buscar en la ruta de la categoría de Tienda Nube"),
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """The Tienda Nube category tree mirrored in `tn_category_embedding`, for the link picker."""
    return service.listar_tn_categorias(db, q)


def _exigir_editar(user: Usuario) -> None:
    """Permission check in its own short session, for the endpoints that must not hold one across a network call."""
    with get_background_db() as db:
        permitido = PermisosService(db).tiene_permiso(user, PERMISO_EDITAR)
    if not permitido:
        raise api_error(403, ErrorCode.INSUFFICIENT_PERMISSIONS, f"Permiso requerido: {PERMISO_EDITAR}")


def _sugerir(user: Usuario, leer_texto: Callable[[Session], tuple[str, Optional[str]]]) -> dict[str, Any]:
    _exigir_editar(user)
    try:
        with get_background_db() as db:
            texto, rama = leer_texto(db)
    except service.NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    embedding = embed_category_text(texto)  # network, no DB session held
    with get_background_db() as db:
        return service.sugerencias_tn(db, embedding, rama)


@router.post("/tn-categorias/sync", response_model=SyncTnResponse)
def sincronizar_tn(user: Usuario = Depends(get_current_user_transient)) -> SyncTnResponse:
    """ "Actualizar desde Tienda Nube": re-runs the existing TN category mirror sync. The TN API and the embedder are
    called with no DB session held; the mirror is written afterwards in a short session."""
    _exigir_editar(user)
    fetched = fetch_category_embeddings()  # network, no DB session held
    with get_background_db() as db:
        result = store_category_embeddings(db, fetched)
    return SyncTnResponse(synced=result["synced"], skipped=result["skipped"], reason=result.get("reason"))


@router.patch("/subcategorias/{subcategoria_id}", response_model=SubcategoriaResponse)
def editar_subcategoria(
    body: EditarSubcategoriaRequest,
    subcategoria_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rename (null = back to GBP), (de)activate, link to TN (null = use the category's) or move an own subcategory."""
    cambios = body.model_dump(include=body.model_fields_set)
    return ejecutar(db, lambda: service.editar_subcategoria(db, subcategoria_id, cambios, user.id))


@router.get("/subcategorias/{subcategoria_id}/sugerencia-tn", response_model=SugerenciaResponse)
def sugerir_tn_subcategoria(
    subcategoria_id: int = Path(..., ge=1),
    user: Usuario = Depends(get_current_user_transient),
) -> dict[str, Any]:
    """Suggested TN categories for "<category> > <subcategory>", kept in the branch of the category's link; empty when
    the embedder is unavailable. No DB session is held during the embedder call."""
    return _sugerir(user, lambda db: service.texto_sugerencia_subcategoria(db, subcategoria_id))


@router.patch("/{categoria_id}", response_model=CategoriaResponse)
def editar(
    body: EditarCategoriaRequest,
    categoria_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rename (null = back to GBP), (de)activate (never deletes) or link to a TN category (null = unlink)."""
    cambios = body.model_dump(include=body.model_fields_set)
    return ejecutar(db, lambda: service.editar_categoria(db, categoria_id, cambios, user.id))


@router.post("/{categoria_id}/subcategorias", response_model=SubcategoriaResponse, status_code=status.HTTP_201_CREATED)
def crear_subcategoria(
    body: CrearRequest,
    categoria_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create an own subcategory under a category."""
    return ejecutar(db, lambda: service.crear_subcategoria(db, categoria_id, body.nombre, user.id))


@router.get("/{categoria_id}/sugerencia-tn", response_model=SugerenciaResponse)
def sugerir_tn(
    categoria_id: int = Path(..., ge=1),
    user: Usuario = Depends(get_current_user_transient),
) -> dict[str, Any]:
    """Suggested TN categories for the category's name (embeddings); empty when the embedder is unavailable. No DB
    session is held during the embedder call."""
    return _sugerir(user, lambda db: service.texto_sugerencia_categoria(db, categoria_id))
