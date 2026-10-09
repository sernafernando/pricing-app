"""Router: the Publicaciones management screen's reads (`/ml-publications/view/...`, design §3).

Thin on purpose: it parses the query, checks the permission, calls `services/ml_publications/view` and serializes.
No SQL here and no access to the product catalog (the base select in the view services is the one place that
joins it).

- `GET /ml-publications/view/items` (`ml_ops.ver`): one row per MLA, filters, search, sorts, optional facets and
  the honest-state block. NO PM or sub-PM scoping: the screen is a management tool over every publication.
- `GET /ml-publications/view/groups` (`ml_ops.ver`): the children of one node of the Agrupado tree (marca >
  categoria > subcategoria > producto > [familia]), with the same filters as `/items`; the publications of a leaf node
  come from `/items` with the node's `params`.
- `GET /ml-publications/view/items/{item_id}` (`ml_ops.ver`): the Resumen of one publication, all its data; the cost of
  the product and the markup breakdown only with `ml_metricas.ver_ganancia`, `can_resync` from `ml_ops.gestionar`.
- `GET /ml-publications/view/items/{item_id}/events` (`ml_ops.ver`): the publication's business events from
  `ml_item_events`, newest first, keyset-paged by an opaque cursor; an empty list while `events.enabled` is off.
- `GET /ml-publications/view/items/{item_id}/history` (`ml_ops.ver`): its `ml_change_log` rows (and those of its user
  product and family), one entry per row with the business fields apart from the technical ones.
- `GET /ml-publications/view/kpis` (`ml_ops.ver` AND `ml_metricas.ver`): Métricas ML's KPI strip over the MLAs the same
  filters select, for its own period (`periodo` 7/15/30/60/90 or `desde`/`hasta`, default the last 30 days) and
  `comparar_con`. The profit figures only with `ml_metricas.ver_ganancia` (omitted otherwise). No PM scoping.
- A query over `statement_timeout` answers 503 with the error code `consulta_lenta` (never a partial page) and
  the connection is released. Errors use the app's envelope: `{"error": {"code", "message"}}`, plus `field` on a
  422 that names the offending query parameter. Nothing here calls Mercado Libre and nothing writes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.routers import ml_metricas
from app.services.ml_daily_metrics import board
from app.services.ml_publications import admin, settings_store
from app.services.ml_publications.view import (
    detail,
    events_view,
    groups,
    history,
    kpis,
    listing,
    status_block,
    variations,
)
from app.services.ml_publications.view.ads import AdsCostProvider, AdsStatus, get_ads_provider, resolve_ads
from app.services.ml_publications.view.filters import (
    FilterError,
    MarkupFilter,
    PublicationFilter,
    parse_ads_period,
    parse_filter,
    parse_markup_filter,
)
from app.services.ml_publications.view.markup_service import AdsPlan, MarkupQuery
from app.services.ml_publications.view.timing import Timer
from app.services.permisos_service import PermisosService

PERMISO_VER = "ml_ops.ver"
PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
PERMISO_METRICAS = ml_metricas.PERMISO_VER  # the KPI strip is Métricas' numbers: seeing them needs seeing Métricas
PERMISO_GESTIONAR = "ml_ops.gestionar"  # what lets the screen offer "Resincronizar"
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


class StockLocationOut(BaseModel):
    type: str
    quantity: int


class ReplenishmentOut(BaseModel):
    """Full replenishment of the publication's user product; `status` is `ok`, `partial` (a 206: `content_missing`
    names what ML did not send), `not_found`, `error` or `never_fetched` (nothing stored yet: every figure is null).
    The whole block is null when the publication is not Full."""

    status: str
    content_missing: Optional[str] = None
    period: Optional[str] = None
    units_30d: Optional[int] = None
    gmv_30d: Optional[float] = None
    currency: Optional[str] = None
    units_7d: Optional[int] = None
    units_14d: Optional[int] = None
    units_21d: Optional[int] = None
    days_out_of_stock_21d: Optional[int] = None
    shipping_urgency: Optional[str] = None
    total_stock: Optional[int] = None
    minimum_distributable_stock: Optional[int] = None
    history_through: Optional[date] = None
    fetched_at: Optional[datetime] = None


class DetailLinkOut(BaseModel):
    """The link of one unit (`variation_id` 0 is the item level) and the product it points at (null when the link
    has none or the product vanished)."""

    variation_id: int
    state: str
    source: Optional[str] = None
    match_status: str
    producto_item_id: Optional[int] = None
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    matched_sku: Optional[str] = None
    sku_field: Optional[str] = None
    suggested_producto_item_id: Optional[int] = None
    suggestion_status: Optional[str] = None
    linked_at: Optional[datetime] = None
    note: Optional[str] = None


class DetailProductOut(BaseModel):
    """The product of the item-level link. `precios_lista` is by pricelist id (4 classic, 17/14/13/23 = 3/6/9/12
    installments). `costo`, `moneda_costo` and `iva` appear only with `ml_metricas.ver_ganancia`."""

    item_id: int
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    subcategoria: Optional[str] = None
    precios_lista: dict[str, Optional[float]]
    costo: Optional[float] = None
    moneda_costo: Optional[str] = None
    iva: Optional[float] = None


class MarkupBreakdownOut(BaseModel):
    """How the markup of the publication's worst unit is made (`variation_id` null: the item-level unit): the price
    and where it comes from, the list that prices it and its installments, the commission (percent and amount), the
    shipping cost and its source, the net, the cost in pesos and the markup (percent). Only for users with
    `ml_metricas.ver_ganancia`; null when no unit could be priced (the row's `markup.reason` says why)."""

    variation_id: Optional[int] = None
    price: float
    price_source: str
    pricelist_id: int
    installments: Optional[int] = None
    comision_pct: float
    comision_total: float
    costo_envio: float
    envio_source: str
    limpio: float
    costo_ars: float
    markup: float


class FreshnessOut(BaseModel):
    """How fresh one stored resource is: `ok`, `not_found`, `error`, `gone` (the publication itself) or
    `never_fetched`."""

    resource: str
    state: str
    fetched_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    http_status: Optional[int] = None


class ItemDetailResponse(BaseModel):
    """`row` is the list's row for this publication; `item` holds every `ml_items` column but the body (`raw`) and its
    hash; `extra` is the whitelisted part of the body (see `view/detail.py`). The variations are not here: they are
    `/items/{item_id}/variations`."""

    row: ItemRowOut
    item: dict[str, Any]
    extra: dict[str, Any]
    sub_status: list[str]
    tags: list[str]
    health: Optional[float] = None
    condition: Optional[str] = None
    date_created: Optional[datetime] = None
    ml_last_updated: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    stock_locations: Optional[list[StockLocationOut]] = None
    stock_as_of: Optional[datetime] = None
    replenishment: Optional[ReplenishmentOut] = None
    links: list[DetailLinkOut]
    product: Optional[DetailProductOut] = None
    markup_breakdown: Optional[MarkupBreakdownOut] = None  # present only with ml_metricas.ver_ganancia
    freshness: list[FreshnessOut]
    can_resync: bool


class EventOut(BaseModel):
    """One business event of the publication; `label` is its Spanish name (a generic one for a type without its
    own), `old_value`/`new_value` what the rule that derived it recorded."""

    id: int
    event_type: str
    label: str
    observed_at: datetime
    promotion_type: Optional[str] = None
    price_kind: Optional[str] = None
    old_value: Any = None
    new_value: Any = None


class EventsResponse(BaseModel):
    """`enabled` false (the store writes no events) comes with an empty list: nothing is shown that was not stored."""

    enabled: bool
    events: list[EventOut]
    next_cursor: Optional[str] = None


class HistoryChangeOut(BaseModel):
    """One changed field. `path` is the diff engine's (`price`, `tags[=cart_eligible]`,
    `locations[meli_facility].quantity`); `label_key` and the Spanish `label` are set on business
    lines only. `old`/`new` are null on the side that does not exist (a field that was added or removed)."""

    path: str
    label_key: Optional[str] = None
    label: Optional[str] = None
    old: Any = None
    new: Any = None


class HistoryEntryOut(BaseModel):
    """One change-log row: `kind` is `change`, `restored` or `gone`; the lines are one per changed field."""

    id: int
    observed_at: datetime
    resource_type: str
    kind: str
    business: list[HistoryChangeOut]
    technical: list[HistoryChangeOut]


class HistoryResponse(BaseModel):
    entries: list[HistoryEntryOut]
    next_cursor: Optional[str] = None


class GroupNodeOut(BaseModel):
    """One node of the tree. `count` is the `/items` total with `params` (the node's filters, ancestors included, to
    be put over the user's own); a `leaf` has publications as children. The product, family and item keys appear
    only on the nodes they describe."""

    kind: str
    key: str
    label: str
    count: int
    leaf: bool
    params: dict[str, str]
    producto_item_id: Optional[int] = None
    codigo: Optional[str] = None
    family_id: Optional[int] = None
    item_id: Optional[str] = None
    # present only with ml_metricas.ver_ganancia (owner decision 7: no average, no Ads sum on a node)
    negative_count: Optional[int] = None  # publications with ANY negative variation (= /items markup_neg total)
    markup_min: Optional[float] = None  # lowest unit markup of the node; null when no publication has a value
    markup_max: Optional[float] = None


class GroupsResponse(BaseModel):
    level: str
    path: list[str]
    nodes: list[GroupNodeOut]
    total: int
    limit: int
    offset: int
    familias: bool
    ads: Optional[AdsOut] = None  # present only with ml_metricas.ver_ganancia


class KpiStripOut(BaseModel):
    """Métricas' KPI strip, figure for figure (`ml_metricas.BoardKpis`); the profit figures (`total_gauss`, `markup`)
    are absent, not null, without `ml_metricas.ver_ganancia`. The Board has no Ads figures, so neither has this."""

    units: ml_metricas.KpiUnits
    gross: ml_metricas.KpiMoney
    total_gauss: Optional[ml_metricas.KpiMoney] = None
    markup: Optional[ml_metricas.KpiMarkup] = None
    rows_with_sales: ml_metricas.KpiShare
    ageing: ml_metricas.KpiAgeing


class KpisResponse(BaseModel):
    period: ml_metricas.BoardPeriod
    kpis: KpiStripOut
    mla_count: int  # the publications the filter selects: the list's `total`, not the ones that sold
    can_see_margin: bool


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


def filter_query(
    q: Optional[str] = Query(None, description="MLA id / digits (exact), else substring of title, SKU, product"),
    estado: Optional[str] = Query(None, description="csv of active,paused,closed,under_review,inactive,gone"),
    estado_excluir: Optional[str] = None,
    tiendas: Optional[str] = Query(None, description="csv of official_store_id, or `none`"),
    marcas: Optional[str] = Query(None, description="csv of brands; `__none__` = no brand"),
    categorias: Optional[str] = Query(None, description="csv of categories; `__none__` = no category"),
    subcategorias: Optional[str] = Query(None, description="csv of subcategory ids; `__none__` = none"),
    pms: Optional[str] = None,
    familia: Optional[str] = None,
    producto: Optional[str] = Query(None, description="one product id (the publications of a tree node)"),
    sin_producto: Optional[bool] = Query(None, description="publications with no linked product (a tree node)"),
    tipo: Optional[str] = Query(None, description="csv of clasica,premium,catalogo,full"),
    vinculo: Optional[str] = Query(None, description="csv of auto,manual,sin_producto,conflicto,no_evaluado"),
    stock: Optional[str] = Query(None, description="csv of sin_stock,full_sin_stock"),
    evento: Optional[str] = Query(None, description="csv of event types; needs events.enabled"),
    evento_desde: Optional[str] = Query(None, description="24h, 7d or 30d"),
) -> PublicationFilter:
    """The filters every read of the screen shares (`/items` and `/groups`): one declaration, so a filter added here
    reaches both. A value outside its vocabulary is a 422 naming the parameter."""
    try:
        return parse_filter(
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
    except FilterError as exc:
        raise _unprocessable(exc) from exc


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
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
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


def _node_out(node: groups.Node) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": node.kind,
        "key": node.key,
        "label": node.label,
        "count": node.count,
        "leaf": node.leaf,
        "params": node.params,
    }
    for name in ("producto_item_id", "codigo", "family_id", "item_id"):
        if getattr(node, name) is not None:
            out[name] = getattr(node, name)
    if node.negative_count is not None:  # the figures travel together, and only for a caller who may see margins
        out["negative_count"] = node.negative_count
        out["markup_min"] = None if node.markup_min is None else round(node.markup_min, 2)
        out["markup_max"] = None if node.markup_max is None else round(node.markup_max, 2)
    return out


@router.get("/groups", response_model=GroupsResponse, response_model_exclude_unset=True)
def get_groups(
    response: Response,
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    path: Optional[str] = Query(None, description="csv of the keys of the opened node, root first; empty = roots"),
    familias: bool = Query(False, description="family nodes between a product and its publications"),
    limit: int = Query(groups.DEFAULT_LIMIT, ge=1, le=groups.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    restar_publicidad: Optional[bool] = Query(None, description="node markup after Ads cost (ver_ganancia)"),
    ads_desde: Optional[str] = Query(None, description="first day of the Ads period, YYYY-MM-DD (ver_ganancia)"),
    ads_hasta: Optional[str] = Query(None, description="last day of the Ads period, YYYY-MM-DD (ver_ganancia)"),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission check and the pricing tables (see `get_items`)
    ads_provider: AdsCostProvider = Depends(get_ads_provider),
) -> dict[str, Any]:
    """The children of one node of the Agrupado tree, a page of them, with their publication counts. The counts
    follow the same filters as `/items` (the store included), and each node's `params` select its publications there.
    With `ml_metricas.ver_ganancia`, also each node's `negative_count` and `markup_min`/`markup_max` (no average)."""
    timer = Timer("groups")
    can_see_margin = PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA)
    if not can_see_margin and restar_publicidad:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para restar la publicidad",
        )
    keys = [key.strip() for key in (path or "").split(",") if key.strip()]
    try:
        markup, ads_status = None, None
        if can_see_margin:
            ads_status = _ads_status(ads_provider, bool(restar_publicidad), *parse_ads_period(ads_desde, ads_hasta))
            markup = MarkupQuery(auth_db, MarkupFilter(), _ads_plan(ads_provider, ads_status))
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        with timer.stage("groups"):
            page = groups.list_groups(db, f, keys, familias=familias, limit=limit, offset=offset, markup=markup)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(level=page.level, rows=len(page.nodes), total=page.total)
    body: dict[str, Any] = {
        "level": page.level,
        "path": keys,
        "nodes": [_node_out(node) for node in page.nodes],
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "familias": familias,
    }
    if ads_status is not None:
        body["ads"] = _ads_out(ads_status.degraded() if page.ads_failed else ads_status)
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


