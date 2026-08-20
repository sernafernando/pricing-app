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


_AFFECTED_CATEGORIES_CAP = 5


class MeasurementProfileResponse(BaseModel):
    id: int
    name: str
    weight: Decimal
    width: Decimal
    height: Decimal
    depth: Decimal
    # PR-8 gap C/D: how many categories currently point at this profile
    # (count of `tn_category_profile_hint` rows for `profile_id`) plus a
    # capped, best-effort list of affected category names — lets the
    # frontend's delete-confirmation dialog warn the operator without a
    # second round-trip. `categorias_en_uso`/`total_categorias_afectadas`
    # are always equal today (both count hint rows); kept as two fields
    # because they answer different UI questions (badge count vs. "y N más").
    categorias_en_uso: int = 0
    categorias_afectadas: List[str] = []
    total_categorias_afectadas: int = 0

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
    `produccion_banlist`'s GET endpoints.

    PR-8 gap C/D: also loads `categorias_en_uso`/`categorias_afectadas` via
    ONE aggregate query for every profile's hints combined — never one query
    per profile (this repo has a documented pool-exhaustion incident; see
    `_upsert_publish_overrides` and PR-5b/PR-7's bulk-loaded hint map, which
    hit the exact same rule for the suggestion path)."""
    perfiles = db.query(TnMeasurementProfile).order_by(TnMeasurementProfile.id).all()

    # Acotada a los perfiles que realmente se están devolviendo: sin el
    # `IN` esto lee la tabla de hints ENTERA para armar el contador, que es
    # justo lo que el resto del módulo evita con sus caps explícitos
    # (`TN_PRODUCTOS_QUERY_CAP`, `GBP_ROWS_CAP`) por el incidente de pool
    # exhaustion del repo. Sigue siendo UNA query para toda la lista.
    profile_ids = [p.id for p in perfiles]
    hint_rows = (
        db.query(TnCategoryProfileHint.profile_id, TnCategoryProfileHint.categoria)
        .filter(TnCategoryProfileHint.profile_id.in_(profile_ids))
        .order_by(TnCategoryProfileHint.id)
        .all()
        if profile_ids
        else []
    )
    categorias_by_profile: dict[int, list[str]] = {}
    for profile_id, categoria in hint_rows:
        categorias_by_profile.setdefault(profile_id, []).append(categoria)

    result = []
    for perfil in perfiles:
        categorias = categorias_by_profile.get(perfil.id, [])
        # Distinct category names for the chip list, cap-and-count preserving
        # insertion order (stable across query plans via the `.id` ordering
        # above).
        distinct_categorias = list(dict.fromkeys(categorias))
        response = MeasurementProfileResponse.model_validate(perfil)
        response.categorias_en_uso = len(categorias)
        response.categorias_afectadas = distinct_categorias[:_AFFECTED_CATEGORIES_CAP]
        response.total_categorias_afectadas = len(categorias)
        result.append(response)
    return result


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

    Registration order note (PR-7 D task): this route MUST stay registered
    BEFORE the `PUT/DELETE /tn-measurement-profiles/{profile_id}` routes
    below. There is no `GET /{profile_id}` today, so the bug is currently
    latent — but FastAPI matches routes in registration order, and the day a
    `GET /{profile_id}` is added, `"suggestion"` would parse as `int` against
    that route first and 422. See `TestSuggestionRouteRegisteredBeforeProfileId`.
    """
    # Same guard as the bulk path's `_select_hint_profile_id`: both docstrings
    # claim an identical lookup order, so they must not diverge on a blank
    # `categoria=` (which would otherwise run a real lookup against "").
    if not categoria.strip():
        return ProfileSuggestionResponse(profile_id=None)

    if subcategoria:
        hint = (
            db.query(TnCategoryProfileHint)
            .filter(
                TnCategoryProfileHint.categoria == categoria,
                TnCategoryProfileHint.subcategoria == subcategoria,
            )
            .order_by(TnCategoryProfileHint.uso_count.desc(), TnCategoryProfileHint.id)
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
        .order_by(TnCategoryProfileHint.uso_count.desc(), TnCategoryProfileHint.id)
        .first()
    )
    if hint:
        return ProfileSuggestionResponse(profile_id=hint.profile_id)

    return ProfileSuggestionResponse(profile_id=None)


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
