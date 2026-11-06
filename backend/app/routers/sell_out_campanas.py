"""Router: sell-out campaigns (`/api/sell-out/campanas`), feature sell-in-sell-out T6.

A campaign credits every unit sold of its product groups between two dates,
by a fixed amount per unit or a percentage of cost (default) or net sale
price, and that credit is added to profit. The rules live in
`app.services.sell_out.campanas`; this module is HTTP only.

- Reads need `sell_out.ver`; load, edit and void need `sell_out.gestionar`
  (migration `20261105_sell_out_campanas`). The author comes from the token.
- `GET ""` is paginated, latest start date first, filtered by estado, tipo,
  a day the campaign covers (`vigente_en`), free text (`q`), group, moneda, a
  period its dates overlap (`desde` / `hasta`, 422 when inverted), marca (a
  product its groups reach, the campaign rule) and program (`programa_id`, or
  `sin_programa=true` for the campaigns without one; both at once is a 422).
- Programs are no longer created, edited or assigned from the app (the tactical is the brand's program), but
  stored ones are still honored: `POST ""` still accepts an existing program (`programa_id`, optional; the
  renewal draft carries the original's): an unknown one is a 404, an archived one a 422 («El programa «X» está
  archivado.»). `PUT /{id}` keeps the stored program and ignores one sent. A renewal sets `renovada_de_id`, the
  campaign it renews. That campaign must exist and be of the same program (422; a copy of an archived program's campaign goes
  without program). A campaign that a non-voided campaign already renews is a 409.
- `GET /{id}/renovacion` (`sell_out.gestionar`) is the renewal draft of a campaign, active or voided: a NEW
  campaign in the exact shape `POST ""` takes, with the next calendar quarter's dates and the name's trailing
  period advanced (`app.services.sell_out.renovacion`). It writes nothing; saving it is an ordinary create, and
  the original never changes.
- `PUT /{id}` replaces an active campaign (409 once voided). There is no
  delete: `POST /{id}/anular` voids it, once (409 on a second call).
- `POST /anular` (`{"ids": [...], "motivo"}`, `sell_out.gestionar`) voids up to 500 campaigns in one
  transaction, each through the single void's step (same audit content, with `es_masivo` set, and queueing).
  Already voided ones are skipped and listed in `omitidas`. All or nothing, nothing is voided and the refusal
  `ANULACION_RECHAZADA` names each refused id and why (`rechazadas`): a 422 for unknown ids, a 409 (retry) when a
  campaign is being rebuilt or a concurrent edit deadlocks with the bulk void, naming it and the unknown ids. Voiding
  is not brand-scoped (a PM with `sell_out.repartir` only cannot void), so the per-request `gestionar` check
  is the per-record one.
- `POST /editar-masivo` (`{"campana_ids": [...], "fecha_desde"?, "fecha_hasta"?, "acumulable"?}`,
  `sell_out.gestionar`) sets the filled fields (at least one) on up to 500 campaigns in one transaction, each
  through the single edit's step (same rules, audit content with `es_masivo` set, and queueing), everything else
  kept as stored (`app.services.sell_out.edicion_masiva`). Campaigns that already have the values are listed in
  `sin_cambio` and write nothing. All or nothing like the bulk void: the refusal `EDICION_RECHAZADA` names each
  refused campaign (`rechazadas`: id, name and why: unknown, voided, dates ending before they start, a rule of
  the edit), a 422; a 409 (retry) when one is being rebuilt or deadlocks with a concurrent writer. Not
  brand-scoped either: `gestionar` is the per-record check. `POST /editar-masivo/previa`, same body and
  permission, writes nothing and says what the apply would do on the same data: which campaigns change, which
  have no change, the refused ones (listed with the same reasons, not raised; busy is the same 409), and what the
  rebuild the apply queues would take from and give to each campaign: it runs the drain's own rebuild inside the
  request and rolls everything back, so the lines, units and money (per currency in the totals) that leave and
  enter are exact on the same data, caps, stacking and fixed-total splits included. Linked campaigns whose credit
  moves are listed in `vinculadas` (`en_seleccion` False when not selected). A rebuild that would fail is a 422;
  one that waits more than 2 s for a selected campaign's row (another preview or bulk edit), a queue row (a
  running drain) or the rebuild's locks, or is in a lock cycle, is the busy 409, nothing written. A campaign with
  pending work (a queue row before the preview) is flagged `incluye_pendientes`; the notice
  `aviso_pendientes` («incluye cambios pendientes que no causa esta edición») appears when any campaign the
  rebuild touches is pending, listed or not (a voided one not drained yet included): the numbers include it.
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
  An edit, void, rate change or split that deadlocks with another writer (a
  bulk edit or its preview holding the queue rows it needs) is the same 409 ("Otra operación está
  modificando la campaña en este momento. Reintentar en unos segundos.").
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
    Moneda,
    RepartoCriterio,
    SellOutAnularIn,
    SellOutAnularMasivoIn,
    SellOutAnularMasivoOut,
    SellOutCampanaIn,
    SellOutCampanaListOut,
    SellOutCampanaOut,
    SellOutConsumosListOut,
    SellOutEdicionPreviaOut,
    SellOutEditarMasivoIn,
    SellOutEditarMasivoOut,
    SellOutRepartoIn,
    SellOutRepartoPreviaOut,
    SellOutTipoCambioIn,
    Tipo,
)
from app.services.permisos_service import verificar_permiso
from app.services.pm_scope import get_pares_marca_categoria_usuario
from app.services.sell_out import campanas as service
from app.services.sell_out import criterio as criterio_service
from app.services.sell_out import edicion_masiva, programas, renovacion, resumen

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


def _requiere_repartir(db: Session, user: Usuario) -> None:
    if not verificar_permiso(db, user, "sell_out.gestionar") and not verificar_permiso(db, user, "sell_out.repartir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso: sell_out.repartir")


def _no_existe(campana_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La campaña {campana_id} no existe")


def _error(db: Session, exc: service.SellOutError) -> HTTPException:
    db.rollback()
    conflicto = (service.SellOutYaAnulada, service.SellOutRecalculando, service.SellOutYaRenovada)
    if isinstance(exc, service.SellOutSinPermiso):
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_409_CONFLICT if isinstance(exc, conflicto) else 422
    return HTTPException(status_code=code, detail=str(exc))


def _filtros(
    estado: Optional[Estado] = Query(None),
    tipo: Optional[Tipo] = Query(None),
    vigente_en: Optional[date] = Query(None, description="Campaigns whose date range includes this day"),
    q: Optional[str] = Query(None, max_length=200, description="Name or description"),
    grupo_id: Optional[int] = Query(None),
    moneda: Optional[Moneda] = Query(None),
    desde: Optional[date] = Query(None, description="With hasta: campaigns whose dates overlap [desde, hasta]"),
    hasta: Optional[date] = Query(None),
    marca: Optional[str] = Query(None, max_length=100, description="Brand of a product the campaign's groups reach"),
    programa_id: Optional[int] = Query(None, description="Campaigns of this program"),
    sin_programa: bool = Query(False, description="Campaigns without a program; not together with programa_id"),
) -> service.FiltrosCampanas:
    """The list's filters, shared by the list and the grouped view."""
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha desde no puede ser posterior a la fecha hasta.")
    if programa_id is not None and sin_programa:
        raise HTTPException(status_code=422, detail="Elegí un programa o «Sin programa», no los dos.")
    return service.FiltrosCampanas(
        estado=estado,
        vigente_en=vigente_en,
        q=q,
        grupo_id=grupo_id,
        tipo=tipo,
        moneda=moneda,
        desde=desde,
        hasta=hasta,
        marca=marca,
        programa_id=programa_id,
        sin_programa=sin_programa,
    )


