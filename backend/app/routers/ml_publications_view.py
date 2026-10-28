"""Router: the Publicaciones management screen's reads (`/ml-publications/view/...`, design §3).

Thin on purpose: it parses the query, checks the permission, calls `services/ml_publications/view` and serializes.
No SQL here and no access to the product catalog (the base select in the view services is the one place that
joins it).

- `GET /ml-publications/view/items` (`ml_ops.ver`): one row per MLA, filters, search, sorts, optional facets and
  the honest-state block. NO PM or sub-PM scoping: the screen is a management tool over every publication.
  With `ml_metricas.ver`, each row also carries `metrics`: Métricas ML's own publication row for it over the last 30
  business days (one Board per page) -- the 7/30-day units and their 90-day series, the gross revenue, the last sale
  and the ageing; Total Gauss, the real (sales-weighted) markup and its series only with `ml_metricas.ver_ganancia`.
  `sales_30d` (units, gross, markup) is the same row's 30-day figures, kept for screens that still read it.
- `GET /ml-publications/view/groups` (`ml_ops.ver`): the children of one node of the Agrupado tree, grouped by one of
  Métricas ML's dimensions (`dimension`, default `marca`: marca > categoria > subcategoria > producto > [familia]),
  with the same filters as `/items`; the publications of a leaf node come from `/items` with the node's `params`.
- `GET /ml-publications/view/products` (`ml_ops.ver`): the Producto view, one row per LINKED product (the
  publication -> product link; "Sin producto" = no link) over the MLAs the same filters select, its figures the sum of
  its publications' own (one Board, publication view, over the last 30 business days), sorted (`orden`/`dir`) and
  paged. Each row's `params` select exactly its `publications_count` publications in `/items`. Figures and figure
  sorts need `ml_metricas.ver`, the margin also `ml_metricas.ver_ganancia`. `sin_mla_count` counts Productos' "Sin
  MLA" products under the product filters (absent with a publication filter); `con_mla=false` lists them instead,
  refusing a publication filter (422), while the publication reads (`/items`, `/groups`, `/kpis`) select nothing.
- `GET /ml-publications/view/items/{item_id}` (`ml_ops.ver`): the Resumen of one publication, all its data; the cost of
  the product and the markup breakdown only with `ml_metricas.ver_ganancia`, `can_resync` from `ml_ops.gestionar`,
  `can_change_status` from `ml_publicaciones.pausar`.
- `GET /ml-publications/view/items/{item_id}/events` (`ml_ops.ver`): the publication's business events from
  `ml_item_events`, newest first, keyset-paged by an opaque cursor; an empty list while `events.enabled` is off.
- `GET /ml-publications/view/items/{item_id}/history` (`ml_ops.ver`): its `ml_change_log` rows (and those of its user
  product and family), one entry per row with the business fields apart from the technical ones.
- `GET /ml-publications/view/kpis` (`ml_ops.ver` AND `ml_metricas.ver`): Métricas ML's KPI strip over the MLAs the same
  filters select, for its own period (`periodo` 7/15/30/60/90 or `desde`/`hasta`, default the last 30 days) and
  `comparar_con`. The profit figures only with `ml_metricas.ver_ganancia` (omitted otherwise). No PM scoping.
- `GET /ml-publications/view/items/export` and `/products/export` (`ml_ops.ver`): the current view (same filters,
  sort, markup filters and permission checks as `/items` and `/products`, through the same dependencies) as a CSV
  streamed page by page, its keys fixed first and each later page read by key on its own session
  (`view/export.py`); every row, no cap. The Agrupado view has no export.
- `/items` also sorts by Métricas ML's figures (`orden` facturado_30d, unidades_7d, unidades_30d, with
  `ml_metricas.ver`; markup_30d and total_gauss_30d also with `ml_metricas.ver_ganancia`; 403 otherwise): the WHOLE
  filtered set ranked by the Board over the last 30 business days, then paged; no sales (or no cost) last.
- A query over `statement_timeout` answers 503 with the error code `consulta_lenta` (never a partial page) and
  the connection is released. Errors use the app's envelope: `{"error": {"code", "message"}}`, plus `field` on a
  422 that names the offending query parameter. Nothing here calls Mercado Libre and nothing writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal, Optional, Sequence

from fastapi import APIRouter, Depends, Path, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_background_db, get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.schemas.sell_in_out_producto import SellInOutProducto
from app.services.ml_daily_metrics import board, kpi_strip
from app.services.ml_daily_metrics.sales import NO_PRODUCT
from app.services import ml_publication_colors as colors
from app.services.ml_publications import admin, settings_store
from app.services.ml_publications.view import (
    detail,
    events_view,
    export,
    groups,
    history,
    kpis,
    listing,
    products,
    row_metrics,
    stats,
    status_block,
    status_targets,
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
from app.services.ml_publications.view.metrics_sort import METRIC_SORTS, needs_margin
from app.services.ml_publications.view.timing import Timer
from app.services.ml_promotions_service import (
    KNOWN_PROMOTION_TYPES,
    fetch_mlas_with_active_promo_type,
    fetch_mlas_with_candidate_only,
    fetch_mlas_with_candidate_only_for_types,
    fetch_mlas_with_started,
)
from app.services.ml_pxq_tiers_read_service import fetch_mlas_with_pxq_tiers
from app.services.permisos_service import PermisosService
from app.services.promo_filter_resolver import PromoResolverFns, select_promo_resolver

PERMISO_VER = "ml_ops.ver"
PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
OFFER_OF_PRODUCT = "oferta_por_producto"  # the `filter_query` param a Producto row's `params` carry with `con_oferta`
PERMISO_METRICAS = "ml_metricas.ver"  # the KPI strip is Métricas' numbers: seeing them needs seeing Métricas
PERMISO_GESTIONAR = "ml_ops.gestionar"  # what lets the screen offer "Resincronizar"
PERMISO_PAUSAR = "ml_publicaciones.pausar"  # what lets the screen offer "Pausar" / "Activar"
QUERY_CANCELED = "57014"  # Postgres' SQLSTATE for statement_timeout
logger = logging.getLogger(__name__)

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


class ErpStockOut(BaseModel):
    """The linked product's ERP stock (depósito 1, as Productos shows it), never merged with the ML `stock`;
    `quantity` is null when the row has no linked product (unknown, not zero)."""

    quantity: Optional[int] = None


class ItemCostOut(BaseModel):
    """The linked product's cost in its own currency, as the panel shows it."""

    amount: Optional[float] = None
    currency: Optional[str] = None


class LinkOut(BaseModel):
    state: str
    producto_item_id: Optional[int] = None
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None


