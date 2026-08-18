"""CRUD + category-based suggestion for TN measurement profiles (PR-4).

All create/update/delete operations are gated on `admin.gestionar_tn_perfiles`
(D10) — a permission distinct from `admin.gestionar_tn_publicacion`, so
publish access and profile-administration access are fully independent in
both directions (MP1).
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.models.tn_category_profile_hint import TnCategoryProfileHint
from app.models.tn_measurement_profile import TnMeasurementProfile

router = APIRouter()

_PERMISO = "admin.gestionar_tn_perfiles"


class MeasurementProfileRequest(BaseModel):
    name: str
    weight: Decimal
    width: Decimal
    height: Decimal
    depth: Decimal


class MeasurementProfileResponse(BaseModel):
    id: int
    name: str
    weight: Decimal
    width: Decimal
    height: Decimal
    depth: Decimal

    model_config = ConfigDict(from_attributes=True)


class ProfileSuggestionResponse(BaseModel):
    profile_id: Optional[int] = None


class DeleteProfileResponse(BaseModel):
    message: str
    profile_id: int


@router.get(
    "/tn-measurement-profiles",
    response_model=List[MeasurementProfileResponse],
    dependencies=[Depends(get_current_user)],
)
def listar_perfiles(db: Session = Depends(get_db)):
    """Lists all measurement profiles. Read-only — authenticated but with no
    permission gate: any logged-in user may read, mirroring the read-side of
    `produccion_banlist`'s GET endpoints."""
    return db.query(TnMeasurementProfile).order_by(TnMeasurementProfile.id).all()


@router.post(
    "/tn-measurement-profiles",
    response_model=MeasurementProfileResponse,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def crear_perfil(request: MeasurementProfileRequest, db: Session = Depends(get_db)):
    perfil = TnMeasurementProfile(
        name=request.name,
        weight=request.weight,
        width=request.width,
        height=request.height,
        depth=request.depth,
    )
    db.add(perfil)
    db.commit()
    db.refresh(perfil)
    return perfil


@router.put(
    "/tn-measurement-profiles/{profile_id}",
    response_model=MeasurementProfileResponse,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def actualizar_perfil(profile_id: int, request: MeasurementProfileRequest, db: Session = Depends(get_db)):
    perfil = db.query(TnMeasurementProfile).filter(TnMeasurementProfile.id == profile_id).first()
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil de medidas no encontrado")

    perfil.name = request.name
    perfil.weight = request.weight
    perfil.width = request.width
    perfil.height = request.height
    perfil.depth = request.depth
    db.commit()
    db.refresh(perfil)
    return perfil


@router.delete(
    "/tn-measurement-profiles/{profile_id}",
    response_model=DeleteProfileResponse,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def eliminar_perfil(profile_id: int, db: Session = Depends(get_db)) -> DeleteProfileResponse:
    perfil = db.query(TnMeasurementProfile).filter(TnMeasurementProfile.id == profile_id).first()
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil de medidas no encontrado")

    db.delete(perfil)
    db.commit()
    return DeleteProfileResponse(message="Perfil de medidas eliminado", profile_id=profile_id)


@router.get(
    "/tn-measurement-profiles/suggestion",
    response_model=ProfileSuggestionResponse,
    dependencies=[Depends(get_current_user)],
)
def sugerir_perfil(categoria: str, subcategoria: Optional[str] = None, db: Session = Depends(get_db)):
    """Category-based suggestion (MP3). Lookup order: exact
    `(categoria, subcategoria)` → highest `uso_count`, else `(categoria, NULL)`
    → highest `uso_count`, else no suggestion (empty result, not an error) —
    cold start for a never-used category returns `profile_id: null`.
    """
    if subcategoria:
        hint = (
            db.query(TnCategoryProfileHint)
            .filter(
                TnCategoryProfileHint.categoria == categoria,
                TnCategoryProfileHint.subcategoria == subcategoria,
            )
            .order_by(TnCategoryProfileHint.uso_count.desc())
            .first()
        )
        if hint:
            return ProfileSuggestionResponse(profile_id=hint.profile_id)

    hint = (
        db.query(TnCategoryProfileHint)
        .filter(
            TnCategoryProfileHint.categoria == categoria,
            TnCategoryProfileHint.subcategoria.is_(None),
        )
        .order_by(TnCategoryProfileHint.uso_count.desc())
        .first()
    )
    if hint:
        return ProfileSuggestionResponse(profile_id=hint.profile_id)

    return ProfileSuggestionResponse(profile_id=None)
