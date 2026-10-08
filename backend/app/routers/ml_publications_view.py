"""Router: the Publicaciones management screen's reads (`/ml-publications/view/...`, design §3).

Thin on purpose: it parses the query, checks the permission, calls `services/ml_publications/view` and serializes.
No SQL here and no access to the product catalog (the base select in the view services is the one place that
joins it).

- `GET /ml-publications/view/items` (`ml_ops.ver`): one row per MLA, filters, search, sorts, optional facets and
  the honest-state block. NO PM or sub-PM scoping: the screen is a management tool over every publication.
- A query over `statement_timeout` answers 503 with the error code `consulta_lenta` (never a partial page) and
  the connection is released. Errors use the app's envelope: `{"error": {"code", "message"}}`, plus `field` on a
  422 that names the offending query parameter. Nothing here calls Mercado Libre and nothing writes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.services.ml_publications import admin, settings_store
from app.services.ml_publications.view import listing, status_block, variations
from app.services.ml_publications.view.ads import AdsCostProvider, AdsStatus, get_ads_provider, resolve_ads
from app.services.ml_publications.view.filters import (
    FilterError,
    MarkupFilter,
    parse_ads_period,
    parse_filter,
    parse_markup_filter,
)
from app.services.ml_publications.view.markup_service import AdsPlan, MarkupQuery
from app.services.ml_publications.view.timing import Timer
from app.services.permisos_service import PermisosService

PERMISO_VER = "ml_ops.ver"
PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
QUERY_CANCELED = "57014"  # Postgres' SQLSTATE for statement_timeout
SLOW_QUERY_CODE = "consulta_lenta"

router = APIRouter(prefix="/ml-publications/view", tags=["ML Publications View"])


def get_view_db(db: Session = Depends(get_db)) -> Session:
    """The session the store tables are read through: the request's own (same database as the permission check).
    A separate dependency only so a test can point the store tables elsewhere."""
    return db


def get_status_provider() -> Callable[[], dict[str, Any]]:
    """The honest-state block, from the process-wide cached report (a seam for tests)."""
    return status_block.REPORT.get


# ── Schemas ──────────────────────────────────────────────────────


class PriceOut(BaseModel):
    """Amounts are display values (`Numeric(16, 2)`, exact as a float); the markup is computed on the server (P6),
    never by the screen from these numbers."""

    amount: Optional[float] = None
    source: Optional[str] = None
    regular_amount: Optional[float] = None
    promotion_type: Optional[str] = None
    campaign: Optional[str] = None
    pricelist_id: Optional[int] = None


class StockOut(BaseModel):
    available: Optional[int] = None
    full: Optional[int] = None
    own: Optional[int] = None
    as_of: Optional[datetime] = None


class LinkOut(BaseModel):
    state: str
    producto_item_id: Optional[int] = None
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None


class AdsRowOut(BaseModel):
    """Ads of one publication over the request's period: `state` is `ok`, `sin_costo` (nothing to subtract) or
    `ads_sin_ventas` (cost but no units sold: the amount is shown, there is no per-unit cost to apply)."""

    state: str
    amount: Optional[float] = None
    units: int
    per_unit: Optional[float] = None


class MarkupOut(BaseModel):
    """Markup of a publication, in percent: the range over its variations (`min == max` when they agree), the
    worst variation (what sorting uses), whether ANY variation is negative, why it has no value (`reason`) and how
    many variations could not be priced (`partial`). With Ads applied, the figures already include it and `ads`
    says how. Only for users with `ml_metricas.ver_ganancia`."""

    min: Optional[float] = None
    max: Optional[float] = None
    worst: Optional[float] = None
    any_negative: bool
    reason: str
    partial: int
    ads: Optional[AdsRowOut] = None


class MarkupStatsOut(BaseModel):
    computed: int
    null_by_reason: dict[str, int]
    ms: float


class AdsOut(BaseModel):
    """Whether Ads cost data exists (`available`), whether this request asked to subtract it (`requested`) and
    whether it was (`applied`). The period the client sent is echoed either way.
    Only for users with `ml_metricas.ver_ganancia`."""

    available: bool
    reason: str
    requested: bool
    applied: bool
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class LastEventOut(BaseModel):
    event_type: str
    observed_at: datetime


class ItemRowOut(BaseModel):
    item_id: str
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    permalink: Optional[str] = None
    status: Optional[str] = None
    sub_status: list[str]
    listing_type_id: Optional[str] = None
    catalog_listing: Optional[bool] = None
    logistic_type: Optional[str] = None
    is_full: bool
    official_store_id: Optional[int] = None
    store_label: Optional[str] = None
    ml_brand: Optional[str] = None
    family_id: Optional[int] = None
    family_name: Optional[str] = None
    user_product_id: Optional[str] = None
    variations_count: int
    gone: bool
    gone_at: Optional[datetime] = None
    price: PriceOut
    stock: StockOut
    link: LinkOut
    last_activity_at: Optional[datetime] = None
    last_event: Optional[LastEventOut] = None  # present only while events.enabled
    markup: Optional[MarkupOut] = None  # present only with ml_metricas.ver_ganancia


class DataStateOut(BaseModel):
    """Why a column may read "—": the flags that are off, the resources the store does not collect, stale data."""

    available: bool
    reason: Optional[str] = None
    generated_at: Optional[datetime] = None
    store_empty: Optional[bool] = None
    kill_switch: Optional[bool] = None
    degraded: bool
    degradations: list[dict[str, Any]]
    sections_failed: list[str]


class ItemsResponse(BaseModel):
    items: list[ItemRowOut]
    total: int
    limit: int
    offset: int
    can_see_margin: bool
    events_enabled: bool
    data_state: DataStateOut
    facets: Optional[dict[str, Any]] = None
    markup_stats: Optional[MarkupStatsOut] = None  # present only with ml_metricas.ver_ganancia
    ads: Optional[AdsOut] = None  # present only with ml_metricas.ver_ganancia


class VariationAttributeOut(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None


class VariationLinkOut(BaseModel):
    """The product a sub-row is priced with: its own link, else the item-level one (`inherited`)."""

    state: str
    inherited: bool
    producto_item_id: Optional[int] = None
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None


class VariationCostOut(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None


class VariationMarkupOut(BaseModel):
    """Markup (percent) of one variation, after Ads when applied; `value` is null with its `reason` when it cannot
    be computed (never 0 for "unknown")."""

    value: Optional[float] = None
    reason: str


class VariationOut(BaseModel):
    variation_id: int
    seller_sku: Optional[str] = None
    user_product_id: Optional[str] = None
    available_quantity: Optional[int] = None
    sold_quantity: Optional[int] = None
    attributes: list[VariationAttributeOut]
    link: VariationLinkOut
    costo: Optional[VariationCostOut] = None  # present only with ml_metricas.ver_ganancia
    markup: Optional[VariationMarkupOut] = None  # present only with ml_metricas.ver_ganancia


class VariationsAdsOut(AdsOut):
    """The list's `ads` block plus, when Ads was applied, the publication's own figures: one cost spread per unit,
    the same on every sub-row."""

    publication: Optional[AdsRowOut] = None


class VariationsResponse(BaseModel):
    item_id: str
    can_see_margin: bool
    variations: list[VariationOut]
    ads: Optional[VariationsAdsOut] = None  # present only with ml_metricas.ver_ganancia


# ── Reads (ml_ops.ver) ───────────────────────────────────────────


def _timed_out(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "pgcode", None) == QUERY_CANCELED


def _unprocessable(exc: FilterError) -> Exception:
    error = api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_ERROR, str(exc))
    error.detail["field"] = exc.field
    return error


def _database_error(exc: DBAPIError) -> Optional[Exception]:
    """The 503 a query over `statement_timeout` answers; `None` for any other database error (re-raised)."""
    if not _timed_out(exc):
        return None
    return api_error(status.HTTP_503_SERVICE_UNAVAILABLE, SLOW_QUERY_CODE, "La consulta tardó demasiado; reintentá.")


def _ads_status(provider: AdsCostProvider, requested: bool, first: Optional[date], last: Optional[date]) -> AdsStatus:
    """Whether Ads can and will be applied to this request. Subtracting Ads needs the period, but only when there
    is Ads data to subtract: while the provider is unavailable the request is ignored and reported."""
    status_ = resolve_ads(provider, requested=requested, date_from=first, date_to=last)
    if status_.available and status_.requested and not status_.applied:
        raise FilterError("ads_desde", "restar_publicidad needs ads_desde and ads_hasta")
    return status_


def _ads_plan(provider: AdsCostProvider, status_: AdsStatus) -> Optional[AdsPlan]:
    if not status_.applied or status_.date_from is None or status_.date_to is None:
        return None
    # The store only accepts a name of `ADS_MARKUP_FORMULAS` and reads anything else as the default
    # (`test_settings_store.py`), so `apply_ads` never meets an unknown formula from here.
    formula = settings_store.get_setting("view.ads_formula").value
    return AdsPlan(provider, formula, status_.date_from, status_.date_to)


def _ads_out(status_: AdsStatus) -> dict[str, Any]:
    out: dict[str, Any] = {
        "available": status_.available,
        "reason": status_.reason,
        "requested": status_.requested,
        "applied": status_.applied,
    }
    if status_.date_from is not None and status_.date_to is not None:
        out["date_from"], out["date_to"] = status_.date_from, status_.date_to
    return out


@router.get("/items", response_model=ItemsResponse, response_model_exclude_unset=True)
def get_items(
    response: Response,
    q: Optional[str] = Query(None, description="MLA id / digits (exact), else substring of title, SKU, product"),
    estado: Optional[str] = Query(None, description="csv of active,paused,closed,under_review,inactive,gone"),
    estado_excluir: Optional[str] = None,
    tiendas: Optional[str] = Query(None, description="csv of official_store_id, or `none`"),
    marcas: Optional[str] = None,
    categorias: Optional[str] = None,
    subcategorias: Optional[str] = None,
    pms: Optional[str] = None,
    familia: Optional[str] = None,
    producto: Optional[str] = Query(None, description="one product id (a tree node's publications)"),
    sin_producto: Optional[bool] = Query(None, description="publications with no linked product (a tree node)"),
    tipo: Optional[str] = Query(None, description="csv of clasica,premium,catalogo,full"),
    vinculo: Optional[str] = Query(None, description="csv of auto,manual,sin_producto,conflicto,no_evaluado"),
    stock: Optional[str] = Query(None, description="csv of sin_stock,full_sin_stock"),
    evento: Optional[str] = Query(None, description="csv of event types; needs events.enabled"),
    evento_desde: Optional[str] = Query(None, description="24h, 7d or 30d"),
    orden: Optional[str] = Query(
        None, description="actividad (default), precio, titulo, stock_full, actualizado, markup (ver_ganancia)"
    ),
    direction: Optional[str] = Query(None, alias="dir", description="asc or desc"),
    markup_neg: Optional[bool] = Query(None, description="ANY variation negative (ver_ganancia)"),
    markup_min: Optional[str] = Query(None, description="worst variation >= this percent (ver_ganancia)"),
    markup_max: Optional[str] = Query(None, description="worst variation <= this percent (ver_ganancia)"),
    restar_publicidad: Optional[bool] = Query(None, description="markup after Ads cost (ver_ganancia)"),
    ads_desde: Optional[str] = Query(
        None, description="first day of the Ads period, YYYY-MM-DD (ver_ganancia; ignored without it)"
    ),
    ads_hasta: Optional[str] = Query(
        None, description="last day of the Ads period, YYYY-MM-DD (ver_ganancia; ignored without it)"
    ),
    limit: int = Query(listing.DEFAULT_LIMIT, ge=1, le=listing.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    facets: bool = False,
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_view_db),
    # The application session, for the permission check. In production it IS `db` (FastAPI caches `get_db`
    # within a request); it is its own parameter so the permission never rides on the store-tables test seam,
    # and it works after the `rollback()` below because a new transaction begins on first use.
    auth_db: Session = Depends(get_db),
    status_provider: Callable[[], dict[str, Any]] = Depends(get_status_provider),
    ads_provider: AdsCostProvider = Depends(get_ads_provider),
) -> dict[str, Any]:
    """One page of publications (one row per MLA) with the honest-state block."""
    timer = Timer("items")
    can_see_margin = PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA)
    asks_for_margin = bool(
        markup_neg
        or restar_publicidad
        or (markup_min or "").strip()
        or (markup_max or "").strip()
        or (orden or "").strip() == "markup"
    )  # blank values are absent parameters and the sort name is trimmed, here as in the parsers
    if not can_see_margin and asks_for_margin:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para ordenar o filtrar por markup",
        )
    try:
        f = parse_filter(
            q=q,
            estado=estado,
            estado_excluir=estado_excluir,
            tiendas=tiendas,
            marcas=marcas,
            categorias=categorias,
            subcategorias=subcategorias,
            pms=pms,
            familia=familia,
            producto=producto,
            sin_producto=sin_producto,
            tipo=tipo,
            vinculo=vinculo,
            stock=stock,
            evento=evento,
            evento_desde=evento_desde,
        )
        sort = listing.parse_sort(orden, direction)
        markup, ads_status = None, None
        if can_see_margin:
            markup_filter = parse_markup_filter(markup_neg=markup_neg, markup_min=markup_min, markup_max=markup_max)
            ads_status = _ads_status(ads_provider, bool(restar_publicidad), *parse_ads_period(ads_desde, ads_hasta))
            markup = MarkupQuery(auth_db, markup_filter, _ads_plan(ads_provider, ads_status))
        with timer.stage("flags"):
            events_enabled = settings_store.get_setting("events.enabled").value is True
        listing.bound(db)
        f = listing.resolve_pm_pairs(db, f)  # once: the list and the facets share the resolved pairs
        with timer.stage("list"):
            page = listing.list_items(db, f, sort, limit, offset, events=events_enabled, markup=markup)
        facet_counts = None
        if facets:
            with timer.stage("facets"):
                facet_counts = {**listing.facets(db, f), "total": page.total}
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    with timer.stage("status"):
        data_state = status_provider()
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(rows=len(page.items), total=page.total)
    if ads_status is not None and page.ads_failed:
        ads_status = ads_status.degraded()
    body: dict[str, Any] = {
        "items": page.items,
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "can_see_margin": can_see_margin,
        "events_enabled": events_enabled,
        "data_state": data_state,
    }
    if facet_counts is not None:
        body["facets"] = facet_counts
    if ads_status is not None:
        body["ads"] = _ads_out(ads_status)
    if page.markup_stats is not None:
        body["markup_stats"] = {
            "computed": page.markup_stats.computed,
            "null_by_reason": dict(page.markup_stats.null_by_reason),
            "ms": page.markup_stats.ms,
        }
    return body


@router.get("/items/{item_id}/variations", response_model=VariationsResponse, response_model_exclude_unset=True)
def get_item_variations(
    response: Response,
    item_id: str = Path(..., pattern=admin.ITEM_ID_PATTERN),
    restar_publicidad: Optional[bool] = Query(None, description="markup after Ads cost (ver_ganancia)"),
    ads_desde: Optional[str] = Query(None, description="first day of the Ads period, YYYY-MM-DD (ver_ganancia)"),
    ads_hasta: Optional[str] = Query(None, description="last day of the Ads period, YYYY-MM-DD (ver_ganancia)"),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),
    ads_provider: AdsCostProvider = Depends(get_ads_provider),
) -> dict[str, Any]:
    """The sub-rows of an expanded publication: per live variation its SKU, quantities, attributes and the product
    it is priced with; with `ml_metricas.ver_ganancia`, also that product's cost and the variation's markup (the
    Ads cost of the publication, per unit, applied the same way to every variation)."""
    timer = Timer("variations")
    can_see_margin = PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA)
    if not can_see_margin and restar_publicidad:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para restar la publicidad",
        )
    try:
        markup, ads_status = None, None
        if can_see_margin:
            ads_status = _ads_status(ads_provider, bool(restar_publicidad), *parse_ads_period(ads_desde, ads_hasta))
            markup = MarkupQuery(auth_db, MarkupFilter(), _ads_plan(ads_provider, ads_status))
        listing.bound(db)
        with timer.stage("variations"):
            found = variations.list_variations(db, item_id, markup)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    if found is None:
        raise api_error(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"La publicación {item_id} no existe")
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(rows=len(found.variations))
    body: dict[str, Any] = {"item_id": item_id, "can_see_margin": can_see_margin, "variations": found.variations}
    if ads_status is not None:
        if found.ads_failed:
            ads_status = ads_status.degraded()
        body["ads"] = _ads_out(ads_status)
        if found.ads is not None:
            body["ads"]["publication"] = found.ads
    return body