class SkuDivergenceOut(BaseModel):
    """The publication's seller SKU disagrees with its linked product: it names another product (`otro_producto`,
    that product here) or no single product (`sin_coincidencia`, no product)."""

    kind: str
    producto_item_id: int | None = None
    codigo: str | None = None
    descripcion: str | None = None


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


class Sales30dOut(BaseModel):
    """Units and gross revenue of the publication over the last 30 business days (Métricas ML's base; zero without
    sales). `markup` is the real markup of those sales (sum of the markup numerator over sum of the cost, as the
    board computes it; null without cost or sales), present only with `ml_metricas.ver_ganancia`."""

    units: int
    gross: float
    markup: Optional[float] = None


class MetricsOut(BaseModel):
    """Métricas ML's figures of the publication, from the Board's publication row over the last 30 business days
    (the numbers the Métricas screen shows for it): units of the last 7 and 30 days with their 90-day daily series,
    the gross revenue, the last sale ever and the ageing in days. Total Gauss, the real markup (sum of the markup
    numerator over sum of the cost; null without cost), its change in points against the previous 30 days and its
    90-day daily series are present only with `ml_metricas.ver_ganancia`."""

    units_7d: int
    units_30d: int
    series_units_90d: list[int]
    gross_30d: float
    last_sale_at: Optional[datetime] = None
    ageing_days: Optional[int] = None
    total_gauss_30d: Optional[float] = None
    markup_30d: Optional[float] = None
    markup_delta_pp: Optional[float] = None
    series_markup_90d: Optional[list[Optional[float]]] = None


class LastEventOut(BaseModel):
    event_type: str
    observed_at: datetime


class ItemRowOut(BaseModel):
    item_id: str
    # The linked product's row color (Productos' team layers, `equipo_id`); present only when set
    # (services/ml_publication_colors.py).
    color_marcado: Optional[str] = None
    color_hint_global: Optional[str] = None
    color_hint_equipo_inicial: Optional[str] = None
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
    seller_sku: Optional[str] = None  # SELLER_SKU attribute, else seller_custom_field (the link rule's key)
    variations_count: int
    gone: bool
    gone_at: Optional[datetime] = None
    price: PriceOut
    stock: StockOut
    erp_stock: ErpStockOut
    link: LinkOut
    sku_divergence: SkuDivergenceOut | None = None  # only when the SKU disagrees with the linked product
    last_activity_at: Optional[datetime] = None
    last_event: Optional[LastEventOut] = None  # present only while events.enabled
    markup: Optional[MarkupOut] = None  # present only with ml_metricas.ver_ganancia
    costo: Optional[ItemCostOut] = None  # present only with ml_metricas.ver_ganancia; null without a product cost
    sales_30d: Optional[Sales30dOut] = None  # present only with ml_metricas.ver
    metrics: Optional[MetricsOut] = None  # present only with ml_metricas.ver; null when Métricas has no row


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
    stock: Optional[int] = None  # ERP stock (depósito 1), apart from the publication's ML stock
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
    # Same gate: the sell in / sell out of the breakdown's unit, its markups under the key `publicacion` (T10).
    sell_in_out: Optional[SellInOutProducto] = None
    freshness: list[FreshnessOut]
    can_resync: bool
    can_change_status: bool


class OriginOut(BaseModel):
    """Who caused a change (`view/origin.py`): `nosotros` (one of our audit rows, `user_name` its user), `automatico`
    (ours, by no user), `ml` (ML's by nature) or `sin_registrar` (could be either; no audit row of ours)."""

    kind: Literal["nosotros", "automatico", "ml", "sin_registrar"]
    user_name: Optional[str] = None


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
    promotion_id: Optional[str] = None
    promotion_name: Optional[str] = None  # the promotion's name as ML gave it, when a stored row has it (events_view)
    payload: Optional[dict[str, Any]] = None  # the typed payload of the event type (events.py)
    status_label: Optional[str] = None  # promotion events: "Disponible para activar", "Aplicada", ...
    origin: OriginOut
    informational: bool  # an ML offer or suggestion that changed nothing applied


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


class HistoryRowOut(BaseModel):
    """One readable line: a Spanish `label`, `before`/`after` already formatted for display (never a dict or a
    list), `subject` when the label alone is not enough (a promotion's name, a day), `status_label` on promotion
    states. Technical lines come only with `tecnicos=true`."""

    path: str
    label: str
    subject: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    is_technical: bool
    status_label: Optional[str] = None


class HistoryEntryOut(BaseModel):
    """One change-log row: `kind` is `change`, `restored` or `gone`; the lines are one per changed field."""

    id: int
    observed_at: datetime
    resource_type: str
    kind: str
    business: list[HistoryChangeOut]
    technical: list[HistoryChangeOut]
    rows: list[HistoryRowOut]
    hidden_technical_count: int
    origin: OriginOut
    informational: bool  # ML's offers, suggestions and metrics: nothing applied changed


class HistoryResponse(BaseModel):
    entries: list[HistoryEntryOut]
    next_cursor: Optional[str] = None
    hidden_technical_count: int = 0  # technical lines of the page left out of `rows` ("Ocultos N cambios técnicos")


class GroupNodeOut(BaseModel):
    """One node of the tree. `count` is the `/items` total with `params` (the node's filters, ancestors included, to
    be put over the user's own); a `leaf` has publications as children. The product, family and item keys appear
    only on the nodes they describe."""

    kind: str
    # The linked product's row color (Productos' team layers, `equipo_id`); present only when set
    # (services/ml_publication_colors.py).
    color_marcado: Optional[str] = None
    color_hint_global: Optional[str] = None
    color_hint_equipo_inicial: Optional[str] = None
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
    dimension: str
    levels: list[str]  # the levels of the tree, top first (`familia` last when families are on)
    level: str
    path: list[str]
    nodes: list[GroupNodeOut]
    total: int
    limit: int
    offset: int
    familias: bool
    ads: Optional[AdsOut] = None  # present only with ml_metricas.ver_ganancia


class ProductRowOut(BaseModel):
    """One row of the Producto view: a linked product and its publications among the selected ones.
    `product_item_id` is null on the "Sin producto" row (no link); `params` select the row's publications in `/items`,
    exactly `publications_count` of them. `metrics` (a publication's shape, its figures the sum of the row's
    publications') needs `ml_metricas.ver`; null when none of its publications has Métricas figures."""

    key: str
    # The linked product's row color (Productos' team layers, `equipo_id`); present only when set
    # (services/ml_publication_colors.py).
    color_marcado: Optional[str] = None
    color_hint_global: Optional[str] = None
    color_hint_equipo_inicial: Optional[str] = None
    product_item_id: Optional[int] = None
    codigo: Optional[str] = None
    descripcion: str
    marca: Optional[str] = None
    publications_count: int
    stock: Optional[int] = None
    params: dict[str, str]
    metrics: Optional[MetricsOut] = None