@router.get("", response_model=SellOutCampanaListOut)
def listar_campanas(
    # The permission first: FastAPI solves dependencies in order, so a user without it never reaches the filters' 422.
    user: Usuario = Depends(requiere_ver),
    filtros: service.FiltrosCampanas = Depends(_filtros),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
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
    except programas.ProgramaError as exc:
        db.rollback()
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, programas.ProgramaNoExiste) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return resumen.serializar(db, [campana])[0]


@router.get("/{campana_id}/renovacion", response_model=SellOutCampanaIn)
def renovar_campana(
    campana_id: int, _user: Usuario = Depends(requiere_gestionar), db: Session = Depends(get_db)
) -> SellOutCampanaIn:
    """The renewal draft: a NEW campaign to review and send to `POST ""`. Voided campaigns can be renewed too,
    since the draft is a copy; nothing is written and the original does not change."""
    try:
        draft = renovacion.borrador(db, campana_id)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    if draft is None:
        raise _no_existe(campana_id)
    return draft


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
        raise HTTPException(status_code=409 if exc.reintentar else 422, detail=detail) from exc
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    return {"anuladas": anuladas, "omitidas": omitidas}


EDITAR_MASIVO_MAX = ANULAR_MASIVO_MAX


def _validar_masivo(data: SellOutEditarMasivoIn) -> dict:
    """The bulk edit's caps, like the bulk void's; returns the filled fields."""
    if not data.campana_ids:
        raise HTTPException(status_code=422, detail="Elegí al menos una campaña para editar.")
    if len(set(data.campana_ids)) > EDITAR_MASIVO_MAX:
        raise HTTPException(status_code=422, detail=f"Se pueden editar hasta {EDITAR_MASIVO_MAX} campañas por vez.")
    cambios = data.cambios()
    if not cambios:
        raise HTTPException(
            status_code=422, detail="Completá al menos un campo para editar: fecha desde, fecha hasta o acumulable."
        )
    return cambios