@router.get("/items/{item_id}", response_model=ItemDetailResponse, response_model_exclude_unset=True)
def get_item_detail(
    response: Response,
    item_id: str = Path(..., pattern=admin.ITEM_ID_PATTERN),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission checks and the pricing tables (see `get_items`)
) -> dict[str, Any]:
    """The Resumen of one publication: its row, every stored field, stock per location, Full replenishment, all
    links and the product, how fresh each resource is and whether the caller may resynchronize it. With
    `ml_metricas.ver_ganancia`, also the product's cost, the row's markup and the breakdown of the markup."""
    timer = Timer("detail")
    permisos = PermisosService(auth_db)
    can_see_margin = permisos.tiene_permiso(user, PERMISO_GANANCIA)
    can_resync = permisos.tiene_permiso(user, PERMISO_GESTIONAR)
    try:
        with timer.stage("flags"):
            events_enabled = settings_store.get_setting("events.enabled").value is True
        markup = MarkupQuery(auth_db) if can_see_margin else None
        with timer.stage("detail"):
            found = detail.get_detail(db, item_id, events=events_enabled, markup=markup)
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    if found is None:
        raise api_error(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"La publicación {item_id} no existe")
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(links=len(found["links"]))
    found["can_resync"] = can_resync
    return found


def _page_cursor(cursor: Optional[str]) -> Optional[tuple[datetime, int]]:
    return events_view.decode_cursor(cursor) if cursor else None


