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
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, get_current_user_transient
from app.core.config import settings
from app.core.database import get_async_db, get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_category_embedding import TnCategoryEmbedding
from app.models.tn_category_profile_hint import TnCategoryProfileHint
from app.models.tn_publish_override import TnPublishOverride
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.tn_category_embedding_service import suggest_category, sync_category_embeddings
from app.services.tn_publish_core import OVERRIDABLE_FIELDS, latest_usd_rate_with_date
from app.services.tn_publish_service import publish_product, unpublish_product
from app.services.tn_reconciliation_service import (
    PUBLISH_CANDIDATE_VERDICTS,
    ErpPriceInfo,
    GBPFetchError,
    _as_optional_int,
    _select_hint_profile_id,
    build_publish_draft,
    build_publish_fields,
    compute_verdicts,
    fetch_gbp_report_78,
)

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

# Slice 2 (publish price, money path) — bulk `productos_erp`/`productos_pricing`
# join that feeds `erp_by_item_id` into `compute_verdicts`. Restricted to the
# `Item_ID`s actually present in the (already-capped) GBP row set rather than
# the whole table, chunked via `_ERP_JOIN_CHUNK_SIZE` to avoid a pathological
# `IN (...)` parameter count; this cap is the belt-and-braces ceiling on top
# of that, following the same never-truncate-silently contract as
# TN_PRODUCTOS_QUERY_CAP/GBP_ROWS_CAP (see `erp_cap_hit` on the response).
# The cap COMPARISON differs from those two on purpose: they bound a SQL
# `LIMIT`, where landing exactly on the ceiling cannot rule out more rows
# existing, so they must flag conservatively with `>=`. Here the full id set
# is already in memory before the query, so `>` is exact — at exactly the cap
# nothing is dropped, and flagging would be a false alarm.
ERP_JOIN_QUERY_CAP = 50_000
_ERP_JOIN_CHUNK_SIZE = 1_000


def _gbp_item_id(gbp_row: Dict[str, Any]) -> Optional[int]:
    """Tolerant `Item_ID` parse — GBP returns numeric fields as decimal
    strings inconsistently (e.g. `"9.0000"`), so the parse must tolerate that
    shape rather than a bare `int(...)` that would raise on it.

    Delegates to the service's `_as_optional_int` instead of re-implementing
    it: two independent definitions of "how a GBP numeric field is parsed"
    agree today but are free to drift apart tomorrow, and this one feeds the
    join key for a money path."""
    return _as_optional_int(gbp_row.get("Item_ID"))


def _load_erp_price_index(db: Session, item_ids: set) -> tuple[Dict[int, ErpPriceInfo], bool]:
    """Bulk-loads the money-path fields for exactly the `Item_ID`s present in
    this request's GBP row set, one outer join covering BOTH
    `precio_web_transferencia`/`participa_web_transferencia` (surcharge base)
    and `precio_lista_ml` (Clásica manual-entry seed) — they are columns of
    the SAME `productos_pricing` row (design Decision 0/2), so this is a
    single indexed 1:1 join, not two queries. Outer join from `productos_erp`
    so an item with no pricing row still resolves (all-`None` price fields).

    Never queried per-row — `compute_verdicts` stays pure/no-db; this is the
    only DB access for the join, run inside the endpoint's existing
    `run_in_threadpool` block alongside the `tienda_nube_productos` load.
    """
    if not item_ids:
        return {}, False

    ids_list = sorted(item_ids)
    cap_hit = len(ids_list) > ERP_JOIN_QUERY_CAP
    if cap_hit:
        logger.warning(
            "ERP join item_id count reached ERP_JOIN_QUERY_CAP=%d — publish-price "
            "enrichment may be missing rows beyond the cap",
            ERP_JOIN_QUERY_CAP,
        )
        ids_list = ids_list[:ERP_JOIN_QUERY_CAP]

    index: Dict[int, ErpPriceInfo] = {}
    for start in range(0, len(ids_list), _ERP_JOIN_CHUNK_SIZE):
        chunk = ids_list[start : start + _ERP_JOIN_CHUNK_SIZE]
        rows = (
            db.query(
                ProductoERP.item_id,
                ProductoPricing.precio_web_transferencia,
                ProductoPricing.participa_web_transferencia,
                ProductoPricing.precio_lista_ml,
            )
            .outerjoin(ProductoPricing, ProductoPricing.item_id == ProductoERP.item_id)
            .filter(ProductoERP.item_id.in_(chunk))
            .all()
        )
        for item_id, precio_web_transferencia, participa_web_transferencia, precio_lista_ml in rows:
            index[item_id] = ErpPriceInfo(
                # Decimal(str(...)) at the boundary — precio_web_transferencia
                # is already Numeric(15,2) but precio_lista_ml is a raw SQL
                # Float; both are normalized identically here so neither
                # binary-float representation error nor an inconsistent type
                # propagates further into the pipeline (design Decision 0).
                precio_web_transferencia=(
                    Decimal(str(precio_web_transferencia)) if precio_web_transferencia is not None else None
                ),
                participa_web_transferencia=(
                    bool(participa_web_transferencia) if participa_web_transferencia is not None else None
                ),
                precio_lista_ml=(Decimal(str(precio_lista_ml)) if precio_lista_ml is not None else None),
            )
    return index, cap_hit


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