def _edicion_rechazada(exc: edicion_masiva.SellOutEdicionRechazada) -> HTTPException:
    rechazadas = [{"id": i, "nombre": nombre, "motivo": motivo} for i, nombre, motivo in exc.rechazadas]
    detail = {"code": "EDICION_RECHAZADA", "message": str(exc), "rechazadas": rechazadas}
    return HTTPException(status_code=409 if exc.reintentar else 422, detail=detail)


@router.post("/editar-masivo/previa", response_model=SellOutEdicionPreviaOut)
def previa_edicion_masiva(
    data: SellOutEditarMasivoIn,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """What the bulk edit would do, writing nothing (module docstring): refused campaigns are listed, not raised."""
    cambios = _validar_masivo(data)
    try:
        return edicion_masiva.previa_edicion(db, data.campana_ids, cambios, user.id)
    except edicion_masiva.SellOutEdicionRechazada as exc:
        raise _edicion_rechazada(exc) from exc
    except service.SellOutError as exc:
        raise _error(db, exc) from exc


@router.post("/editar-masivo", response_model=SellOutEditarMasivoOut)
def editar_campanas_masivo(
    data: SellOutEditarMasivoIn,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Set the filled fields on the selected campaigns, all or nothing (module docstring)."""
    cambios = _validar_masivo(data)
    try:
        editadas, sin_cambio = edicion_masiva.editar_campanas(db, data.campana_ids, cambios, user.id)
    except edicion_masiva.SellOutEdicionRechazada as exc:
        raise _edicion_rechazada(exc) from exc
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    return {"editadas": editadas, "sin_cambio": sin_cambio}


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
    """Set the split of an active `monto_total` campaign among its products (module docstring), by hand or, with
    `criterio`, by a criterion over the whole total (only for a user who sees every brand: 403 otherwise)."""
    _requiere_repartir(db, user)
    pares = _pares_reparto(db, user)
    try:
        campana = service.repartir(db, campana_id, data.repartos, user.id, pares, criterio=data.criterio)
    except service.SellOutError as exc:
        raise _error(db, exc) from exc
    if campana is None:
        raise _no_existe(campana_id)
    return service.solo_sus_marcas(db, resumen.serializar(db, [campana]), pares)[0]


@router.get("/{campana_id}/reparto/vista-previa", response_model=SellOutRepartoPreviaOut)
def vista_previa_reparto(
    campana_id: int,
    criterio: RepartoCriterio = Query(...),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """What splitting a `monto_total` campaign by `criterio` gives per product, before saving it with
    `PUT /{id}/reparto` (`app.services.sell_out.criterio.vista_previa`); nothing is stored. Same rule as that
    split: only a user who sees every brand."""
    _requiere_repartir(db, user)
    if _pares_reparto(db, user) is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=service.SOLO_TODAS_LAS_MARCAS)
    campana = db.get(SellOutCampana, campana_id)
    if campana is None:
        raise _no_existe(campana_id)
    if campana.estado == "anulada":  # like `PUT /reparto`
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"La campaña {campana_id} está anulada")
    try:
        return criterio_service.vista_previa(db, campana, criterio)
    except criterio_service.CriterioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
