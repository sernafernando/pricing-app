"""Router: Publicaciones ML column layouts and presets (S2 storage, S3, S4).

- `GET /ml-publications/layouts/{vista}`: the caller's layout of that view, `{columns, preset_activo_id}`; nulls
  when nothing is saved, and a remembered preset the caller can no longer see reads as null.
- `PUT /ml-publications/layouts/{vista}`: saves it (one row per user and view). `preset_activo_id` must be a preset
  of the same view the caller can see (404 otherwise). "Restablecer" = `{columns: null, preset_activo_id: null}`.
- `GET /ml-publications/presets?vista=X`: the caller's personal presets plus every shared one of that view, shared
  first, then by name. `editable` = own personal, or shared and the caller has `ml_publicaciones.presets_compartidos`.
- `POST /ml-publications/presets` (201), `PUT /ml-publications/presets/{id}`, `DELETE /ml-publications/presets/{id}`
  (204). Another user's personal preset does not exist for the caller (404); a shared one is written only with
  `ml_publicaciones.presets_compartidos` (403). A name already used in that view by the same owner (personal) or by
  another shared preset, case-insensitive, is 409; "Predeterminado" is the built-in preset's name, also 409.
  Deleting a preset nulls the layouts remembering it.

Access to every endpoint is the screen's (`PERMISOS_PUBLICACIONES_ML`); the `auditoria` view also needs
`ml_publicaciones.ver_auditoria_stock` (403). Payloads are validated by `app.schemas.ml_publicaciones_presets`
(422, nothing stored) and kept opaquely: the backend never interprets the saved filters.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_algun_permiso
from app.core.constants import PERMISOS_PUBLICACIONES_ML
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.ml_publicaciones_preset import MlPublicacionesLayout, MlPublicacionesPreset
from app.models.usuario import Usuario
from app.schemas.ml_publicaciones_presets import (
    LayoutBody,
    PresetCreate,
    PresetItem,
    PresetUpdate,
    Vista,
)
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/ml-publications", tags=["ml-publications-presets"])

PERMISO_PRESETS_COMPARTIDOS = "ml_publicaciones.presets_compartidos"
PERMISO_AUDITORIA_STOCK = "ml_publicaciones.ver_auditoria_stock"
VISTA_AUDITORIA = "auditoria"
NOMBRE_RESERVADO = "predeterminado"  # the built-in preset (the view's defaults), lives only in the frontend

screen_user = require_algun_permiso(PERMISOS_PUBLICACIONES_ML)


def _tiene(db: Session, user: Usuario, codigo: str) -> bool:
    return PermisosService(db).tiene_permiso(user, codigo)


def _check_vista(db: Session, user: Usuario, vista: str) -> None:
    """The Auditoría view, its layout and its presets need the view's own permission."""
    if vista == VISTA_AUDITORIA and not _tiene(db, user, PERMISO_AUDITORIA_STOCK):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Permiso requerido: {PERMISO_AUDITORIA_STOCK}",
        )


def _check_compartidos(db: Session, user: Usuario) -> None:
    if not _tiene(db, user, PERMISO_PRESETS_COMPARTIDOS):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Permiso requerido: {PERMISO_PRESETS_COMPARTIDOS}",
        )


def _is_visible(preset: MlPublicacionesPreset, user: Usuario) -> bool:
    """Shared presets are everyone's; a personal one only its owner's."""
    return preset.usuario_id is None or preset.usuario_id == user.id


def _not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Preset no encontrado")


def _visible_preset(db: Session, preset_id: int, user: Usuario) -> MlPublicacionesPreset:
    """The preset if the caller can see it; 404 when it does not exist or is another user's personal one."""
    preset = db.get(MlPublicacionesPreset, preset_id)
    if preset is None or not _is_visible(preset, user):
        raise _not_found()
    return preset


def _writable_preset(db: Session, preset_id: int, user: Usuario) -> MlPublicacionesPreset:
    """The preset if the caller may write it: visible (404), its view's permission and, if shared, the shared
    presets' permission (403)."""
    preset = _visible_preset(db, preset_id, user)
    _check_vista(db, user, preset.vista)
    if preset.usuario_id is None:
        _check_compartidos(db, user)
    return preset