@router.get("/items/{item_id}/events", response_model=EventsResponse, response_model_exclude_unset=True)
def get_item_events(
    response: Response,
    item_id: str = Path(..., pattern=admin.ITEM_ID_PATTERN),
    cursor: Optional[str] = Query(None, description="opaque position returned as next_cursor by the previous page"),
    limit: int = Query(events_view.DEFAULT_LIMIT, ge=1, le=events_view.MAX_LIMIT),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_view_db),
) -> dict[str, Any]:
    """The Eventos tab: a page of the publication's events, newest first. With `events.enabled` off, an empty list
    (`enabled` false): the store writes no events then and none is invented."""
    timer = Timer("events")
    try:
        position = _page_cursor(cursor)
        with timer.stage("flags"):
            events_enabled = settings_store.get_setting("events.enabled").value is True
        with timer.stage("events"):
            found = events_view.list_events(db, item_id, enabled=events_enabled, cursor=position, limit=limit)
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
    timer.emit(rows=len(found.events))
    return {"enabled": events_enabled, "events": found.events, "next_cursor": found.next_cursor}


@router.get("/items/{item_id}/history", response_model=HistoryResponse, response_model_exclude_unset=True)
def get_item_history(
    response: Response,
    item_id: str = Path(..., pattern=admin.ITEM_ID_PATTERN),
    cursor: Optional[str] = Query(None, description="opaque position returned as next_cursor by the previous page"),
    limit: int = Query(history.DEFAULT_LIMIT, ge=1, le=history.MAX_LIMIT),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_view_db),
) -> dict[str, Any]:
    """The Historial tab: a page of the publication's change log, newest first, each row split into the business
    fields and the technical ones. Independent of the events flag (it reads the log, not the events)."""
    timer = Timer("history")
    try:
        position = _page_cursor(cursor)
        with timer.stage("history"):
            found = history.list_history(db, item_id, cursor=position, limit=limit)
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
    timer.emit(rows=len(found.entries))
    return {"entries": found.entries, "next_cursor": found.next_cursor}