class ProductsResponse(BaseModel):
    rows: list[ProductRowOut]
    total: int  # the product rows of the whole filtered set
    mla_count: int  # the publications the filter selects: the list's `total`
    limit: int
    offset: int
    orden: str
    dir: str
    can_see_margin: bool
    # Productos' "Sin MLA" card: the products the product filters keep that no publication is linked to; absent
    # when a publication filter is on (it has nothing to ask of a product with no publication)
    sin_mla_count: Optional[int] = None


class KpiStripOut(BaseModel):
    """Métricas' KPI strip, figure for figure (`kpi_strip.BoardKpis`); the profit figures (`total_gauss`, `markup`)
    are absent, not null, without `ml_metricas.ver_ganancia`. The Board has no Ads figures, so neither has this."""

    units: kpi_strip.KpiUnits
    gross: kpi_strip.KpiMoney
    total_gauss: Optional[kpi_strip.KpiMoney] = None
    markup: Optional[kpi_strip.KpiMarkup] = None
    rows_with_sales: kpi_strip.KpiShare
    ageing: kpi_strip.KpiAgeing


class KpisResponse(BaseModel):
    period: kpi_strip.BoardPeriod
    kpis: KpiStripOut
    mla_count: int  # the publications the filter selects: the list's `total`, not the ones that sold
    can_see_margin: bool


class StatsResponse(BaseModel):
    stats: dict[str, int]  # card -> linked products (`stats.compute`); the markup cards only with `can_see_margin`
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


def _sin_mla_count_or_none(db: Session, f: PublicationFilter) -> Optional[int]:
    """The Sin MLA card's count, or None (the card shows it as unknown) when it goes over `statement_timeout`: an
    extra figure of the page never fails the rows already read. Any other database error is raised."""
    try:
        return products.sin_mla_count(db, f)
    except DBAPIError as exc:
        if not _timed_out(exc):
            raise
        logger.warning("ml_publications products: sin_mla_count over statement_timeout; answered without it")
        return None


def _attach_colors(
    auth_db: Session, layer: colors.ColorLayer, rows: list[dict[str, Any]], product_of: Callable[[dict[str, Any]], Any]
) -> None:
    """The row colors, with the list's own answer to a read over `statement_timeout`: the same 503."""
    try:
        colors.attach_colors(auth_db, layer, rows, product_of)
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise


def filter_query(
    q: Optional[str] = Query(None, description="MLA id / digits (exact), else substring of title, SKU, product"),
    estado: Optional[str] = Query(None, description="csv of active,paused,closed,under_review,inactive,gone"),
    estado_excluir: Optional[str] = None,
    tiendas: Optional[str] = Query(None, description="csv of official_store_id, or `none`"),
    marcas: Optional[str] = Query(None, description="csv of brands; `__none__` = no brand"),
    categorias: Optional[str] = Query(None, description="csv of categories; `__none__` = no category"),
    subcategorias: Optional[str] = Query(None, description="csv of subcategory ids; `__none__` = none"),
    pms: Optional[str] = None,
    pm_grupo: Optional[str] = Query(None, description="one PM user id, or `__none__` (the PM node of the tree)"),
    familia: Optional[str] = None,
    producto: Optional[str] = Query(None, description="one product id (the publications of a tree node)"),
    sin_producto: Optional[bool] = Query(None, description="publications with no linked product (a tree node)"),
    tipo: Optional[str] = Query(None, description="csv of clasica,premium,catalogo,full"),
    vinculo: Optional[str] = Query(
        None, description="csv of auto,manual,sin_producto,conflicto,no_evaluado,sku_divergente"
    ),
    stock: Optional[str] = Query(
        None, description="csv of sin_stock,full_sin_stock,erp_sin_stock,erp_con_stock,propio_sin_stock"
    ),
    evento: Optional[str] = Query(None, description="csv of event types; needs events.enabled"),
    evento_desde: Optional[str] = Query(None, description="24h, 7d or 30d"),
    # Productos' "Filtros de Presencia": the same params as `GET /productos`
    con_rebate: Optional[bool] = Query(
        None, description="the linked product takes part in rebate (false: it does not)"
    ),
    con_oferta: Optional[bool] = Query(None, description="the publication has a current mejor oferta"),
    con_web_transf: Optional[bool] = Query(None, description="the linked product takes part in web transferencia"),
    tn_con_descuento: Optional[bool] = Query(
        None, description="the product is in Tienda Nube with a promotional price"
    ),
    tn_sin_descuento: Optional[bool] = Query(None, description="the product is in Tienda Nube without one"),
    tn_no_publicado: Optional[bool] = Query(None, description="the product has ERP stock and is not in Tienda Nube"),
    out_of_cards: Optional[bool] = Query(None, description="the linked product is marked out of cards"),
    oferta_por_producto: Optional[bool] = Query(
        None, description="ask con_oferta of the product (any of its publications), as the Producto view does"
    ),
    con_precio: Optional[bool] = Query(None, description="the linked product has a list price (false: it has none)"),
    nuevos_ultimos_7_dias: Optional[bool] = Query(
        None, description="the linked product was synced from the ERP in the last 7 days"
    ),
    # Productos' markup filters, its stored markups of the linked product (ver_ganancia)
    markup_clasica_positivo: Optional[bool] = Query(None, description="markup clásica > 0 (false: < 0)"),
    markup_rebate_positivo: Optional[bool] = Query(None, description="markup rebate > 0 (false: < 0)"),
    markup_oferta_positivo: Optional[bool] = Query(None, description="markup oferta > 0 (false: < 0)"),
    markup_web_transf_positivo: Optional[bool] = Query(None, description="markup web transferencia > 0 (false: < 0)"),
    # Productos' audit filter: the linked product's `auditoria` rows
    audit_usuarios: Optional[str] = Query(None, description="csv of user ids who changed the product"),
    audit_tipos_accion: Optional[str] = Query(None, description="csv of audit kinds (GET /auditoria/tipos-accion)"),
    audit_fecha_desde: Optional[str] = Query(None, description="YYYY-MM-DD[ HH:MM], Buenos Aires time"),
    audit_fecha_hasta: Optional[str] = Query(
        None, description="YYYY-MM-DD[ HH:MM], Buenos Aires time; a date: all day"
    ),
    # Productos' promo filter and its "Con precios mayoristas" (MLA sets from the mlwebhook database)
    promo_tipos: Optional[str] = Query(None, description="csv of promotion types (SELLER_CAMPAIGN, DEAL, ...)"),
    promo_estado: Optional[str] = Query(None, description="disponible (default), aplicada or sin_aplicar"),
    con_promo_aplicada: Optional[bool] = Query(None, description="any promotion started (without promo_tipos)"),
    con_promo_sin_aplicar: Optional[bool] = Query(None, description="only candidate promotions (without promo_tipos)"),
    con_pxq: Optional[bool] = Query(None, description="the publication has wholesale (PxQ) tiers"),
    colores: Optional[str] = Query(
        None, description="csv of Productos' colors and/or `sin_color`, on the layer of `equipo_id` (the global one)"
    ),
    equipo_id: Optional[int] = Query(None, description="color layer (Productos' teams); omitted = the global one"),
    con_mla: Optional[bool] = Query(
        None, description="false: the products no publication is linked to (Productos' Sin MLA, Producto view)"
    ),
    # The caller and the application session, for the permission check of the markup filters (cached per request:
    # every endpoint already authenticates the same way).
    user: Usuario = Depends(get_current_user),
    auth_db: Session = Depends(get_db),
) -> PublicationFilter:
    """The filters every read of the screen shares (`/items` and `/groups`): one declaration, so a filter added here
    reaches both. A value outside its vocabulary is a 422 naming the parameter; a markup filter without
    `ml_metricas.ver_ganancia` is a 403, as every markup of this screen."""
    signs = (markup_clasica_positivo, markup_rebate_positivo, markup_oferta_positivo, markup_web_transf_positivo)
    if any(sign is not None for sign in signs) and not PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para filtrar por markup",
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
            pm_grupo=pm_grupo,
            familia=familia,
            producto=producto,
            sin_producto=sin_producto,
            tipo=tipo,
            vinculo=vinculo,
            stock=stock,
            evento=evento,
            evento_desde=evento_desde,
            con_rebate=con_rebate,
            con_oferta=con_oferta,
            con_web_transf=con_web_transf,
            tn_con_descuento=tn_con_descuento,
            tn_sin_descuento=tn_sin_descuento,
            tn_no_publicado=tn_no_publicado,
            out_of_cards=out_of_cards,
            oferta_por_producto=oferta_por_producto,
            con_precio=con_precio,
            nuevos_ultimos_7_dias=nuevos_ultimos_7_dias,
            markup_clasica_positivo=markup_clasica_positivo,
            markup_rebate_positivo=markup_rebate_positivo,
            markup_oferta_positivo=markup_oferta_positivo,
            markup_web_transf_positivo=markup_web_transf_positivo,
            audit_usuarios=audit_usuarios,
            audit_tipos_accion=audit_tipos_accion,
            audit_fecha_desde=audit_fecha_desde,
            audit_fecha_hasta=audit_fecha_hasta,
            mla_scope=_mla_scope(promo_tipos, promo_estado, con_promo_aplicada, con_promo_sin_aplicar, con_pxq),
            colores=colores,
            con_mla=con_mla,
        )
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    if not (f.colors or f.no_color):
        return f
    # The colors are the layer's (a team the user is not in is a 403, as everywhere): resolved once, here, so the
    # filter means the same products on every read it reaches.
    return colors.resolve_color_filter(auth_db, colors.resolve_layer(auth_db, user, equipo_id), f)