class PublishFieldDraftResponse(BaseModel):
    """One resolved field in a `PublishDraftResponse` (D2 — the audit
    primitive: every transmitted field can answer "why is this the value
    the operator sees" from `source` alone)."""

    value: Optional[Any] = None
    source: Literal["operator", "override", "gbp", "profile", "empty"]
    editable: bool = True


class PublishDraftResponse(BaseModel):
    """PC11/D3 (design Decision 3, task 5.19): the pre-resolved draft for a
    publish-candidate row, built server-side from the same report-78 data
    already in hand for this request — see `build_publish_draft`. `None`
    when this row isn't a publish candidate, or its report-78 extraction
    itself failed (see `publish_fields_error` on the row for that case)."""

    fields: Dict[str, PublishFieldDraftResponse]
    blocked: bool
    blocked_reasons: List[str]
    suggested_profile_id: Optional[int] = None
    exchange_rate: Optional[Dict[str, Any]] = None


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
    # Slice 5 (product-identity fallback): the GBP report's own `Descripción`
    # column — the ERP description, NOT an ML field. Verified live on report
    # 78: 1136/1136 rows carry it, while `ml_title` only covers 1091/1136 —
    # the gap is exactly the never-published-to-ML rows that otherwise render
    # as an anonymous EAN. No `productos_erp` join needed; it's already on
    # the row. `None` when GBP omits the key for this row (see
    # `parse_soap_response`'s per-row key omission, not `rows[0]`-derived).
    erp_desc: Optional[str] = None
    # Slice 2 (publish price, money path): additive fields sourced from the
    # bulk `productos_erp`/`productos_pricing` join (see
    # `_load_erp_price_index`), mirrored 1:1 from `ReconcileRow`. Both price
    # fields are serialized as STRINGS (never a JS number) so the browser's
    # float64 cannot re-introduce representation error before the operator
    # sees it — see the module's money-path design note. `null` when the
    # row's `Item_ID` didn't resolve to an ERP/pricing row.
    precio_web_transferencia: Optional[str] = None
    participa_web_transferencia: Optional[bool] = None
    precio_lista_ml: Optional[str] = None
    # PR-3 (tn-publish-core foundation, PC1/PC2/PC3): full publish field set
    # sourced through the strict extract -> resolve conversion layer (see
    # `_publish_fields_for_row`), replacing the earlier discard where the
    # row only carried a hand-picked subset of `gbp_row`. Only populated for
    # publish-candidate verdicts (FALTA_PUBLICAR/FALTA_VINCULAR) — `None`
    # for every other verdict, and also `None` when this specific row's
    # report-78 data was incomplete (see `_publish_fields_for_row`'s
    # graceful degradation). `cost` is RAW, pre-currency-conversion — D6
    # (USD->ARS) lands in PR-5.
    marca: Optional[str] = None
    cost: Optional[str] = None
    barcode: Optional[str] = None
    promotional_price: Optional[str] = None
    weight_kg: Optional[float] = None
    width_cm: Optional[float] = None
    depth_cm: Optional[float] = None
    height_cm: Optional[float] = None
    # D13: explicit, machine-readable signal that THIS row's extraction hit
    # `MissingReportFieldError` (a report-78 schema break), distinct from a
    # row whose measurements are genuinely absent (which leaves this
    # `None` but the fields above still populate/resolve normally). PR-5's
    # D3 blocked-publication gate must be able to tell the two apart from
    # the response alone, not only from the service's warning log.
    publish_fields_error: Optional[str] = None
    # PR-5b (task 5.19, design Decision 3): the resolved draft envelope for
    # a publish-candidate row (precedence-resolved measurements + cost,
    # D3's blocked/blocked_reasons). `None` for every non-candidate verdict
    # AND for a candidate row whose draft assembly itself failed — same
    # per-row containment as `publish_fields_error` above, never a 500 for
    # the whole report.
    publish_draft: Optional[PublishDraftResponse] = None