KPI_PERIOD_PRESETS = (7, 15, 30, 60, 90)  # days, ending today
KPI_DEFAULT_DAYS = 30


def _day(value: Optional[str], field: str) -> Optional[date]:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise FilterError(field, f"invalid date (YYYY-MM-DD): {value!r}") from exc


def kpi_period(periodo: Optional[str], desde: Optional[str], hasta: Optional[str]) -> tuple[date, date]:
    """The strip's own period: a preset of days ending today, or `desde`/`hasta` (each defaulting like Métricas:
    `hasta` to today, `desde` to the default length before it). The bounds are Métricas' own."""
    days = KPI_DEFAULT_DAYS
    if periodo is not None and periodo.strip():
        if (desde or "").strip() or (hasta or "").strip():
            raise FilterError("periodo", "cannot be combined with desde / hasta")
        if not periodo.strip().isdigit() or int(periodo) not in KPI_PERIOD_PRESETS:
            raise FilterError("periodo", f"must be one of {', '.join(map(str, KPI_PERIOD_PRESETS))}")
        days = int(periodo)
    last = _day(hasta, "hasta") or board.today_business()
    given = _day(desde, "desde")
    first = given or last - timedelta(days=days - 1)
    low, high = ml_metricas.MIN_BOARD_DATE, ml_metricas.MAX_BOARD_DATE
    bounds = f"must be between {low.isoformat()} and {high.isoformat()}"
    if given and not low <= given <= high:
        raise FilterError("desde", bounds)
    if not low <= last <= high:
        raise FilterError("hasta", bounds)
    if not low <= first <= high:  # a `desde` the client never sent comes from `hasta`: that is the one at fault
        raise FilterError("hasta", f"leaves the {days}-day period before {low.isoformat()}")
    if first > last:
        raise FilterError("desde", "is after hasta")
    if (last - first).days + 1 > ml_metricas.MAX_PERIOD_DAYS:
        raise FilterError("desde", f"the period cannot exceed {ml_metricas.MAX_PERIOD_DAYS} days")
    return first, last