PROMO_STATES = ("disponible", "aplicada", "sin_aplicar")
FILTER_UNAVAILABLE_CODE = "filtro_no_disponible"


def _mla_scope(
    promo_tipos: Optional[str],
    promo_estado: Optional[str],
    con_promo_aplicada: Optional[bool],
    con_promo_sin_aplicar: Optional[bool],
    con_pxq: Optional[bool],
) -> Optional[frozenset[str]]:
    """Productos' promo filter (the same `select_promo_resolver` dispatch) and its PxQ toggle as the MLAs that match,
    read from the mlwebhook database, ANDed; `None` when neither is asked. A resolver that cannot answer is a 503:
    never the unfiltered list."""
    tipos = [t.strip() for t in (promo_tipos or "").split(",") if t.strip()]
    unknown = [t for t in tipos if t not in KNOWN_PROMOTION_TYPES]
    if unknown:
        raise FilterError(
            "promo_tipos", f"unknown value(s) {', '.join(unknown)}; known: {', '.join(sorted(KNOWN_PROMOTION_TYPES))}"
        )
    if promo_estado is not None and promo_estado not in PROMO_STATES:
        raise FilterError("promo_estado", f"unknown value {promo_estado}; known: {', '.join(PROMO_STATES)}")
    asked = []
    promo = select_promo_resolver(
        PromoResolverFns(
            active_promo_type=fetch_mlas_with_active_promo_type,
            started=fetch_mlas_with_started,
            candidate_only=fetch_mlas_with_candidate_only,
            candidate_only_for_types=fetch_mlas_with_candidate_only_for_types,
        ),
        tipos or None,
        promo_estado,
        con_promo_aplicada,
        con_promo_sin_aplicar,
    )
    if promo is not None:
        asked.append((*promo, "Filtro de promociones no disponible temporalmente"))
    if con_pxq:
        asked.append(
            (fetch_mlas_with_pxq_tiers, "Filtro PxQ", "Filtro de precios mayoristas no disponible temporalmente")
        )
    scope: Optional[frozenset[str]] = None
    for resolver, context, message in asked:
        try:
            found = frozenset(resolver())
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.warning("%s no disponible: %s", context, exc)
            raise api_error(status.HTTP_503_SERVICE_UNAVAILABLE, FILTER_UNAVAILABLE_CODE, message) from exc
        scope = found if scope is None else scope & found
    return scope


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


def _metrics_out(row: board.Row, with_margin: bool) -> dict[str, Any]:
    """The Board row as Métricas ML serializes it (same rounding), the margin only for who may see it."""
    out: dict[str, Any] = {
        "units_7d": row.windows["7d"],
        "units_30d": row.windows["30d"],
        "series_units_90d": row.series_units,
        "gross_30d": kpi_strip.round_money(row.gross),
        "last_sale_at": row.last_sale_at,
        "ageing_days": row.ageing_days,
    }
    if with_margin:
        out["total_gauss_30d"] = kpi_strip.round_money(row.tg)
        out["markup_30d"] = kpi_strip.round_pp(row.markup)
        out["markup_delta_pp"] = kpi_strip.round_pp(row.markup_delta)
        out["series_markup_90d"] = row.series_markup
    return out


