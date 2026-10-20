"""Router: sell-out campaigns (`/api/sell-out/campanas`), feature sell-in-sell-out T6.

A campaign credits every unit sold of its product groups between two dates,
by a fixed amount per unit or a percentage of cost (default) or net sale
price, and that credit is added to profit. The rules live in
`app.services.sell_out.campanas`; this module is HTTP only.

- Reads need `sell_out.ver`; load, edit and void need `sell_out.gestionar`
  (migration `20261105_sell_out_campanas`). The author comes from the token.
- `GET ""` is paginated, latest start date first, filtered by estado, tipo,
  a day the campaign covers (`vigente_en`), free text (`q`) and group.
- `PUT /{id}` replaces an active campaign (409 once voided). There is no
  delete: `POST /{id}/anular` voids it, once (409 on a second call).
- `POST /{id}/tipo-cambio` sets or changes the rate of a USD `al_cobro`
  campaign when the brand pays, also after it ended (audited; 409 once voided).
  Until then its ARS figures are estimates at the current BNA rate (T7).
- Business-rule errors are a 422 with one readable Spanish message; an
  unknown campaign is a 404.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.sell_out import SellOutCampana
from app.models.usuario import Usuario
from app.schemas.sell_out import (
    Estado,
    SellOutAnularIn,
    SellOutCampanaIn,
    SellOutCampanaListOut,
    SellOutCampanaOut,
    SellOutTipoCambioIn,
    Tipo,
)
from app.services.permisos_service import verificar_permiso
from app.services.sell_out import campanas as service

router = APIRouter(prefix="/sell-out/campanas", tags=["Sell out"])


def _requiere(codigo: str):
    def dependencia(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
        if not verificar_permiso(db, current_user, codigo):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {codigo}")
        return current_user

    return dependencia


requiere_ver = _requiere("sell_out.ver")
requiere_gestionar = _requiere("sell_out.gestionar")


def _no_existe(campana_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La campaña {campana_id} no existe")


def _error(db: Session, exc: service.SellOutError) -> HTTPException:
    db.rollback()
    code = status.HTTP_409_CONFLICT if isinstance(exc, service.SellOutYaAnulada) else 422
    return HTTPException(status_code=code, detail=str(exc))


@router.get("", response_model=SellOutCampanaListOut)
def listar_campanas(
    estado: Optional[Estado] = Query(None),
    tipo: Optional[Tipo] = Query(None),
    vigente_en: Optional[date] = Query(None, description="Campaigns whose date range includes this day"),
    q: Optional[str] = Query(None, max_length=200, description="Name or description"),
    grupo_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    filtros = service.FiltrosCampanas(estado=estado, vigente_en=vigente_en, q=q, grupo_id=grupo_id, tipo=tipo)
    campanas, total = service.listar_campanas(db, filtros, page=page, page_size=page_size)
    return {"items": service.serializar(db, campanas), "total": total, "page": page, "page_size": page_size}


@router.get("/{campana_id}", response_model=SellOutCampanaOut)
def obtener_campana(campana_id: int, _user: Usuario = Depends(requiere_ver), db: Session = Depends(get_db)) -> dict:
    campana = db.get(SellOutCampana, campana_id)
    if campana is None:
        raise _no_existe(campana_id)
    return service.serializar(db, [campana])[0]


@router.post("", response_model=SellOutCampanaOut, status_code=status.HTTP_201_CREATED)
def crear_campana(
    data: SellOutCampanaIn, user: Usuario = Depends(requiere_gestionar), db: Session = Depends(get_db)
) -> dict:
    try:
        campana = service.crear_campana(db, data, user.id)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    return service.serializar(db, [campana])[0]


@router.put("/{campana_id}", response_model=SellOutCampanaOut)
def editar_campana(
    campana_id: int,
    data: SellOutCampanaIn,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Replace every field and the groups of an active campaign."""
    try:
        campana = service.editar_campana(db, campana_id, data, user.id)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    if campana is None:
        raise _no_existe(campana_id)
    return service.serializar(db, [campana])[0]


@router.post("/{campana_id}/anular", response_model=SellOutCampanaOut)
def anular_campana(
    campana_id: int,
    data: Optional[SellOutAnularIn] = Body(None),
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Void the campaign (the reason goes to the audit row). A second call is a 409."""
    try:
        campana = service.anular_campana(db, campana_id, user.id, data.motivo if data else None)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    if campana is None:
        raise _no_existe(campana_id)
    return service.serializar(db, [campana])[0]


@router.post("/{campana_id}/tipo-cambio", response_model=SellOutCampanaOut)
def definir_tipo_cambio(
    campana_id: int,
    data: SellOutTipoCambioIn,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Set the rate the brand paid at for an `al_cobro` campaign; it can be changed later."""
    try:
        campana = service.definir_tipo_cambio(db, campana_id, data.tipo_cambio, user.id)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    if campana is None:
        raise _no_existe(campana_id)
    return service.serializar(db, [campana])[0]