def _name_taken() -> Exception:
    return api_error(status.HTTP_409_CONFLICT, ErrorCode.ALREADY_EXISTS, "Ya existe un preset con ese nombre")


def _check_nombre(
    db: Session, *, owner_id: Optional[int], vista: str, nombre: str, exclude_id: Optional[int] = None
) -> None:
    """409 when the name is the built-in one or already used, case-insensitive, by the same owner in that view
    (personal) or by another shared preset of that view (shared)."""
    if nombre.lower() == NOMBRE_RESERVADO:
        raise api_error(status.HTTP_409_CONFLICT, ErrorCode.ALREADY_EXISTS, "El nombre 'Predeterminado' está reservado")
    owner = MlPublicacionesPreset.usuario_id
    query = select(MlPublicacionesPreset.id).where(
        MlPublicacionesPreset.vista == vista,
        func.lower(MlPublicacionesPreset.nombre) == nombre.lower(),
        owner.is_(None) if owner_id is None else owner == owner_id,
    )
    if exclude_id is not None:
        query = query.where(MlPublicacionesPreset.id != exclude_id)
    if db.execute(query.limit(1)).first() is not None:
        raise _name_taken()


def _commit(db: Session) -> None:
    """Commit; a unique-name race lost to a concurrent write is the same 409."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None


def _item(preset: MlPublicacionesPreset, user: Usuario, puede_compartidos: bool) -> PresetItem:
    compartido = preset.usuario_id is None
    return PresetItem(
        id=preset.id,
        vista=preset.vista,
        nombre=preset.nombre,
        compartido=compartido,
        editable=puede_compartidos if compartido else preset.usuario_id == user.id,
        payload=preset.payload,
        updated_at=preset.updated_at,
    )


def _layout_row(db: Session, user: Usuario, vista: str) -> Optional[MlPublicacionesLayout]:
    return db.execute(
        select(MlPublicacionesLayout).where(
            MlPublicacionesLayout.usuario_id == user.id, MlPublicacionesLayout.vista == vista
        )
    ).scalar_one_or_none()


# ----------------------------------------------------------------------------------------------------------------
# Layouts
# ----------------------------------------------------------------------------------------------------------------


@router.get("/layouts/{vista}", response_model=LayoutBody)
def get_layout(vista: Vista, db: Session = Depends(get_db), user: Usuario = Depends(screen_user)) -> LayoutBody:
    """The caller's saved layout of `vista`: nulls when nothing is saved; a remembered preset that is gone or no
    longer visible to the caller reads as null."""
    _check_vista(db, user, vista)
    row = _layout_row(db, user, vista)
    if row is None:
        return LayoutBody()
    preset_id = row.preset_activo_id
    if preset_id is not None:
        preset = db.get(MlPublicacionesPreset, preset_id)
        if preset is None or preset.vista != vista or not _is_visible(preset, user):
            preset_id = None
    return LayoutBody(columns=row.column_layout, preset_activo_id=preset_id)


@router.put("/layouts/{vista}", response_model=LayoutBody)
def put_layout(
    vista: Vista, body: LayoutBody, db: Session = Depends(get_db), user: Usuario = Depends(screen_user)
) -> LayoutBody:
    """Save the caller's layout of `vista` (upsert). `preset_activo_id` must be a preset of `vista` the caller can
    see (404 otherwise). `{columns: null, preset_activo_id: null}` returns the view to its defaults."""
    _check_vista(db, user, vista)
    if body.preset_activo_id is not None:
        preset = _visible_preset(db, body.preset_activo_id, user)
        if preset.vista != vista:
            raise _not_found()
    column_layout = body.columns.model_dump() if body.columns is not None else None
    # Two concurrent requests can break the save at commit: another first save of this view inserted the row
    # (unique usuario + vista) -> save again as an update; or the remembered preset was deleted after the check
    # above (FK) -> 404, storing nothing, so no layout ever points at a missing preset.
    for _attempt in range(2):
        row = _layout_row(db, user, vista)
        if row is None:
            row = MlPublicacionesLayout(usuario_id=user.id, vista=vista)
            db.add(row)
        row.column_layout = column_layout
        row.preset_activo_id = body.preset_activo_id
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if body.preset_activo_id is not None and db.get(MlPublicacionesPreset, body.preset_activo_id) is None:
                raise _not_found() from None
    else:
        raise api_error(status.HTTP_409_CONFLICT, ErrorCode.ALREADY_EXISTS, "El layout cambió mientras se guardaba")
    return LayoutBody(columns=body.columns, preset_activo_id=body.preset_activo_id)


# ----------------------------------------------------------------------------------------------------------------
# Presets
# ----------------------------------------------------------------------------------------------------------------


@router.get("/presets", response_model=list[PresetItem])
def list_presets(
    vista: Vista = Query(...), db: Session = Depends(get_db), user: Usuario = Depends(screen_user)
) -> list[PresetItem]:
    """The caller's personal presets of `vista` plus every shared one; shared first, then by name."""
    _check_vista(db, user, vista)
    owner = MlPublicacionesPreset.usuario_id
    presets = (
        db.execute(
            select(MlPublicacionesPreset)
            .where(MlPublicacionesPreset.vista == vista, (owner.is_(None)) | (owner == user.id))
            .order_by(
                case((owner.is_(None), 0), else_=1),
                func.lower(MlPublicacionesPreset.nombre),
                MlPublicacionesPreset.id,
            )
        )
        .scalars()
        .all()
    )
    puede_compartidos = _tiene(db, user, PERMISO_PRESETS_COMPARTIDOS)
    return [_item(preset, user, puede_compartidos) for preset in presets]