def _attach_metrics(items: list[dict[str, Any]], by_mla: dict[str, board.Row], with_margin: bool) -> None:
    """`metrics` (null without a Board row) and `sales_30d` (zero without sales) on every row of the page."""
    for item in items:
        found = by_mla.get(item["item_id"])
        item["metrics"] = _metrics_out(found, with_margin) if found else None
        sales: dict[str, Any] = {
            "units": found.windows["30d"] if found else 0,
            "gross": kpi_strip.round_money(found.gross) if found else 0.0,
        }
        if with_margin:
            sales["markup"] = kpi_strip.round_pp(found.markup) if found else None
        item["sales_30d"] = sales


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


@dataclass(frozen=True)
class ItemsAsk:
    """What a publications request asks (`/items` and its export read it from the same dependency, so the two can
    never drift): what the caller may see, the sort, the markup filter and the Ads to apply."""

    can_see_margin: bool
    can_see_sales: bool
    sort: listing.Sort
    markup_filter: Optional[MarkupFilter] = None  # set only when the caller may see margins
    ads_status: Optional[AdsStatus] = None
    ads_plan: Optional[AdsPlan] = None

    def markup(self, pricing_db: Session, ads: Optional[AdsPlan] = None) -> Optional[MarkupQuery]:
        """The markup query over `pricing_db` (None for a caller who may not see margins); `ads` replaces the plan."""
        if self.markup_filter is None:
            return None
        return MarkupQuery(pricing_db, self.markup_filter, ads if ads is not None else self.ads_plan)


def items_ask(
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    orden: Optional[str] = Query(
        None,
        description=(
            "actividad (default), precio, titulo, stock_full, stock_propio, stock_erp, actualizado, markup "
            "(ver_ganancia); Métricas ML's figures over the whole filtered set (ml_metricas.ver): facturado_30d, "
            "unidades_7d, unidades_30d, markup_30d and total_gauss_30d (also ver_ganancia)"
        ),
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
    # The application session, for the permission check (see `get_items`).
    auth_db: Session = Depends(get_db),
    ads_provider: AdsCostProvider = Depends(get_ads_provider),
) -> ItemsAsk:
    """The permission checks (403) and the parsing (422) of a publications request's sort, markup and Ads."""
    permisos = PermisosService(auth_db)
    can_see_margin = permisos.tiene_permiso(user, PERMISO_GANANCIA)
    can_see_sales = permisos.tiene_permiso(user, PERMISO_METRICAS)
    sort_name = (orden or "").strip()
    if sort_name in METRIC_SORTS and not can_see_sales:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_METRICAS} para ordenar por las cifras de Métricas ML",
        )
    asks_for_margin = bool(
        markup_neg
        or restar_publicidad
        or (markup_min or "").strip()
        or (markup_max or "").strip()
        or sort_name == "markup"
        or sort_name in listing.MARGIN_SORTS
        or (sort_name in METRIC_SORTS and needs_margin(sort_name))
    )  # blank values are absent parameters and the sort name is trimmed, here as in the parsers
    if not can_see_margin and asks_for_margin:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para ordenar o filtrar por markup",
        )
    try:
        sort = listing.parse_sort(orden, direction)
        if not can_see_margin:
            return ItemsAsk(can_see_margin, can_see_sales, sort)
        markup_filter = parse_markup_filter(markup_neg=markup_neg, markup_min=markup_min, markup_max=markup_max)
        ads_status = _ads_status(ads_provider, bool(restar_publicidad), *parse_ads_period(ads_desde, ads_hasta))
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    return ItemsAsk(can_see_margin, can_see_sales, sort, markup_filter, ads_status, _ads_plan(ads_provider, ads_status))


@router.get("/items", response_model=ItemsResponse, response_model_exclude_unset=True)
def get_items(
    response: Response,
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    ask: ItemsAsk = Depends(items_ask),
    limit: int = Query(listing.DEFAULT_LIMIT, ge=1, le=listing.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    facets: bool = False,
    equipo_id: Optional[int] = Query(None, description="color layer (Productos' teams); omitted = the global one"),
    db: Session = Depends(get_view_db),
    # The application session, for the permission check. In production it IS `db` (FastAPI caches `get_db`
    # within a request); it is its own parameter so the permission never rides on the store-tables test seam,
    # and it works after the `rollback()` below because a new transaction begins on first use.
    auth_db: Session = Depends(get_db),
    status_provider: Callable[[], dict[str, Any]] = Depends(get_status_provider),
) -> dict[str, Any]:
    """One page of publications (one row per MLA) with the honest-state block, each with its product's row color."""
    timer = Timer("items")
    layer = colors.resolve_layer(auth_db, user, equipo_id)  # first: a team the user is not in is a 403
    can_see_margin, can_see_sales, sort = ask.can_see_margin, ask.can_see_sales, ask.sort
    ads_status = ask.ads_status
    try:
        markup = ask.markup(auth_db)
        with timer.stage("flags"):
            events_enabled = settings_store.get_setting("events.enabled").value is True
        listing.bound(db)
        f = listing.resolve_pm_pairs(db, f)  # once: the list and the facets share the resolved pairs
        with timer.stage("list"):
            page = listing.list_items(
                db, f, sort, limit, offset, events=events_enabled, markup=markup, can_see_margin=can_see_margin
            )
        if can_see_sales:
            with timer.stage("metrics"):
                by_mla = row_metrics.metrics_by_mla(db, [item["item_id"] for item in page.items])
            _attach_metrics(page.items, by_mla, with_margin=can_see_margin)
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
    with timer.stage("colors"):
        _attach_colors(auth_db, layer, page.items, lambda item: (item.get("link") or {}).get("producto_item_id"))
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
    dimension: str = Query(groups.DEFAULT_DIMENSION, description=" | ".join(groups.DIMENSIONS)),
    familias: bool = Query(False, description="family nodes between a product and its publications"),
    limit: int = Query(groups.DEFAULT_LIMIT, ge=1, le=groups.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    restar_publicidad: Optional[bool] = Query(None, description="node markup after Ads cost (ver_ganancia)"),
    ads_desde: Optional[str] = Query(None, description="first day of the Ads period, YYYY-MM-DD (ver_ganancia)"),
    ads_hasta: Optional[str] = Query(None, description="last day of the Ads period, YYYY-MM-DD (ver_ganancia)"),
    equipo_id: Optional[int] = Query(None, description="color layer (Productos' teams); omitted = the global one"),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission check and the pricing tables (see `get_items`)
    ads_provider: AdsCostProvider = Depends(get_ads_provider),
) -> dict[str, Any]:
    """The children of one node of the Agrupado tree, a page of them, with their publication counts. The counts
    follow the same filters as `/items` (the store included), and each node's `params` select its publications there.
    With `ml_metricas.ver_ganancia`, also each node's `negative_count` and `markup_min`/`markup_max` (no average)."""
    timer = Timer("groups")
    layer = colors.resolve_layer(auth_db, user, equipo_id)  # a team the user is not in is a 403
    can_see_margin = PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA)
    if not can_see_margin and restar_publicidad:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para restar la publicidad",
        )
    keys = [key.strip() for key in (path or "").split(",") if key.strip()]
    try:
        levels = [*groups.levels_of(dimension), *([groups.KIND_FAMILY] if familias else [])]
        markup, ads_status = None, None
        if can_see_margin:
            ads_status = _ads_status(ads_provider, bool(restar_publicidad), *parse_ads_period(ads_desde, ads_hasta))
            markup = MarkupQuery(auth_db, MarkupFilter(), _ads_plan(ads_provider, ads_status))
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        with timer.stage("groups"):
            page = groups.list_groups(
                db, f, keys, familias=familias, limit=limit, offset=offset, markup=markup, dimension=dimension
            )
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    nodes = [_node_out(node) for node in page.nodes]
    # Only a product node is painted: its product's color (the other levels group several products).
    product_nodes = [node for node in nodes if node["kind"] == groups.KIND_PRODUCT]
    _attach_colors(auth_db, layer, product_nodes, lambda node: node.get("producto_item_id"))
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(level=page.level, rows=len(page.nodes), total=page.total)
    body: dict[str, Any] = {
        "dimension": dimension,
        "levels": levels,
        "level": page.level,
        "path": keys,
        "nodes": nodes,
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "familias": familias,
    }
    if ads_status is not None:
        body["ads"] = _ads_out(ads_status.degraded() if page.ads_failed else ads_status)
    return body