def _safe_publish_draft(
    row: Any,
    overrides_by_ean: Dict[str, Dict[str, str]],
    usd_rate: Optional[float],
    usd_rate_date: Optional[Any] = None,
    suggested_profile_id: Optional[int] = None,
) -> Optional[PublishDraftResponse]:
    """Per-row containment for `build_publish_draft` (task 5.19): a draft
    assembly failure (e.g. an unexpected exception from the resolver) must
    degrade to `None` for THIS row only, never 500 the whole `/reporte`
    response — same pattern `build_publish_fields`'s caller already relies
    on for `publish_fields_error`. Takes no DB session: everything row-rate
    related (`usd_rate`, overrides, `suggested_profile_id`) was bulk-loaded
    once by the caller."""
    try:
        draft = build_publish_draft(
            row,
            overrides_by_ean.get(row.ean, {}),
            usd_rate,
            usd_rate_date=usd_rate_date,
            suggested_profile_id=suggested_profile_id,
        )
    except Exception:
        logger.exception("publish_draft assembly failed for ean=%s — omitting draft for this row only", row.ean)
        return None
    if draft is None:
        return None
    return PublishDraftResponse(**draft)


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
    erp_cap_hit: bool


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
    """PC11/D7's typed publish request. design.md's Interfaces/Contracts
    section specifies this as REPLACING `product_data: Dict[str, Any]`
    outright with fully-typed operator-intent fields (`overrides`,
    `profile_id`, `visibility`, `free_shipping`, `seo_*`, `tags`, `price`).

    As-built deviation (PR-5b, task 5.18): `product_data` is kept, not
    removed. `TnPublishModal.jsx` still sends the OLD wire shape
    (`product_data: {name: {es}, price}`) until PR-7 rebuilds it against
    this typed model — an SDD PR must not break the live modal publish flow
    (`_publish_kwargs`'s `product_data` remains `publish_product`'s
    documented product-shape parameter; see that module's docstring). The
    NEW typed fields below are additive: they are accepted now so the
    backend pipeline (override persistence, PC5/D8) is wired end-to-end,
    and PR-7 switches the frontend to send them instead of `product_data`
    without requiring another backend contract change.
    """

    ean: str
    product_data: Dict[str, Any]
    category_id: int
    description_html: str
    image_srcs: List[str] = []
    # Slice 2 (publish price, money path) — audit-only traceability fields;
    # the actual price lives in `product_data["price"]` (validated by
    # `tn_publish_service.publish_product`'s containment guard, NOT
    # recomputed here — there is no server-side pricing constant to check
    # it against, see that module's docstring). `offset_percent` is the
    # modal-local surcharge preset in effect when the surcharge path was
    # used (`None` on the manual-entry path). `price_base_source` records
    # which business quantity the operator was looking at.
    offset_percent: Optional[float] = None
    # Only the two sources a caller can actually be in: the surcharge path, or
    # operator-typed. The Clásica price is NOT a third source — it merely SEEDS
    # the manual field, and the operator is free to overwrite it before
    # submitting, so recording it as its own origin would misreport what the
    # number actually is.
    price_base_source: Optional[Literal["web_transferencia", "manual"]] = None
    # design's typed model (PC5/D8, task 5.4/5.5): operator-edited fields,
    # keyed by field name. Keys are validated by `_overrides_keys_must_be_known`
    # below against `tn_publish_core.OVERRIDABLE_FIELDS` (an unknown key is a
    # 422, never silently persisted), and `_upsert_publish_overrides` filters
    # against the same tuple as defense in depth.
    # Persisted into `tn_publish_override` ONLY on a `submitted` outcome.
    # Defaults to `{}` — the current modal sends nothing here yet (PR-7).
    overrides: Dict[str, str] = {}
    # The COMPLETE resolved measurement set the modal was showing — what to
    # PUBLISH. Distinct from `overrides`, which is dirty-only (what the
    # operator edited, and therefore what may be persisted). Reading the D3
    # gate off `overrides` would fail-close every publish where nothing was
    # edited, i.e. the happy path.
    measurements: Dict[str, str] = {}
    # GBP's own currency for this row's cost — a report fact, not an operator
    # input. The backend needs it to decide whether a missing `TipoCambio`
    # must block the publish (D6/PC8); the RATE itself is always read
    # server-side, never trusted from the client.
    moneda_costo: Optional[str] = None
    profile_id: Optional[int] = None
    # PR-8 gap A/B: the GBP category/subcategory for this row — forwarded so
    # `publish_product` can write the `tn_category_profile_hint` usage row on
    # a successful publish where `profile_id` was applied. Report facts, not
    # operator input — same status as `moneda_costo` above.
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None

    @field_validator("overrides", "measurements")
    @classmethod
    def _overrides_keys_must_be_known(cls, value: Dict[str, str]) -> Dict[str, str]:
        unknown = sorted(set(value) - set(OVERRIDABLE_FIELDS))
        if unknown:
            raise ValueError(
                f"Campos de override desconocidos: {', '.join(unknown)}. Permitidos: {', '.join(OVERRIDABLE_FIELDS)}"
            )
        return value

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
    # Defect fix: distinct from `skipped_image_srcs` (never sent to TN at
    # all — failed the local reachability guard). An image src that WAS
    # sent but rejected by TN with a 429 lands here instead — reported to
    # the operator for a manual retry rather than being silently dropped.
    rate_limited_image_srcs: List[str] = []
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