@router.post("/presets", response_model=PresetItem, status_code=status.HTTP_201_CREATED)
def create_preset(
    body: PresetCreate, db: Session = Depends(get_db), user: Usuario = Depends(screen_user)
) -> PresetItem:
    """Create a personal preset of the caller, or a shared one (`compartido`, needs the shared presets' permission)."""
    _check_vista(db, user, body.vista)
    if body.compartido:
        _check_compartidos(db, user)
    owner_id = None if body.compartido else user.id
    _check_nombre(db, owner_id=owner_id, vista=body.vista, nombre=body.nombre)
    preset = MlPublicacionesPreset(
        usuario_id=owner_id,
        vista=body.vista,
        nombre=body.nombre,
        payload=body.payload.model_dump(),
        created_by=user.id,
    )
    db.add(preset)
    _commit(db)
    db.refresh(preset)
    return _item(preset, user, body.compartido)


@router.put("/presets/{preset_id}", response_model=PresetItem)
def update_preset(
    preset_id: int, body: PresetUpdate, db: Session = Depends(get_db), user: Usuario = Depends(screen_user)
) -> PresetItem:
    """Rename and/or overwrite a preset the caller may write (404 another user's personal one, 403 a shared one
    without the permission, 409 a taken or reserved name)."""
    preset = _writable_preset(db, preset_id, user)
    if body.nombre is not None:
        _check_nombre(db, owner_id=preset.usuario_id, vista=preset.vista, nombre=body.nombre, exclude_id=preset.id)
        preset.nombre = body.nombre
    if body.payload is not None:
        preset.payload = body.payload.model_dump()
    _commit(db)
    db.refresh(preset)
    return _item(preset, user, preset.usuario_id is None)


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(preset_id: int, db: Session = Depends(get_db), user: Usuario = Depends(screen_user)) -> Response:
    """Delete a preset the caller may write (same 404/403 as the update); the layouts remembering it forget it."""
    preset = _writable_preset(db, preset_id, user)
    # The FK is ON DELETE SET NULL too; done here as well so the session never holds a stale reference.
    db.execute(
        update(MlPublicacionesLayout)
        .where(MlPublicacionesLayout.preset_activo_id == preset.id)
        .values(preset_activo_id=None)
        .execution_options(synchronize_session="fetch")
    )
    db.delete(preset)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