def _product_out(
    row: board.Row, with_metrics: bool, with_margin: bool, has_figures: bool, offer_filter: bool
) -> dict[str, Any]:
    no_product = row.product_item_id == NO_PRODUCT
    params = {groups.PARAM_NO_PRODUCT: "true"} if no_product else {groups.PARAM_PRODUCT: str(row.product_item_id)}
    if offer_filter:  # the rows ask mejor oferta of the product: opening one must ask it the same way
        params[OFFER_OF_PRODUCT] = "true"
    out: dict[str, Any] = {
        "key": row.key,
        "product_item_id": None if no_product else row.product_item_id,
        "codigo": row.sku,
        "descripcion": row.title,
        "marca": row.marca,
        "publications_count": row.publications_count,
        "stock": row.stock,
        "params": params,
    }
    if with_metrics:
        out["metrics"] = _metrics_out(row, with_margin) if has_figures else None
    return out


@dataclass(frozen=True)
class ProductsAsk:
    """What a Producto-view request asks (`/products` and `/products/export` both read it): what the caller may see and the
    sort, already checked and parsed."""

    can_see_margin: bool
    can_see_sales: bool
    sort_name: str
    sort_dir: str


def products_ask(
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    orden: Optional[str] = Query(
        None,
        description=(
            "facturado_30d (default with ml_metricas.ver), unidades_7d, unidades_30d (ml_metricas.ver); markup_30d, "
            "total_gauss_30d (also ver_ganancia); titulo (the default without ml_metricas.ver)"
        ),
    ),
    direction: Optional[str] = Query(None, alias="dir", description="asc or desc (default desc; asc by titulo)"),
    auth_db: Session = Depends(get_db),  # the permission checks (see `get_items`)
) -> ProductsAsk:
    """The permission checks (403) and the parsing (422) of a Producto-view request's sort."""
    permisos = PermisosService(auth_db)
    can_see_margin = permisos.tiene_permiso(user, PERMISO_GANANCIA)
    can_see_sales = permisos.tiene_permiso(user, PERMISO_METRICAS)
    sort_name = (orden or "").strip() or (products.DEFAULT_SORT if can_see_sales else products.NEUTRAL_SORT)
    known = sort_name in products.PRODUCT_SORTS
    if known and products.needs_metrics(sort_name) and not can_see_sales:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_METRICAS} para ordenar por las cifras de Métricas ML",
        )
    if known and products.needs_margin(sort_name) and not can_see_margin:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para ordenar por markup",
        )
    default_dir = "asc" if sort_name == products.NEUTRAL_SORT else "desc"
    sort_dir = (direction or default_dir).strip().lower()
    if sort_dir not in ("asc", "desc"):
        raise _unprocessable(FilterError("dir", "must be asc or desc"))
    return ProductsAsk(can_see_margin, can_see_sales, sort_name, sort_dir)


@router.get("/products", response_model=ProductsResponse, response_model_exclude_unset=True)
def get_products(
    response: Response,
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    ask: ProductsAsk = Depends(products_ask),
    limit: int = Query(listing.DEFAULT_LIMIT, ge=1, le=listing.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    equipo_id: Optional[int] = Query(None, description="color layer (Productos' teams); omitted = the global one"),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the color layer and its colors (see `get_items`)
) -> dict[str, Any]:
    """The Producto view: one page of product rows over the MLAs the filters select, with Métricas ML's figures
    and each product's row color."""
    timer = Timer("products")
    layer = colors.resolve_layer(auth_db, user, equipo_id)  # a team the user is not in is a 403
    can_see_margin, can_see_sales, sort_name, sort_dir = (
        ask.can_see_margin,
        ask.can_see_sales,
        ask.sort_name,
        ask.sort_dir,
    )
    try:
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        with timer.stage("products"):
            page = products.list_products(db, f, sort_name, sort_dir == "desc", limit, offset)
        if f.sin_mla:  # the rows are the Sin MLA products: their total is the count
            sin_mla_count = page.total
        else:
            with timer.stage("sin_mla"):
                sin_mla_count = _sin_mla_count_or_none(db, f)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(rows=len(page.rows), total=page.total)
    rows = [
        _product_out(row, can_see_sales, can_see_margin, row.key not in page.without_figures, f.oferta is not None)
        for row in page.rows
    ]
    _attach_colors(auth_db, layer, rows, lambda row: row["product_item_id"])
    applied_name, applied_desc = products.applied_sort(f, sort_name, sort_dir == "desc")
    return {
        "rows": rows,
        "total": page.total,
        "mla_count": page.mla_count,
        "limit": limit,
        "offset": offset,
        "orden": applied_name,
        "dir": "desc" if applied_desc else "asc",
        "can_see_margin": can_see_margin,
        **({} if sin_mla_count is None else {"sin_mla_count": sin_mla_count}),
    }


class ProductIdsResponse(BaseModel):
    item_ids: list[int]
    count: int
    sin_producto: int  # matching publications with no linked product: no bulk action reaches them
    fuera_de_catalogo: int  # linked products gone from the ERP catalog: left out, no bulk write can price them


PRODUCT_IDS_OVER_CAP = "demasiados_productos"


def _check_markup_filter(
    user: Usuario,
    auth_db: Session,
    markup_neg: Optional[bool],
    markup_min: Optional[str],
    markup_max: Optional[str],
) -> bool:
    """Whether the request filters by markup; doing so needs `ml_metricas.ver_ganancia` (403 otherwise)."""
    asks_for_margin = bool(markup_neg or (markup_min or "").strip() or (markup_max or "").strip())
    if asks_for_margin and not PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Se requiere el permiso {PERMISO_GANANCIA} para filtrar por markup",
        )
    return asks_for_margin