class CategoriaSyncResponse(BaseModel):
    synced: int
    skipped: bool
    reason: Optional[str] = None


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
        item_ids = {iid for row in gbp_rows if (iid := _gbp_item_id(row)) is not None}
        erp_by_item_id, erp_cap_hit = _load_erp_price_index(db, item_ids)
        verdicts = compute_verdicts(gbp_rows, tn_productos, banned_eans=banned_eans, erp_by_item_id=erp_by_item_id)
        # Decision 3: overrides loaded as ONE bulk query
        # (`WHERE ean IN (...)`), never per row — scoped to only the
        # publish-candidate EANs actually present in this report.
        candidate_rows = [v for v in verdicts if v.verdict in PUBLISH_CANDIDATE_VERDICTS]
        candidate_eans = {v.ean for v in candidate_rows}
        overrides_by_ean: Dict[str, Dict[str, str]] = {}
        if candidate_eans:
            for override_row in db.query(TnPublishOverride).filter(TnPublishOverride.ean.in_(candidate_eans)).all():
                overrides_by_ean.setdefault(override_row.ean, {})[override_row.campo] = override_row.valor
        # Decision 3: the USD exchange rate is resolved ONCE per report
        # (1-2 `TipoCambio` queries total) and handed to every draft as a
        # value+date pair (PR-7 gap fix, task B) — ~99% of report rows are
        # USD-costed, so a per-row lookup would multiply into hundreds of
        # queries per `/reporte` on this checked-out pooled connection (see
        # the pool-exhaustion history in this module's docstring).
        usd_rate_with_date = latest_usd_rate_with_date(db) if candidate_rows else None
        usd_rate = usd_rate_with_date[0] if usd_rate_with_date is not None else None
        usd_rate_date = usd_rate_with_date[1] if usd_rate_with_date is not None else None
        # Decision 3 (PR-7 gap fix, task C): the D11 category-profile hints
        # are bulk-loaded ONCE (`WHERE categoria IN (...)`), never one
        # `TnCategoryProfileHint` query per row — mirrors the overrides/
        # usd_rate bulk pattern above. Ordered so the FIRST row seen per
        # `(categoria, subcategoria)` key is the highest-`uso_count` winner
        # (ties broken by lowest id), exactly like `sugerir_perfil`'s query.
        candidate_categorias = {v.gbp_row.get("Categoría") for v in candidate_rows if v.gbp_row.get("Categoría")}
        hints_by_key: Dict[Any, int] = {}
        if candidate_categorias:
            hint_rows = (
                db.query(TnCategoryProfileHint)
                .filter(TnCategoryProfileHint.categoria.in_(candidate_categorias))
                .order_by(
                    TnCategoryProfileHint.categoria,
                    TnCategoryProfileHint.subcategoria,
                    TnCategoryProfileHint.uso_count.desc(),
                    TnCategoryProfileHint.id,
                )
                .all()
            )
            for hint in hint_rows:
                key = (hint.categoria, hint.subcategoria)
                hints_by_key.setdefault(key, hint.profile_id)
        # Decision 3: drafts are also built HERE, inside the same
        # threadpool call as the bulk queries above — never on the event
        # loop thread, matching this module's existing pool-safety pattern
        # for `/reporte`.
        drafts_by_ean: Dict[str, Optional[PublishDraftResponse]] = {
            v.ean: _safe_publish_draft(
                v,
                overrides_by_ean,
                usd_rate,
                usd_rate_date=usd_rate_date,
                suggested_profile_id=_select_hint_profile_id(
                    hints_by_key, v.gbp_row.get("Categoría"), v.gbp_row.get("SubCategoría")
                ),
            )
            for v in candidate_rows
        }
        return verdicts, cap_hit, erp_cap_hit, drafts_by_ean

    # Sync DB query + CPU-bound verdict computation off the event loop —
    # this is the only `async def` in the module, so without this it would
    # block every other request for the whole computation window.
    verdicts, cap_hit, erp_cap_hit, drafts_by_ean = await run_in_threadpool(_load_and_compute)

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
            erp_desc=v.gbp_row.get("Descripción"),
            precio_web_transferencia=(
                str(v.precio_web_transferencia) if v.precio_web_transferencia is not None else None
            ),
            participa_web_transferencia=v.participa_web_transferencia,
            precio_lista_ml=(str(v.precio_lista_ml) if v.precio_lista_ml is not None else None),
            publish_draft=drafts_by_ean.get(v.ean),
            **build_publish_fields(v),
        )
        for v in filtered
    ]

    return ReconcileReportResponse(
        items=items,
        total=len(filtered),
        verdict_counts=verdict_counts,
        catalog_cap_hit=cap_hit,
        gbp_rows_cap_hit=gbp_rows_cap_hit,
        erp_cap_hit=erp_cap_hit,
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

    Money-path guard (Slice 2): `publish_product` rejects an absent,
    non-numeric or non-positive `product_data["price"]` with
    `status="rejected_invalid_price"` BEFORE any TN call — that status is
    surfaced here as a 4xx (unlike every other rejection status, which
    returns 200 with `submitted=False`), per the spec's explicit requirement
    that an invalid price is a hard validation failure, not a soft outcome.
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
        offset_percent=request.offset_percent,
        price_base_source=request.price_base_source,
        overrides=request.overrides,
        measurements=request.measurements,
        moneda_costo=request.moneda_costo,
        profile_id=request.profile_id,
        categoria=request.categoria,
        subcategoria=request.subcategoria,
    )
    if outcome["status"] in ("rejected_invalid_price", "blocked_measurements", "blocked_cost"):
        raise HTTPException(status_code=400, detail=outcome.get("detail"))
    return PublicarResponse(
        submitted=outcome["submitted"],
        status=outcome["status"],
        product_id=outcome.get("product_id"),
        skipped_image_srcs=outcome.get("skipped_image_srcs", []),
        rate_limited_image_srcs=outcome.get("rate_limited_image_srcs", []),
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
    similarity-ranked suggestion). An empty/blank `q` returns a bounded,
    alphabetically-ordered first page of the whole table instead of `[]` —
    a search-only picker with nothing to browse is unusable when the
    operator doesn't already know the category vocabulary. A genuinely
    empty catalog still returns `[]`; the frontend uses that as the signal
    to distinguish "never synced" from "no rows match your query".

    Reuses `admin.gestionar_tn_publicacion` — same write-gate as the rest of
    the publish flow this feeds.
    """
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_publicacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la publicación de Tienda Nube")

    query_text = q.strip()

    rows_query = db.query(TnCategoryEmbedding)
    if query_text:
        # icontains → case-insensitive (ILIKE), autoescape → treat %/_ literally.
        # `.contains(...)` alone is LIKE (case-SENSITIVE on Postgres); the search
        # is contractually case-insensitive, so it must be ILIKE.
        rows_query = rows_query.filter(TnCategoryEmbedding.category_path_text.icontains(query_text, autoescape=True))

    rows = (
        rows_query
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


@router.post("/categorias/sync", response_model=CategoriaSyncResponse)
def sync_categorias(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Operator-triggered refresh of `tn_category_embedding` (PR-1,
    tn-publisher-module — design Decision 8). Wiring only: delegates to the
    already-implemented, already-tested `sync_category_embeddings()`, never
    modified by this endpoint.

    Reuses `admin.gestionar_tn_publicacion` — sync is maintenance on the
    publish path, not a distinct capability (minimalism ladder rung 2, no
    new permission for this PR).
    """
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_publicacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la publicación de Tienda Nube")

    result = sync_category_embeddings(db)
    return CategoriaSyncResponse(synced=result["synced"], skipped=result["skipped"], reason=result.get("reason"))