def require_kpis_access(
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    auth_db: Session = Depends(get_db),
) -> Usuario:
    """The strip is Métricas' numbers, so it needs `ml_metricas.ver` on top of `ml_ops.ver` (owner decision 4).
    A dependency declared first: who may ask is decided before anything asked is validated."""
    if not PermisosService(auth_db).tiene_permiso(user, PERMISO_METRICAS):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_METRICAS} para ver los KPIs",
        )
    return user


@router.get("/kpis", response_model=KpisResponse, response_model_exclude_unset=True)
def get_kpis(
    response: Response,
    user: Usuario = Depends(require_kpis_access),
    f: PublicationFilter = Depends(filter_query),
    periodo: Optional[str] = Query(None, description="7, 15, 30 (default), 60 or 90 days ending today"),
    desde: Optional[str] = Query(None, description="first day of the period, YYYY-MM-DD (instead of periodo)"),
    hasta: Optional[str] = Query(None, description="last day of the period, YYYY-MM-DD (default: today)"),
    comparar_con: str = Query("periodo_anterior", description=" | ".join(board.COMPARE)),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission checks (see `get_items`)
) -> dict[str, Any]:
    """Métricas ML's KPI strip over the MLAs the filters select, for its own period. The figures are the Board's own
    (same serializer as `/ml-metricas/board`); the profit ones need `ml_metricas.ver_ganancia`."""
    timer = Timer("kpis")
    can_see_margin = PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA)
    try:
        if comparar_con not in board.COMPARE:
            raise FilterError("comparar_con", f"must be one of {', '.join(board.COMPARE)}")
        first, last = kpi_period(periodo, desde, hasta)
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        with timer.stage("kpis"):
            strip = kpis.compute(db, f, first, last, comparar_con)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(mla_count=strip.mla_count)
    figures = ml_metricas.build_kpis(strip.kpis, can_see_margin)
    return {
        "period": {"date_from": first, "date_to": last, "prev_from": strip.prev_from, "prev_to": strip.prev_to},
        "kpis": figures.model_dump(exclude=None if can_see_margin else {"total_gauss", "markup"}),
        "mla_count": strip.mla_count,
        "can_see_margin": can_see_margin,
    }