def _markup_query(
    auth_db: Session, markup_neg: Optional[bool], markup_min: Optional[str], markup_max: Optional[str]
) -> MarkupQuery:
    markup_filter = parse_markup_filter(markup_neg=markup_neg, markup_min=markup_min, markup_max=markup_max)
    return MarkupQuery(auth_db, markup_filter)


@router.get("/product-ids", response_model=ProductIdsResponse)
def get_product_ids(
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    markup_neg: Optional[bool] = Query(None, description="ANY variation negative (ver_ganancia), as in /items"),
    markup_min: Optional[str] = Query(None, description="worst variation >= this percent (ver_ganancia)"),
    markup_max: Optional[str] = Query(None, description="worst variation <= this percent (ver_ganancia)"),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission check and the pricing tables (see `get_items`)
) -> dict[str, Any]:
    """The linked products of the publications the filters select -- the markup filters included, applied as
    `/items` applies them: the set a bulk pricing action acts on. Over `products.MAX_PRODUCT_IDS` it is a 422
    naming the count, never a truncated list."""
    asks_for_margin = _check_markup_filter(user, auth_db, markup_neg, markup_min, markup_max)
    try:
        markup = _markup_query(auth_db, markup_neg, markup_min, markup_max) if asks_for_margin else None
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        found = products.product_ids(db, f, markup)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except products.TooManyProducts as exc:
        error = api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PRODUCT_IDS_OVER_CAP,
            f"El filtro selecciona {exc.count} productos; una acción masiva admite hasta {exc.cap}. Acotá el filtro.",
        )
        error.detail["count"] = exc.count
        error.detail["max"] = exc.cap
        raise error from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    return {
        "item_ids": found.item_ids,
        "count": len(found.item_ids),
        "sin_producto": found.sin_producto,
        "fuera_de_catalogo": found.fuera_de_catalogo,
    }


class StatusItemIdsResponse(BaseModel):
    item_ids: list[str]
    count: int
    no_aplican: int  # the rest of the filtered set: another status, or deleted -- the bulk action leaves them alone


STATUS_ITEM_IDS_OVER_CAP = "demasiadas_publicaciones"


@router.get("/status-item-ids", response_model=StatusItemIdsResponse)
def get_status_item_ids(
    target: Literal["paused", "active"] = Query(..., description="the status the bulk action asks for"),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    _may_change: Usuario = Depends(require_permiso(PERMISO_PAUSAR)),
    f: PublicationFilter = Depends(filter_query),
    markup_neg: Optional[bool] = Query(None, description="ANY variation negative (ver_ganancia), as in /items"),
    markup_min: Optional[str] = Query(None, description="worst variation >= this percent (ver_ganancia)"),
    markup_max: Optional[str] = Query(None, description="worst variation <= this percent (ver_ganancia)"),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission checks and the pricing tables (see `get_items`)
) -> dict[str, Any]:
    """The publications of the filtered set -- the markup filters included, applied as `/items` applies them -- that
    a bulk pause / activate acts on: only active ones are paused, only paused ones activated, never a deleted one.
    Needs `ml_publicaciones.pausar`. Over `caps.MAX_STATUS_ITEM_IDS` it is a 422 naming the count, never a
    truncated list."""
    asks_for_margin = _check_markup_filter(user, auth_db, markup_neg, markup_min, markup_max)
    try:
        markup = _markup_query(auth_db, markup_neg, markup_min, markup_max) if asks_for_margin else None
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        found = status_targets.status_item_ids(db, f, target, markup)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except status_targets.TooManyPublications as exc:
        error = api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STATUS_ITEM_IDS_OVER_CAP,
            f"El filtro selecciona {exc.count} publicaciones; una acción masiva admite hasta {exc.cap}. Acotá el filtro.",
        )
        error.detail["count"] = exc.count
        error.detail["max"] = exc.cap
        raise error from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    return {"item_ids": found.item_ids, "count": len(found.item_ids), "no_aplican": found.no_aplican}


# ── CSV export of the current view ───────────────────────────────


