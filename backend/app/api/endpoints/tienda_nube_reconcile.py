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
from app.core.config import settings
from app.core.database import get_async_db, get_db
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_category_embedding import TnCategoryEmbedding
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.tn_category_embedding_service import suggest_category
from app.services.tn_publish_service import publish_product, unpublish_product
from app.services.tn_reconciliation_service import GBPFetchError, compute_verdicts, fetch_gbp_report_78

# Closed set — mirrors compute_verdicts' taxonomy minus OK (OK is never an
# actionable/filterable verdict). FastAPI/pydantic rejects any other value
# with a 422, so a typo can never be misread as "no anomalies of this type".
VerdictFilter = Literal[
    "FALTA_VINCULAR", "FALTA_PUBLICAR", "MAL_VINCULADO", "MAL_PUBLICADO", "DUPLICADO", "POR_CORREGIR"
]

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
    tn_admin_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


IMAGE_KEYS = [f"image{i}" for i in range(1, 11)]


def _gbp_images(gbp_row: Dict[str, Any]) -> List[str]:
    """Ordered `image1..image10` values, filtering out empty/null slots.

    Sub-slice 3c follow-up: exposed directly on the row response so the
    publish modal reads images off the row it already has instead of
    re-fetching the full GBP report via `/gbp-parser` and matching by EAN
    client-side.
    """
    images = []
    for key in IMAGE_KEYS:
        value = gbp_row.get(key)
        if isinstance(value, str) and value.strip():
            images.append(value)
    return images


class ReconcileRowResponse(BaseModel):
    ean: str
    verdict: str
    despublicar: bool
    tn_matches: List[TnMatchResponse]
    # TN Presence Field requirement — orthogonal to `verdict`. One of
    # `published`/`draft`/`unknown`/`not_in_tn`; see
    # `tn_reconciliation_service._compute_presence`.
    tn_presence: str = "not_in_tn"
    # FALTA_VINCULAR Exposes Matched TN IDs requirement — only populated for
    # a FALTA_VINCULAR row whose normalized SKU already resolved a TN
    # product/variant; null for every other verdict and for FALTA_VINCULAR
    # rows with no resolving match.
    product_id: Optional[int] = None
    variant_id: Optional[int] = None
    # Reason/cause taxonomy (Slice 1) — mirrored 1:1 from `ReconcileRow`.
    # Only populated for MAL_PUBLICADO (DEAD_LINK/SKU_MISMATCH) and
    # MAL_VINCULADO (NO_VARIANT_LINK); `null` for every other verdict.
    reason: Optional[str] = None
    reason_detail: Optional[dict] = None
    # Slice 4: `stock` mirrors `ReconcileRow.stock` 1:1. `None` means "not
    # reported by GBP" and MUST render/sort differently from a genuine `0`
    # (which is the value that raises `despublicar`) — see
    # `_as_optional_int`'s docstring in `tn_reconciliation_service`.
    stock: Optional[int] = None
    # Sub-slice 3c follow-up: raw GBP product fields the publish modal needs
    # (category picker text + description editor + image list), populated
    # from `ReconcileRow.gbp_row` — see `_gbp_images` above. Replaces the
    # earlier frontend workaround of re-fetching the whole report via
    # `/gbp-parser` and matching by EAN client-side.
    ml_desc: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    images: List[str] = []
    # UI-rebuild field: `ml_title` is the raw GBP `ML_title` field (for the
    # modal's editable title input). The TN admin edit-link is per-match on
    # each `TnMatchResponse.tn_admin_url` — never a single row-level link, so a
    # DUPLICADO group never privileges one conflicting row over the others.
    ml_title: Optional[str] = None


def _tn_admin_url_for(product_id: Optional[int]) -> Optional[str]:
    """Tienda Nube admin product-edit link for a given TN `product_id`, or
    `None` if `product_id` is missing or `TN_ADMIN_BASE_URL` isn't configured.

    The base URL (handle-based admin subdomain + path) is configuration, not a
    guessed pattern — it lives in `settings.TN_ADMIN_BASE_URL`; this helper only
    appends `/{product_id}`. If the setting is unset, no link is emitted rather
    than fabricating one that would 404.
    """
    if product_id is None or not settings.TN_ADMIN_BASE_URL:
        return None
    return f"{settings.TN_ADMIN_BASE_URL.rstrip('/')}/{product_id}"


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


