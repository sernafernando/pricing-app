"""Endpoints for TN Reconcile & Publish — Slice 1 (read-only reconciliation view).

Fetches GBP export report 78, joins it against `tienda_nube_productos` on
EAN, and returns a live-computed verdict per row (nothing is persisted except
the ban list). Mirrors `items_sin_mla.py`'s shape: explicit response models,
permission gating via `verificar_permiso`.

Pool-safety note (`/reporte` only): this endpoint's own `db` session genuinely
IS held open for the whole request, including the awaited GBP SOAP
round-trip — FastAPI's dependency generator only closes it when the handler
returns. That connection-hold window is bounded to `GBP_FETCH_TIMEOUT_SECONDS`
(NOT the 300s/~600s-with-retry default `call_soap_service` would otherwise
inherit). It uses `Depends(get_async_db)`, NOT `Depends(get_db)` (used by the
other three endpoints here, which are plain `def` and never await anything
long-lived): `get_async_db`'s `finally: db.close()` is guaranteed to run in
the async context even if the coroutine is cancelled mid-await (e.g. the
client disconnects during the up-to-60s SOAP wait) — `get_db` is a sync
generator FastAPI runs in its threadpool, where a cancelled coroutine can skip
the `finally` and leak the connection back to the pool as still-checked-out
(see `app/core/database.py`'s own docstring on `get_async_db`). Authentication
uses `get_current_user_transient` instead of `get_current_user` specifically
so it does NOT ALSO hold a SECOND connection open for that same window
(`get_current_user` depends on `get_async_db` itself, a separate pooled
session that stays open for the whole request just like this endpoint's own
`db` does). The sync DB query + `compute_verdicts` CPU work run inside
`run_in_threadpool` so they never block the event loop for other requests
while they execute — this endpoint is the only `async def` in the module; the
other three are plain `def` and FastAPI already runs those in its threadpool
automatically.

One-shot fetch, no server-side pagination (third review round): `/reporte` is
called ONCE per explicit load/refresh, never per page/sub-tab navigation —
the frontend fetches the full verdict set and paginates/filters client-side.
Earlier server-side `page`/`page_size` params meant every page click or
sub-tab switch re-ran the full SOAP fetch + DB load, reproducing the exact
pool-exhaustion shape an earlier round had just fixed; server pagination
trimmed the payload but not the repeated work. `verdict` still optionally
filters WHICH verdict subset is returned (validated against the closed
verdict taxonomy — an unknown value is a 422, never a silently-empty "no
anomalies of this type" result), and `verdict_counts` always reports the
TRUE count per verdict across the WHOLE result set regardless of that filter.

Scaling note: BOTH sides of the join are bounded, not just one. The internal
`tienda_nube_productos` query is bounded by `TN_PRODUCTOS_QUERY_CAP`, ordered
by `id` so which rows you get under the cap is at least deterministic;
`catalog_cap_hit` reports whether that ceiling was reached. The GBP side
(`fetch_gbp_report_78()`'s rows, which have no bound of their own) is
likewise capped by `GBP_ROWS_CAP`, reported via `gbp_rows_cap_hit` — one-shot
fetch (no server pagination) is NOT the same as unbounded: without this cap,
a large report 78 would assemble a multi-MB JSON response (with nested
`tn_matches`) in memory while the pooled connection above is still held.
Neither cap ever truncates silently — both flags surface a possibly-partial
reconciliation to the caller instead of a silent partial one.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, get_current_user_transient
from app.core.database import get_async_db, get_db
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.tn_publish_service import publish_product, unpublish_product
from app.services.tn_reconciliation_service import GBPFetchError, compute_verdicts, fetch_gbp_report_78

# Closed set — mirrors compute_verdicts' taxonomy minus OK (OK is never an
# actionable/filterable verdict). FastAPI/pydantic rejects any other value
# with a 422, so a typo can never be misread as "no anomalies of this type".
VerdictFilter = Literal["FALTA_VINCULAR", "FALTA_PUBLICAR", "MAL_VINCULADO", "MAL_PUBLICADO", "DUPLICADO"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tienda-nube-reconcile", tags=["tienda-nube-reconcile"])

# Explicit ceiling on the internal TN catalog query — a full-table load with
# no bound is exactly the kind of unbounded-query pattern that has caused
# pool exhaustion in this repo before. If the table ever reaches this size,
# reconciliation may miss matches beyond the cap; this is a known Slice 1
# scaling limit, logged loudly rather than silently truncated.
TN_PRODUCTOS_QUERY_CAP = 50_000

# Mirrors TN_PRODUCTOS_QUERY_CAP for the OTHER side of the join — the GBP
# rows from `fetch_gbp_report_78()` have no bound of their own. One-shot
# fetch (no server pagination) is not the same as unbounded: without this,
# a large report 78 assembles a multi-MB JSON (with nested `tn_matches`)
# in memory while the pooled connection is still held for the request
# (see the module docstring's pool-safety note). Same contract as the
# catalog cap: reported via `gbp_rows_cap_hit`, never silently truncated.
GBP_ROWS_CAP = 50_000


class TnMatchResponse(BaseModel):
    product_id: int
    variant_id: int
    variant_sku: Optional[str]
    activo: Optional[bool] = None
    published: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ReconcileRowResponse(BaseModel):
    ean: str
    verdict: str
    despublicar: bool
    tn_matches: List[TnMatchResponse]


class ReconcileReportResponse(BaseModel):
    items: List[ReconcileRowResponse]
    total: int
    verdict_counts: Dict[str, int]
    catalog_cap_hit: bool
    gbp_rows_cap_hit: bool


class BanEanRequest(BaseModel):
    ean: str
    motivo: Optional[str] = None

    @field_validator("ean")
    @classmethod
    def _ean_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El EAN no puede estar vacío")
        return stripped


class UnbanEanRequest(BaseModel):
    banlist_id: int


class BanEanResponse(BaseModel):
    success: bool
    message: str
    banlist_id: int


class UnbanEanResponse(BaseModel):
    success: bool
    message: str


class BanlistEntryResponse(BaseModel):
    id: int
    ean: str
    motivo: Optional[str]
    usuario_nombre: str
    fecha_creacion: str

    model_config = ConfigDict(from_attributes=True)


class DespublicarRequest(BaseModel):
    product_id: int


class DespublicarResponse(BaseModel):
    submitted: bool
    status: str
    detail: Optional[str] = None


class PublicarRequest(BaseModel):
    ean: str
    product_data: Dict[str, Any]
    category_id: int
    description_html: str
    image_srcs: List[str] = []

    @field_validator("ean")
    @classmethod
    def _ean_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El EAN no puede estar vacío")
        return stripped


class PublicarResponse(BaseModel):
    submitted: bool
    status: str
    product_id: Optional[int] = None
    skipped_image_srcs: List[str] = []
    detail: Optional[str] = None


@router.get("/reporte", response_model=ReconcileReportResponse)
async def get_reconciliation_report(
    verdict: Optional[VerdictFilter] = Query(None, description="Filtra a un solo veredicto; omitir = todos excepto OK"),
    db: Session = Depends(get_async_db),
    current_user: Usuario = Depends(get_current_user_transient),
):
    """One-shot reconciliation report: GBP report 78 joined against TN on EAN.

    Nothing here is persisted — verdicts are recomputed on every call. Any
    GBP fetch failure surfaces a clear 502 to the operator with no partial
    write (Graceful Degradation requirement). Call this ONCE per explicit
    load/refresh, never per page/sub-tab navigation — there is no server-side
    pagination; the full (optionally verdict-filtered) result set is returned
    in one response, and `verdict_counts`/`catalog_cap_hit` always describe
    the WHOLE underlying set regardless of the `verdict` filter.
    """
    has_permission = await run_in_threadpool(verificar_permiso, db, current_user, "admin.ver_tn_reconciliacion")
    if not has_permission:
        raise HTTPException(status_code=403, detail="No tienes permiso para ver la reconciliación de Tienda Nube")

    try:
        gbp_rows = await fetch_gbp_report_78()
    except GBPFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    gbp_rows_cap_hit = len(gbp_rows) >= GBP_ROWS_CAP
    if gbp_rows_cap_hit:
        logger.warning(
            "GBP report 78 row count reached GBP_ROWS_CAP=%d — reconciliation may be missing rows beyond the cap",
            GBP_ROWS_CAP,
        )
        gbp_rows = gbp_rows[:GBP_ROWS_CAP]

    def _load_and_compute():
        tn_productos = db.query(TiendaNubeProducto).order_by(TiendaNubeProducto.id).limit(TN_PRODUCTOS_QUERY_CAP).all()
        cap_hit = len(tn_productos) >= TN_PRODUCTOS_QUERY_CAP
        if cap_hit:
            logger.warning(
                "tienda_nube_productos row count reached TN_PRODUCTOS_QUERY_CAP=%d — "
                "reconciliation may be missing matches beyond the cap",
                TN_PRODUCTOS_QUERY_CAP,
            )
        banned_eans = {row.ean for row in db.query(TnReconcileBanlist.ean).all()}
        return compute_verdicts(gbp_rows, tn_productos, banned_eans=banned_eans), cap_hit

    # Sync DB query + CPU-bound verdict computation off the event loop —
    # this is the only `async def` in the module, so without this it would
    # block every other request for the whole computation window.
    verdicts, cap_hit = await run_in_threadpool(_load_and_compute)

    verdict_counts: Dict[str, int] = dict(Counter(v.verdict for v in verdicts if v.verdict != "OK"))

    if verdict:
        filtered = [v for v in verdicts if v.verdict == verdict]
    else:
        filtered = [v for v in verdicts if v.verdict != "OK"]

    items = [
        ReconcileRowResponse(
            ean=v.ean,
            verdict=v.verdict,
            despublicar=v.despublicar,
            tn_matches=[TnMatchResponse.model_validate(tn) for tn in v.tn_matches],
        )
        for v in filtered
    ]

    return ReconcileReportResponse(
        items=items,
        total=len(filtered),
        verdict_counts=verdict_counts,
        catalog_cap_hit=cap_hit,
        gbp_rows_cap_hit=gbp_rows_cap_hit,
    )


@router.get("/baneados", response_model=List[BanlistEntryResponse])
def get_banlist(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_reconcile_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de reconciliación TN")

    baneados = (
        db.query(TnReconcileBanlist, Usuario)
        .join(Usuario, Usuario.id == TnReconcileBanlist.usuario_id)
        .order_by(TnReconcileBanlist.fecha_creacion.desc())
        .all()
    )

    return [
        BanlistEntryResponse(
            id=entry.id,
            ean=entry.ean,
            motivo=entry.motivo,
            usuario_nombre=usuario.nombre,
            fecha_creacion=entry.fecha_creacion.isoformat(),
        )
        for entry, usuario in baneados
    ]


@router.post("/banear", response_model=BanEanResponse)
def banear_ean(
    request: BanEanRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_reconcile_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de reconciliación TN")

    existente = db.query(TnReconcileBanlist).filter(TnReconcileBanlist.ean == request.ean).first()
    if existente:
        raise HTTPException(status_code=400, detail="El EAN ya está en la banlist")

    nuevo_ban = TnReconcileBanlist(ean=request.ean, motivo=request.motivo, usuario_id=current_user.id)
    db.add(nuevo_ban)
    try:
        db.commit()
    except IntegrityError:
        # TOCTOU guard: a concurrent request may have inserted the same EAN
        # between the existence check above and this commit. The unique
        # index is the real guarantee — this just turns the resulting
        # constraint violation into the intended 400 instead of a 500.
        db.rollback()
        raise HTTPException(status_code=400, detail="El EAN ya está en la banlist") from None
    db.refresh(nuevo_ban)

    return {"success": True, "message": f"EAN {request.ean} agregado a la banlist", "banlist_id": nuevo_ban.id}


@router.post("/desbanear", response_model=UnbanEanResponse)
def desbanear_ean(
    request: UnbanEanRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_reconcile_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de reconciliación TN")

    ban_entry = db.query(TnReconcileBanlist).filter(TnReconcileBanlist.id == request.banlist_id).first()
    if not ban_entry:
        raise HTTPException(status_code=404, detail="Entrada de banlist no encontrada")

    ean = ban_entry.ean
    db.delete(ban_entry)
    db.commit()

    return {"success": True, "message": f"EAN {ean} removido de la banlist"}


@router.post("/despublicar", response_model=DespublicarResponse)
def despublicar_producto(
    request: DespublicarRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Explicit, operator-triggered unpublish of ONE TN product
    (`published: false`). NEVER bulk, NEVER automatic — the spec's
    non-goals forbid automatic bulk actions; this endpoint always acts on
    exactly the single `product_id` in the request body.

    Delegates the fresh-read-before-write / no-retry-on-ambiguous /
    audit-logged write itself to `tn_publish_service.unpublish_product` —
    see that module's docstring for the write-safety contract.
    """
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_publicacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la publicación de Tienda Nube")

    outcome = unpublish_product(db, current_user, request.product_id)
    return DespublicarResponse(submitted=outcome["submitted"], status=outcome["status"], detail=outcome.get("detail"))


@router.post("/publicar", response_model=PublicarResponse)
def publicar_producto(
    request: PublicarRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Explicit, operator-triggered creation of ONE TN product from
    GBP-derived data. NEVER bulk, NEVER automatic — same non-goal as
    `/despublicar`; this endpoint always acts on exactly the single `ean` in
    the request body. Reuses `admin.gestionar_tn_publicacion` (the same
    write-gate as unpublish, per design intent of one shared permission).

    Delegates the idempotency check / single-shot create / image attach /
    audit-logged write itself to `tn_publish_service.publish_product` — see
    that module's docstring for the write-safety contract, including the
    documented defense-in-depth note on `description_html`.
    """
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_publicacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la publicación de Tienda Nube")

    outcome = publish_product(
        db,
        current_user,
        ean=request.ean,
        product_data=request.product_data,
        category_id=request.category_id,
        description_html=request.description_html,
        image_srcs=request.image_srcs,
    )
    return PublicarResponse(
        submitted=outcome["submitted"],
        status=outcome["status"],
        product_id=outcome.get("product_id"),
        skipped_image_srcs=outcome.get("skipped_image_srcs", []),
        detail=outcome.get("detail"),
    )
