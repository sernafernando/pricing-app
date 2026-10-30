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
- `POST /anular` (`{"ids": [...], "motivo"}`, `sell_out.gestionar`) voids up to 500 campaigns in one
  transaction, each through the single void's step (same audit row and queueing). Already voided ones are
  skipped and listed in `omitidas`. All or nothing: an unknown id is a 422 `ANULACION_RECHAZADA` naming each
  refused id and why (`rechazadas`) and nothing is voided; a campaign being rebuilt is the 409 below. Voiding
  is not brand-scoped (a PM with `sell_out.repartir` only cannot void), so the per-request `gestionar` check
  is the per-record one.
- A brand-scoped PM (`sell_out.repartir` without `sell_out.gestionar`) reads
  a `monto_total` campaign's shares of their brands only, in the list, the
  detail and the `PUT /{id}/reparto` response, so what they read is what they
  may send back; the summary stays the campaign's.
- `PUT /{id}/reparto` sets the split of a `monto_total` campaign among its
  products (T26c, S34), with `sell_out.repartir` or `sell_out.gestionar`
  (migration `20261216_sell_out_repartir_permiso`). A user who sees every
  brand replaces the whole split; a PM (`sell_out.repartir` only) splits only
  the products of their brands (`pm_scope`): another brand's product is a 403
  naming it, and the shares they cannot see are kept; their response lists
  only the shares of their brands (the summary is the campaign's aggregate).
- `POST /{id}/tipo-cambio` sets or changes the rate of a USD `al_cobro`
  campaign when the brand pays, also after it ended (audited; 409 once voided).
  Until then its ARS figures are estimates at the current BNA rate (T7).
- An edit, void or rate change while `sell_out.drain` is rebuilding the
  campaign is a 409 ("La campaña se está recalculando. Reintentar en unos
  segundos."); nothing is stored and the client can retry.
- Every campaign comes with `resumen`, what it credited so far: units, amount
  in its currency and in ARS, what its cap has left, per channel, the sales
  waiting for their percentage base and the rebuild state
  (`app.services.sell_out.resumen`; a fixed number of queries per page).
  `GET /{id}/consumos` pages its credited lines, in sale order.
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
    SellOutAnularMasivoIn,
    SellOutAnularMasivoOut,
    SellOutCampanaIn,
    SellOutCampanaListOut,
    SellOutCampanaOut,
    SellOutConsumosListOut,
    SellOutRepartoIn,
    SellOutTipoCambioIn,
    Tipo,
)
from app.services.permisos_service import verificar_permiso
from app.services.pm_scope import get_pares_marca_categoria_usuario
from app.services.sell_out import campanas as service
from app.services.sell_out import resumen

router = APIRouter(prefix="/sell-out/campanas", tags=["Sell out"])


def _requiere(codigo: str):
    def dependencia(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
        if not verificar_permiso(db, current_user, codigo):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {codigo}")
        return current_user

    return dependencia


requiere_ver = _requiere("sell_out.ver")
requiere_gestionar = _requiere("sell_out.gestionar")


def _pares_reparto(db: Session, user: Usuario) -> Optional[set]:
    """The (MARCA, CATEGORIA) pairs a brand-scoped PM splits and reads shares of: a user with `sell_out.repartir`
    but not `sell_out.gestionar` who does not see every brand (`pm_scope`). None for everyone else."""
    if verificar_permiso(db, user, "sell_out.gestionar") or not verificar_permiso(db, user, "sell_out.repartir"):
        return None
    alcance_pm = get_pares_marca_categoria_usuario(db, user)  # None: the user sees every brand
    return None if alcance_pm is None else set(alcance_pm)


def _no_existe(campana_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La campaña {campana_id} no existe")


def _error(db: Session, exc: service.SellOutError) -> HTTPException:
    db.rollback()
    conflicto = (service.SellOutYaAnulada, service.SellOutRecalculando)
    if isinstance(exc, service.SellOutSinPermiso):
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_409_CONFLICT if isinstance(exc, conflicto) else 422
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
    user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    filtros = service.FiltrosCampanas(estado=estado, vigente_en=vigente_en, q=q, grupo_id=grupo_id, tipo=tipo)
    campanas, total = service.listar_campanas(db, filtros, page=page, page_size=page_size)
    items = service.solo_sus_marcas(db, resumen.serializar(db, campanas), _pares_reparto(db, user))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{campana_id}", response_model=SellOutCampanaOut)
def obtener_campana(campana_id: int, user: Usuario = Depends(requiere_ver), db: Session = Depends(get_db)) -> dict:
    campana = db.get(SellOutCampana, campana_id)
    if campana is None:
        raise _no_existe(campana_id)
    return service.solo_sus_marcas(db, resumen.serializar(db, [campana]), _pares_reparto(db, user))[0]


@router.get("/{campana_id}/consumos", response_model=SellOutConsumosListOut)
def listar_consumos(
    campana_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    """The campaign's credited sale lines, in sale order, one page at a time."""
    campana = db.get(SellOutCampana, campana_id)
    if campana is None:
        raise _no_existe(campana_id)
    items, total = resumen.consumos(db, campana, page=page, page_size=page_size)
    return {
        "moneda": campana.moneda,
        "ars_estimado": resumen.ars_estimado(campana),
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=SellOutCampanaOut, status_code=status.HTTP_201_CREATED)
def crear_campana(
    data: SellOutCampanaIn, user: Usuario = Depends(requiere_gestionar), db: Session = Depends(get_db)
) -> dict:
    try:
        campana = service.crear_campana(db, data, user.id)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    return resumen.serializar(db, [campana])[0]


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
    return resumen.serializar(db, [campana])[0]


ANULAR_MASIVO_MAX = 500


@router.post("/anular", response_model=SellOutAnularMasivoOut)
def anular_campanas(
    data: SellOutAnularMasivoIn,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Void the selected campaigns, all or nothing (module docstring); the reason goes to each audit row."""
    if not data.ids:
        raise HTTPException(status_code=422, detail="Elegí al menos una campaña para anular.")
    if len(set(data.ids)) > ANULAR_MASIVO_MAX:
        raise HTTPException(status_code=422, detail=f"Se pueden anular hasta {ANULAR_MASIVO_MAX} campañas por vez.")
    try:
        anuladas, omitidas = service.anular_campanas(db, data.ids, user.id, data.motivo)
    except service.SellOutAnulacionRechazada as exc:
        rechazadas = [{"id": i, "motivo": motivo} for i, motivo in exc.rechazadas]
        detail = {"code": "ANULACION_RECHAZADA", "message": str(exc), "rechazadas": rechazadas}
        raise HTTPException(status_code=422, detail=detail) from exc
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    return {"anuladas": anuladas, "omitidas": omitidas}


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
    return resumen.serializar(db, [campana])[0]


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
    return resumen.serializar(db, [campana])[0]


@router.put("/{campana_id}/reparto", response_model=SellOutCampanaOut)
def repartir_campana(
    campana_id: int,
    data: SellOutRepartoIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Set the split of an active `monto_total` campaign among its products (module docstring)."""
    if not verificar_permiso(db, user, "sell_out.gestionar") and not verificar_permiso(db, user, "sell_out.repartir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso: sell_out.repartir")
    pares = _pares_reparto(db, user)
    try:
        campana = service.repartir(db, campana_id, data.repartos, user.id, pares)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    if campana is None:
        raise _no_existe(campana_id)
    return service.solo_sus_marcas(db, resumen.serializar(db, [campana]), pares)[0]
