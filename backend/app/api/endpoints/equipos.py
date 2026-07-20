"""
Equipos (teams) — CRUD and membership management.

Governance model (hybrid):
- Any authenticated user may create a team and becomes its admin.
- Membership/admin status is DATA stored in `equipo_miembro.rol`. A user with
  `rol='admin'` on team T may manage T's membership, rename T, or delete T.
  A `rol='miembro'` user cannot.
- The singleton global ("U") team has IMPLICIT membership — every user is
  considered a member for read/write-color purposes (see
  `productos_shared.puede_escribir_layer`), but there are no explicit
  `EquipoMiembro` rows for it. Any attempt to add/remove/list explicit
  members, rename, or delete the global team via this router is rejected.
  The `equipos.gestionar_global` permission (seeded in the PR1 migration) is
  reserved for future admin actions scoped to the global team; today it does
  not gate anything actionable here (spec assumption A3).
- Deleting a team is blocked while it still has `ProductoColor` rows — the
  caller must be told to reassign/clear those first, avoiding silent data
  loss.
- A team's last admin cannot be removed or demoted (would orphan the team).
  Deleting the team entirely is still allowed for its (last) admin, since
  that is an explicit, intentional action for the whole team.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.endpoints.productos_shared import get_global_equipo_id
from app.core.database import get_db
from app.models.equipo import Equipo, EquipoMiembro, ProductoColor, RolEquipo
from app.models.usuario import Usuario

router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================


class EquipoCreateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)


class EquipoUpdateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)


class EquipoResponse(BaseModel):
    id: int
    nombre: str
    es_global: bool

    model_config = ConfigDict(from_attributes=True)


class MiembroAddRequest(BaseModel):
    usuario_id: int
    rol: RolEquipo = RolEquipo.MIEMBRO


class MiembroUpdateRequest(BaseModel):
    rol: RolEquipo


class MiembroResponse(BaseModel):
    id: int
    equipo_id: int
    usuario_id: int
    rol: str

    model_config = ConfigDict(from_attributes=True)


class MensajeResponse(BaseModel):
    mensaje: str


# =============================================================================
# Helpers
# =============================================================================


def _get_equipo_or_404(db: Session, equipo_id: int) -> Equipo:
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if equipo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado")
    return equipo


def _reject_global(equipo: Equipo) -> None:
    if equipo.es_global:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El equipo global tiene membresía implícita; no admite esta operación",
        )


def _get_miembro(db: Session, equipo_id: int, usuario_id: int) -> Optional[EquipoMiembro]:
    return (
        db.query(EquipoMiembro)
        .filter(EquipoMiembro.equipo_id == equipo_id, EquipoMiembro.usuario_id == usuario_id)
        .first()
    )


def _require_admin(db: Session, equipo_id: int, user: Usuario) -> EquipoMiembro:
    miembro = _get_miembro(db, equipo_id, user.id)
    if miembro is None or miembro.rol != RolEquipo.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador del equipo puede realizar esta operación",
        )
    return miembro


def _require_member(db: Session, equipo_id: int, user: Usuario) -> EquipoMiembro:
    miembro = _get_miembro(db, equipo_id, user.id)
    if miembro is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No sos miembro de este equipo",
        )
    return miembro


def _count_admins(db: Session, equipo_id: int) -> int:
    return (
        db.query(EquipoMiembro)
        .filter(EquipoMiembro.equipo_id == equipo_id, EquipoMiembro.rol == RolEquipo.ADMIN.value)
        .count()
    )


def _assert_admin_no_huerfano(db: Session, equipo_id: int, miembro: EquipoMiembro, nuevo_rol: Optional[str]) -> None:
    """Guards against orphaning a team of its last admin.

    Raises 400 if `miembro` is the team's last admin and the pending change
    strips their admin rol — a demotion (`nuevo_rol != admin`) or a removal
    (`nuevo_rol is None`). Called from every endpoint that changes/removes a
    rol (POST upsert, PATCH, DELETE) so the invariant lives in one place.
    """
    if miembro.rol != RolEquipo.ADMIN.value:
        return
    pierde_admin = nuevo_rol is None or nuevo_rol != RolEquipo.ADMIN.value
    if pierde_admin and _count_admins(db, equipo_id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede quitar el último administrador del equipo",
        )


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/equipos", response_model=EquipoResponse, status_code=status.HTTP_201_CREATED)
def crear_equipo(
    request: EquipoCreateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Equipo:
    """Creates a new (non-global) team; the creator becomes its admin."""
    equipo = Equipo(nombre=request.nombre, es_global=False, creado_por=current_user.id)
    db.add(equipo)
    db.flush()

    miembro = EquipoMiembro(equipo_id=equipo.id, usuario_id=current_user.id, rol=RolEquipo.ADMIN.value)
    db.add(miembro)

    db.commit()
    db.refresh(equipo)
    return equipo


@router.get("/equipos", response_model=List[EquipoResponse])
def listar_equipos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Equipo]:
    """Lists teams the current user belongs to, plus the global ("U") team.

    This is the data source for the frontend layer selector ("View colors
    of: Mine / Team X / Global").
    """
    global_id = get_global_equipo_id(db)

    mis_equipos = (
        db.query(Equipo)
        .join(EquipoMiembro, EquipoMiembro.equipo_id == Equipo.id)
        .filter(EquipoMiembro.usuario_id == current_user.id)
        .all()
    )

    resultado = list(mis_equipos)
    if not any(e.id == global_id for e in resultado):
        resultado.append(_get_equipo_or_404(db, global_id))

    return resultado


@router.get("/equipos/{equipo_id}/miembros", response_model=List[MiembroResponse])
def listar_miembros(
    equipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[EquipoMiembro]:
    """Lists explicit members of a team. Requires the caller be a member."""
    equipo = _get_equipo_or_404(db, equipo_id)
    _reject_global(equipo)
    _require_member(db, equipo_id, current_user)

    return db.query(EquipoMiembro).filter(EquipoMiembro.equipo_id == equipo_id).all()


@router.post("/equipos/{equipo_id}/miembros", response_model=MiembroResponse, status_code=status.HTTP_201_CREATED)
def agregar_miembro(
    equipo_id: int,
    request: MiembroAddRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EquipoMiembro:
    """Adds a member to a team. Requires the caller be an admin of that team."""
    equipo = _get_equipo_or_404(db, equipo_id)
    _reject_global(equipo)
    _require_admin(db, equipo_id, current_user)

    usuario = db.query(Usuario).filter(Usuario.id == request.usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    existente = _get_miembro(db, equipo_id, request.usuario_id)
    if existente is not None:
        # Idempotent: re-adding an existing member updates their rol instead
        # of raising a 409, since the caller's intent (this user should be a
        # member with this rol) is already satisfied either way.
        # Same last-admin guard as PATCH/DELETE: re-adding the sole admin with
        # a non-admin rol would silently orphan the team.
        _assert_admin_no_huerfano(db, equipo_id, existente, request.rol.value)
        existente.rol = request.rol.value
        db.commit()
        db.refresh(existente)
        return existente

    miembro = EquipoMiembro(equipo_id=equipo_id, usuario_id=request.usuario_id, rol=request.rol.value)
    db.add(miembro)
    db.commit()
    db.refresh(miembro)
    return miembro


@router.patch("/equipos/{equipo_id}/miembros/{usuario_id}", response_model=MiembroResponse)
def actualizar_rol_miembro(
    equipo_id: int,
    usuario_id: int,
    request: MiembroUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EquipoMiembro:
    """Changes a member's rol. Requires the caller be an admin of that team."""
    equipo = _get_equipo_or_404(db, equipo_id)
    _reject_global(equipo)
    _require_admin(db, equipo_id, current_user)

    miembro = _get_miembro(db, equipo_id, usuario_id)
    if miembro is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no es miembro de este equipo")

    _assert_admin_no_huerfano(db, equipo_id, miembro, request.rol.value)

    miembro.rol = request.rol.value
    db.commit()
    db.refresh(miembro)
    return miembro


@router.delete("/equipos/{equipo_id}/miembros/{usuario_id}", response_model=MensajeResponse)
def eliminar_miembro(
    equipo_id: int,
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Removes a member from a team. Requires the caller be an admin of that team."""
    equipo = _get_equipo_or_404(db, equipo_id)
    _reject_global(equipo)
    _require_admin(db, equipo_id, current_user)

    miembro = _get_miembro(db, equipo_id, usuario_id)
    if miembro is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no es miembro de este equipo")

    _assert_admin_no_huerfano(db, equipo_id, miembro, None)

    db.delete(miembro)
    db.commit()
    return {"mensaje": "Miembro eliminado"}


@router.patch("/equipos/{equipo_id}", response_model=EquipoResponse)
def renombrar_equipo(
    equipo_id: int,
    request: EquipoUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Equipo:
    """Renames a team. Requires the caller be an admin of that team."""
    equipo = _get_equipo_or_404(db, equipo_id)
    _reject_global(equipo)
    _require_admin(db, equipo_id, current_user)

    equipo.nombre = request.nombre
    db.commit()
    db.refresh(equipo)
    return equipo


@router.delete("/equipos/{equipo_id}", response_model=MensajeResponse)
def eliminar_equipo(
    equipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Deletes a team and its memberships. Blocked if it still has color rows.

    Requires the caller be an admin of that team. Does NOT delete color data:
    if the team still has `ProductoColor` rows the request is rejected, and the
    caller must reassign or clear those first, to avoid silently discarding
    team color data.
    """
    equipo = _get_equipo_or_404(db, equipo_id)
    _reject_global(equipo)
    _require_admin(db, equipo_id, current_user)

    tiene_colores = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo_id).first() is not None
    if tiene_colores:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El equipo tiene colores marcados; elimínalos antes de borrar el equipo",
        )

    db.query(EquipoMiembro).filter(EquipoMiembro.equipo_id == equipo_id).delete()
    db.delete(equipo)
    db.commit()
    return {"mensaje": "Equipo eliminado"}