def _csv_response(body: Any, name: str) -> StreamingResponse:
    filename = f"publicaciones-ml-{name}-{date.today().isoformat()}.csv"
    return StreamingResponse(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/items/export")
def export_items(
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    ask: ItemsAsk = Depends(items_ask),  # the list's own checks and parsing: the file cannot show what it cannot
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission checks and the pricing tables of the keys (see `get_items`)
) -> StreamingResponse:
    """Every publication of the current view as a CSV, in the list's order (the markup sort and filter included),
    STREAMED page by page with the list's own columns; the Métricas ML columns with `ml_metricas.ver`, the margin
    ones with `ml_metricas.ver_ganancia`.

    The request's short transaction fixes the ORDERED keys of EVERY row (no cap) and reads
    page 1, before the 200, so a bad state fails as a normal HTTP error. Each later page of `export.EXPORT_PAGE_SIZE`
    keys runs on its OWN short session (`get_background_db`) and reads its rows BY KEY: a change between pages can
    never repeat or drop a row (a row that stopped matching the filters is skipped). The request sessions are closed
    before the first byte: a session held for the whole download pins a pooled connection while the client reads
    (QueuePool incident, PR #811). A page failing mid-stream ends the file with an explicit error line."""
    columns = export.visible(export.ITEM_COLUMNS, sales=ask.can_see_sales, margin=ask.can_see_margin)
    page_size = export.EXPORT_PAGE_SIZE
    try:
        events = settings_store.get_setting("events.enabled").value is True
        listing.bound(db)
        f = listing.resolve_pm_pairs(db, f)  # once: every page gets the resolved pairs
        plan, ads_failed = ask.ads_plan, False
        if plan is not None:  # read ONCE, before the keys: the order, the selection and every row share it
            prefetched = export.PrefetchedAds(plan.provider, plan.date_from, plan.date_to)
            plan, ads_failed = replace(plan, provider=prefetched), prefetched.failed
        keys = listing.ordered_keys(
            db,
            f,
            ask.sort,
            None,  # every row: no bound
            events=events,
            markup=ask.markup(auth_db, plan),
            can_see_margin=ask.can_see_margin,
        )

        def read(session: Session, pricing: Session, page_keys: Sequence[str]) -> list[list[Any]]:
            nonlocal ads_failed
            page = listing.items_for_keys(session, f, list(page_keys), events=False, markup=ask.markup(pricing, plan))
            ads_failed = ads_failed or page.ads_failed
            by_mla = (
                row_metrics.metrics_by_mla(session, [i["item_id"] for i in page.items]) if ask.can_see_sales else {}
            )
            return export.lines(columns, [(item, by_mla.get(item["item_id"])) for item in page.items])

        first = read(db, auth_db, keys[:page_size])
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written

    def fetch(page_keys: Sequence[str]) -> list[list[Any]]:
        with get_background_db() as page_db:
            listing.bound(page_db)
            try:
                return read(page_db, page_db, page_keys)
            finally:
                page_db.rollback()

    # CLOSE the request sessions: nothing may stay tied to the response's lifetime.
    db.close()
    auth_db.close()

    def notes() -> list[str]:
        """The Ads asked and not applied -- unavailable, or failed while pricing -- as the list's `ads` block says."""
        status_ = ask.ads_status
        if status_ is None or not status_.requested or (status_.applied and not ads_failed):
            return []
        return [export.ADS_NOTE.format(reason=status_.degraded().reason if ads_failed else status_.reason)]

    stream = export.stream(columns, keys, first, fetch, page_size, "items", notes)
    return _csv_response(stream, "publicaciones")


@router.get("/products/export")
def export_products(
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    ask: ProductsAsk = Depends(products_ask),  # the Producto view's own checks and parsing
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),
) -> StreamingResponse:
    """Every row of the Producto view as a CSV, in its order, streamed page by page exactly as `export_items` is
    (keys first, each later page by key on its own session, the request sessions closed before the first byte, an
    error line if a page fails); the figures with `ml_metricas.ver`, the margin with `ml_metricas.ver_ganancia`."""
    columns = export.visible(export.PRODUCT_COLUMNS, sales=ask.can_see_sales, margin=ask.can_see_margin)
    page_size = export.EXPORT_PAGE_SIZE
    descending = ask.sort_dir == "desc"
    try:
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        f = listing.resolve_pm_pairs(db, f)
        keys = products.ordered_product_keys(db, f, ask.sort_name, descending, None)  # every row

        def read(session: Session, page_keys: Sequence[int]) -> list[list[Any]]:
            page = products.products_for_keys(session, f, list(page_keys))
            return export.lines(columns, [(row, row.key not in page.without_figures) for row in page.rows])

        first = read(db, keys[:page_size])
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written

    def fetch(page_keys: Sequence[int]) -> list[list[Any]]:
        with get_background_db() as page_db:
            listing.bound(page_db)
            try:
                return read(page_db, page_keys)
            finally:
                page_db.rollback()

    db.close()
    auth_db.close()
    return _csv_response(export.stream(columns, keys, first, fetch, page_size, "productos"), "productos")


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
    can_change_status = permisos.tiene_permiso(user, PERMISO_PAUSAR)
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
    found["can_change_status"] = can_change_status
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
    tecnicos: bool = Query(False, description="include the technical lines in each entry's rows"),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_view_db),
) -> dict[str, Any]:
    """The Historial tab: a page of the publication's change log, newest first, each row split into the business
    fields and the technical ones. Independent of the events flag (it reads the log, not the events)."""
    timer = Timer("history")
    try:
        position = _page_cursor(cursor)
        with timer.stage("history"):
            found = history.list_history(db, item_id, cursor=position, limit=limit, include_technical=tecnicos)
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
    return {
        "entries": found.entries,
        "next_cursor": found.next_cursor,
        "hidden_technical_count": found.hidden_technical_count,
    }


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
    low, high = kpi_strip.MIN_BOARD_DATE, kpi_strip.MAX_BOARD_DATE
    bounds = f"must be between {low.isoformat()} and {high.isoformat()}"
    if given and not low <= given <= high:
        raise FilterError("desde", bounds)
    if not low <= last <= high:
        raise FilterError("hasta", bounds)
    if not low <= first <= high:  # a `desde` the client never sent comes from `hasta`: that is the one at fault
        raise FilterError("hasta", f"leaves the {days}-day period before {low.isoformat()}")
    if first > last:
        raise FilterError("desde", "is after hasta")
    if (last - first).days + 1 > kpi_strip.MAX_PERIOD_DAYS:
        raise FilterError("desde", f"the period cannot exceed {kpi_strip.MAX_PERIOD_DAYS} days")
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


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    response: Response,
    user: Usuario = Depends(require_permiso(PERMISO_VER)),  # first: who may ask comes before what is asked
    f: PublicationFilter = Depends(filter_query),
    db: Session = Depends(get_view_db),
    auth_db: Session = Depends(get_db),  # the permission checks (see `get_items`)
) -> dict[str, Any]:
    """Productos' stat cards (`/stats-dinamicos`) over the MLAs the filters select: each card counts the linked
    products its click lists. The markup cards are margin figures: only with `ml_metricas.ver_ganancia`."""
    timer = Timer("stats")
    can_see_margin = PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA)
    try:
        if f.needs_events and settings_store.get_setting("events.enabled").value is not True:
            raise FilterError("evento", "requires the events flag (events.enabled) to be on")
        listing.bound(db)
        with timer.stage("stats"):
            cards = stats.compute(db, f, markups=can_see_margin)
    except FilterError as exc:
        raise _unprocessable(exc) from exc
    except DBAPIError as exc:
        if (slow := _database_error(exc)) is not None:
            raise slow from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(total=cards["total"])
    return {"stats": cards, "can_see_margin": can_see_margin}


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
    figures = kpi_strip.build_kpis(strip.kpis, can_see_margin)
    return {
        "period": {"date_from": first, "date_to": last, "prev_from": strip.prev_from, "prev_to": strip.prev_to},
        "kpis": figures.model_dump(exclude=None if can_see_margin else {"total_gauss", "markup"}),
        "mla_count": strip.mla_count,
        "can_see_margin": can_see_margin,
    }