class CategoriaSugeridaRequest(BaseModel):
    category_text: str
    top_n: int = 5

    @field_validator("category_text")
    @classmethod
    def _category_text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("category_text no puede estar vacío")
        return stripped


class CategoriaSugeridaItem(BaseModel):
    tn_category_id: int
    category_path_text: str
    similarity: float


class CategoriaSugeridaResponse(BaseModel):
    suggestions: List[CategoriaSugeridaItem]
    top: Optional[CategoriaSugeridaItem] = None


class CategoriaSearchItem(BaseModel):
    tn_category_id: int
    category_path: str


CATEGORIAS_SEARCH_DEFAULT_LIMIT = 20


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
            tn_matches=[
                TnMatchResponse(
                    product_id=tn.product_id,
                    variant_id=tn.variant_id,
                    variant_sku=tn.variant_sku,
                    activo=tn.activo,
                    published=tn.published,
                    tn_admin_url=_tn_admin_url_for(tn.product_id),
                )
                for tn in v.tn_matches
            ],
            tn_presence=v.tn_presence,
            product_id=v.product_id,
            variant_id=v.variant_id,
            reason=v.reason,
            reason_detail=v.reason_detail,
            stock=v.stock,
            ml_desc=v.gbp_row.get("ML_desc"),
            categoria=v.gbp_row.get("Categoría"),
            subcategoria=v.gbp_row.get("SubCategoría"),
            images=_gbp_images(v.gbp_row),
            ml_title=v.gbp_row.get("ML_title"),
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


@router.post("/categoria-sugerida", response_model=CategoriaSugeridaResponse)
def categoria_sugerida(
    request: CategoriaSugeridaRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Embedder-assisted TN category suggestion (sub-slice 3b — read-only,
    feeds the publish flow's category picker in sub-slice 3c).

    Reuses `admin.gestionar_tn_publicacion` — same write-gate the publish
    action itself requires, since this suggestion is only useful in that
    context. NEVER raises on embedder unavailability: `suggest_category`
    returns an empty suggestion (`suggestions=[]`, `top=None`) whenever the
    LAN embedder is down/unreachable, so the caller (3c's frontend) falls
    back to manual category search instead of seeing an error.
    """
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_publicacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la publicación de Tienda Nube")

    result = suggest_category(db, request.category_text, top_n=request.top_n)
    return CategoriaSugeridaResponse(suggestions=result["suggestions"], top=result["top"])


@router.get("/categorias", response_model=List[CategoriaSearchItem])
def buscar_categorias(
    q: str = Query("", description="Substring a buscar en el path de categoría (case-insensitive)"),
    limit: int = Query(CATEGORIAS_SEARCH_DEFAULT_LIMIT, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Plain case-insensitive substring search over
    `tn_category_embedding.category_path_text` — lets the publish modal's
    manual category picker show category NAMES instead of a raw id, without
    invoking the embedder (that's `/categoria-sugerida`, a separate
    similarity-ranked suggestion). An empty/blank `q` returns an empty list
    rather than the whole table.

    Reuses `admin.gestionar_tn_publicacion` — same write-gate as the rest of
    the publish flow this feeds.
    """
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_publicacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la publicación de Tienda Nube")

    query_text = q.strip()
    if not query_text:
        return []

    rows = (
        db.query(TnCategoryEmbedding)
        # icontains → case-insensitive (ILIKE), autoescape → treat %/_ literally.
        # `.contains(...)` alone is LIKE (case-SENSITIVE on Postgres); the search
        # is contractually case-insensitive, so it must be ILIKE.
        .filter(TnCategoryEmbedding.category_path_text.icontains(query_text, autoescape=True))
        # NOTE (scaling): the leading-`%` ILIKE cannot use a btree index and the
        # ORDER BY sorts the whole match set before `limit` cuts it. Fine for the
        # bounded TN category tree today; if it grows large, add a trigram
        # (pg_trgm) index on `category_path_text` before this becomes a hot query.
        .order_by(TnCategoryEmbedding.category_path_text)
        .limit(limit)
        .all()
    )
    return [
        CategoriaSearchItem(tn_category_id=row.tn_category_id, category_path=row.category_path_text) for row in rows
    ]
