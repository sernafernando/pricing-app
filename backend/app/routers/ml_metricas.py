"""Router: the Métricas ML board (ODD `metricas-ml-tablero` T3).

`GET /ml-metricas/board` -- one row per product (or per publication) with
sales windows, markup now vs before, 90-day sparklines, last sale and
ageing, plus the KPI strip and every chip count. The heavy lifting lives in
`app.services.ml_daily_metrics.board`; this module parses and validates the
params, applies the permission rules and shapes the response.

Permissions (migration `20261001_ml_metricas_permisos`):
- `ml_metricas.ver`: the screen at all (403 without it).
- `ml_metricas.ver_ganancia`: Total Gauss, markup and anything derived from
  them (sorting by them, the "Margen cayendo" alert). Without it those
  fields come back `null` and asking to sort/filter by them is 403 -- same
  split as `dashboard_tplink.ver` / `.ver_ganancia`.
"""

from __future__ import annotations

import csv
import json
import logging
import io
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_background_db, get_db
from app.models.usuario import Usuario
from app.services.ml_sales_query.params import parse_csv_ids, parse_csv_stores, parse_csv_strings
from app.services.ml_daily_metrics import board, groups
from app.services.ml_daily_metrics.kpi_strip import (
    MAX_BOARD_DATE,
    MAX_PERIOD_DAYS,
    MIN_BOARD_DATE,
    BoardKpis,
    BoardPeriod,
    KpiAgeing,  # noqa: F401 -- part of this router's public surface (its tests import it from here)
    build_kpis,
    round_money,
    round_pp,
)
from app.services import pm_scope
from app.services.permisos_service import PermisosService
from app.services.product_facets import ProductFacetOptions
from app.utils.csv_cells import csv_text

PERMISO_VER = "ml_metricas.ver"
PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
DEFAULT_PERIOD_DAYS = 30
# The CSV streams this many rows per page, each page on its own short DB
# session: memory and the pooled connection follow ONE page, never the file.
EXPORT_PAGE_SIZE = 500
# The export fixes the ordered list of row keys up front (see `export_board`);
# beyond this many rows it refuses and asks for narrower filters, like the
# Ventas ML export.
EXPORT_MAX_ROWS = 10_000

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml-metricas", tags=["ML Métricas"])


def require_ver(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not PermisosService(db).tiene_permiso(current_user, PERMISO_VER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Falta el permiso {PERMISO_VER}")
    return current_user


# ── Response models ──────────────────────────────────────────────


class BoardRow(BaseModel):
    key: str
    product_item_id: int
    mla: Optional[str] = None
    title: str
    sku: Optional[str] = None
    marca: Optional[str] = None
    publications_count: int
    # Distinct products of a group row (the "Agrupado" view); null elsewhere.
    products_count: Optional[int] = None
    # The tree level of a row of the "Agrupado" view (a level kind, or
    # "product" at the leaf) and what it opens into (null at the leaf);
    # null in the other views.
    level: Optional[str] = None
    child_level: Optional[str] = None
    units: int
    units_24h: int
    units_3d: int
    units_7d: int
    units_15d: int
    units_30d: int
    gross: float
    total_gauss: Optional[float] = None
    markup_pct: Optional[float] = None
    markup_prev_pct: Optional[float] = None
    markup_delta_pp: Optional[float] = None
    markup_min_90d: Optional[float] = None
    markup_max_90d: Optional[float] = None
    series_units_90d: List[int]
    series_markup_90d: Optional[List[Optional[float]]] = None
    last_sale_at: Optional[datetime] = None
    ageing_days: Optional[int] = None
    # `productos_erp.stock` of the row's product (a publication row: its
    # current product's); null when the ERP has none.
    stock: Optional[int] = None
    alerts: List[str]
    # Publication attributes (publication rows and nested rows only).
    status: Optional[str] = None
    listing_type: Optional[str] = None
    is_catalog: Optional[bool] = None
    is_full: Optional[bool] = None
    store_id: Optional[int] = None
    is_best: Optional[bool] = None
    thumbnail: Optional[str] = None


class BoardFacets(BaseModel):
    stores: Dict[str, int]
    stores_total: int
    pub_status: Dict[str, int]
    pub_type: Dict[str, int]
    alerts: Dict[str, Optional[int]]
    stock: Dict[str, int]
    # Same buckets as `KpiAgeing` (`over_60` is the "Ageing > 60d" alert).
    ageing: Dict[str, int]
    # Marca / categoría / subcategoría / PM options, each narrowed by every
    # OTHER active filter (stores included), never by its own.
    product: ProductFacetOptions


class BoardResponse(BaseModel):
    period: BoardPeriod
    group_by: str
    # What the "group" view sums by; null in the product/publication views.
    dimension: Optional[str] = None
    # The levels of the "group" view's tree, top first, "product" last; null elsewhere.
    levels: Optional[List[str]] = None
    total: int
    with_sales_count: int
    limit: int
    offset: int
    can_see_margin: bool
    refreshed_at: Optional[datetime] = None
    kpis: BoardKpis
    facets: BoardFacets
    rows: List[BoardRow]


class PublicationsResponse(BaseModel):
    rows: List[BoardRow]


class GroupNodesResponse(BaseModel):
    """One page of the level below a node of the "Agrupado" tree (its child
    nodes, or its products at the last level) and how many it has in all."""

    level: str
    rows: List[BoardRow]
    total: int
    limit: int
    offset: int


# ── Params ───────────────────────────────────────────────────────


def _parse_day(value: Optional[str], field: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"{field} inválida (YYYY-MM-DD): {value!r}") from e


def _parse_choices(raw: Optional[str], field: str, allowed: Tuple[str, ...]) -> Tuple[str, ...]:
    values = parse_csv_strings(raw, field)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise HTTPException(status_code=422, detail=f"{field} inválido: {bad} (esperado {', '.join(allowed)})")
    return values


def _no_overlap(include: Tuple[str, ...], exclude: Tuple[str, ...], field: str) -> None:
    both = [v for v in include if v in exclude]
    if both:
        raise HTTPException(status_code=422, detail=f"{field}: {both} no se puede incluir y excluir a la vez")


def board_filter(
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive (default: hace 29 días)"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive (default: hoy)"),
    comparar_con: str = Query(default="periodo_anterior", description=" | ".join(board.COMPARE)),
    group_by: str = Query(default="product", description=" | ".join(board.GROUP_BY)),
    dimension: str = Query(default="marca", description="Con group_by=group: " + " | ".join(board.DIMENSIONS)),
    stores: Optional[str] = Query(default=None, description="CSV de mlp_official_store_id y/o 'sin_tienda'"),
    marcas: Optional[str] = Query(default=None),
    categorias: Optional[str] = Query(default=None, description="CSV de categorías (productos_erp.categoria)"),
    subcategorias: Optional[str] = Query(default=None),
    pms: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Producto, SKU, marca, MLA o título"),
    pub_status: Optional[str] = Query(default=None, description="CSV: " + ", ".join(board.PUB_STATUSES)),
    pub_type: Optional[str] = Query(default=None, description="CSV: " + ", ".join(board.PUB_TYPES)),
    pub_status_exclude: Optional[str] = Query(
        default=None, description="CSV a ocultar: " + ", ".join(board.PUB_STATUSES)
    ),
    pub_type_exclude: Optional[str] = Query(default=None, description="CSV a ocultar: " + ", ".join(board.PUB_TYPES)),
    alerts: Optional[str] = Query(default=None, description="CSV: " + ", ".join(board.ALERTS)),
    stock: Optional[str] = Query(default=None, description="CSV: " + ", ".join(board.STOCK_BUCKETS)),
    stock_exclude: Optional[str] = Query(default=None, description="CSV a ocultar: " + ", ".join(board.STOCK_BUCKETS)),
    ageing: Optional[str] = Query(default=None, description="CSV: " + ", ".join(board.AGEING_BUCKETS)),
    ageing_exclude: Optional[str] = Query(
        default=None, description="CSV a ocultar: " + ", ".join(board.AGEING_BUCKETS)
    ),
    # OFF unless asked for: during a rolling deploy an older SPA bundle sends
    # nothing and must keep the full catalog (board, KPIs, CSV). The page
    # always sends it (on by default in the UI).
    solo_con_ventas: bool = Query(
        default=False,
        description="Sólo filas con al menos una unidad vendida en el período (sus ventanas no cambian)",
    ),
    sort: str = Query(default="gross", description=" | ".join(board.SORTS)),
    sort_dir: str = Query(default="desc", description="asc | desc"),
) -> board.BoardFilter:
    """Every board filter, validated (422 on anything unknown)."""
    if group_by not in board.GROUP_BY:
        raise HTTPException(status_code=422, detail=f"group_by inválido: {group_by!r}")
    if dimension not in board.DIMENSIONS:
        raise HTTPException(status_code=422, detail=f"dimension inválida: {dimension!r}")
    if comparar_con not in board.COMPARE:
        raise HTTPException(status_code=422, detail=f"comparar_con inválido: {comparar_con!r}")
    if sort not in board.SORTS:
        raise HTTPException(status_code=422, detail=f"sort inválido: {sort!r}")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=422, detail=f"sort_dir inválido: {sort_dir!r}")
    hasta = _parse_day(date_to, "date_to") or board.today_business()
    if not MIN_BOARD_DATE <= hasta <= MAX_BOARD_DATE:
        raise HTTPException(
            status_code=422,
            detail=f"Fechas fuera de rango: entre {MIN_BOARD_DATE.isoformat()} y {MAX_BOARD_DATE.isoformat()}",
        )
    desde = _parse_day(date_from, "date_from") or hasta - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if desde > hasta:
        raise HTTPException(status_code=422, detail="date_from es posterior a date_to")
    if desde < MIN_BOARD_DATE or hasta > MAX_BOARD_DATE:
        raise HTTPException(
            status_code=422,
            detail=f"Fechas fuera de rango: entre {MIN_BOARD_DATE.isoformat()} y {MAX_BOARD_DATE.isoformat()}",
        )
    if (hasta - desde).days + 1 > MAX_PERIOD_DAYS:
        raise HTTPException(status_code=422, detail=f"El período no puede superar {MAX_PERIOD_DAYS} días")
    pub_status_in = _parse_choices(pub_status, "pub_status", board.PUB_STATUSES)
    pub_status_out = _parse_choices(pub_status_exclude, "pub_status_exclude", board.PUB_STATUSES)
    pub_type_in = _parse_choices(pub_type, "pub_type", board.PUB_TYPES)
    pub_type_out = _parse_choices(pub_type_exclude, "pub_type_exclude", board.PUB_TYPES)
    _no_overlap(pub_status_in, pub_status_out, "pub_status")
    _no_overlap(pub_type_in, pub_type_out, "pub_type")
    stock_in = _parse_choices(stock, "stock", board.STOCK_BUCKETS)
    stock_out = _parse_choices(stock_exclude, "stock_exclude", board.STOCK_BUCKETS)
    _no_overlap(stock_in, stock_out, "stock")
    ageing_in = _parse_choices(ageing, "ageing", board.AGEING_BUCKETS)
    ageing_out = _parse_choices(ageing_exclude, "ageing_exclude", board.AGEING_BUCKETS)
    _no_overlap(ageing_in, ageing_out, "ageing")
    return board.BoardFilter(
        date_from=desde,
        date_to=hasta,
        compare=comparar_con,
        group_by=group_by,
        dimension=dimension,
        stores=parse_csv_stores(stores),
        marcas=parse_csv_strings(marcas, "marcas"),
        categorias=parse_csv_strings(categorias, "categorias"),
        subcategorias=parse_csv_ids(subcategorias, "subcategorias"),
        pms=parse_csv_ids(pms, "pms"),
        q=q.strip() if q and q.strip() else None,
        pub_status=pub_status_in,
        pub_type=pub_type_in,
        pub_status_exclude=pub_status_out,
        pub_type_exclude=pub_type_out,
        alerts=_parse_choices(alerts, "alerts", board.ALERTS),
        stock=stock_in,
        stock_exclude=stock_out,
        ageing=ageing_in,
        ageing_exclude=ageing_out,
        solo_con_ventas=solo_con_ventas,
        sort=sort,
        sort_desc=sort_dir == "desc",
    )


def _margin_gate(f: board.BoardFilter, can_see_margin: bool) -> None:
    if can_see_margin:
        return
    if f.sort in board.MARGIN_SORTS or "margen_cayendo" in f.alerts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Ordenar o filtrar por margen requiere {PERMISO_GANANCIA}"
        )


# ── Shaping ──────────────────────────────────────────────────────


def _row_out(row: board.Row, can_see_margin: bool, group_view: bool = False, leaf: bool = False) -> BoardRow:
    """`group_view`: a node of the "Agrupado" tree; `leaf`: a product under one."""
    known = [m for m in row.series_markup if m is not None]
    pub = row.pub
    # Alerts are product filters: a group row has none.
    alerts = [] if group_view else sorted(row.alerts() - (set() if can_see_margin else {"margen_cayendo"}))
    return BoardRow(
        key=row.key,
        product_item_id=row.product_item_id,
        mla=row.mla,
        title=row.title,
        sku=row.sku,
        marca=row.marca,
        publications_count=row.publications_count,
        products_count=row.products_count if group_view else None,
        level=row.level if group_view else (groups.PRODUCT_LEVEL if leaf else None),
        child_level=row.child_level if group_view else None,
        units=row.units,
        units_24h=row.units_24h,
        units_3d=row.windows["3d"],
        units_7d=row.windows["7d"],
        units_15d=row.windows["15d"],
        units_30d=row.windows["30d"],
        gross=round_money(row.gross),
        total_gauss=round_money(row.tg) if can_see_margin else None,
        markup_pct=round_pp(row.markup) if can_see_margin else None,
        markup_prev_pct=round_pp(row.markup_prev) if can_see_margin else None,
        markup_delta_pp=round_pp(row.markup_delta) if can_see_margin else None,
        markup_min_90d=(min(known) if known else None) if can_see_margin else None,
        markup_max_90d=(max(known) if known else None) if can_see_margin else None,
        series_units_90d=row.series_units,
        series_markup_90d=row.series_markup if can_see_margin else None,
        last_sale_at=row.last_sale_at,
        ageing_days=row.ageing_days,
        stock=row.stock,
        alerts=alerts,
        status=pub.status if pub else None,
        listing_type=pub.listing_type if pub else None,
        is_catalog=pub.is_catalog if pub else None,
        is_full=pub.is_full if pub else None,
        store_id=pub.store_id if pub else None,
        thumbnail=row.thumbnail,
    )


def _facets(facets: board.Facets, can_see_margin: bool) -> BoardFacets:
    alerts: Dict[str, Optional[int]] = dict(facets.alerts)
    if not can_see_margin:
        alerts["margen_cayendo"] = None
    return BoardFacets(
        stores=facets.stores,
        stores_total=facets.stores_total,
        pub_status=facets.pub_status,
        pub_type=facets.pub_type,
        alerts=alerts,
        stock=facets.stock,
        ageing=facets.ageing,
        product=facets.product,
    )


def _can_see_margin(db: Session, user: Usuario) -> bool:
    return PermisosService(db).tiene_permiso(user, PERMISO_GANANCIA)


def _scope_pairs(db: Session, user: Usuario) -> Optional[List[Tuple[str, str]]]:
    """The caller's PM scope: the upper-cased (marca, categoría) pairs they
    may see (`marcas_pm` + `marca_sub_pm`), `[]` for none (or an inactive
    user), `None` for a full-view caller. Resolved server-side from the
    authenticated user, never from the query, and handed to EVERY `Board`:
    the `pms` filter can only narrow it further."""
    return pm_scope.get_pares_marca_categoria_usuario(db, user)


def build_board_response(
    db: Session,
    f: board.BoardFilter,
    *,
    limit: int,
    offset: int,
    can_see_margin: bool,
    scope_pairs: Optional[Sequence[Tuple[str, str]]],
) -> BoardResponse:
    """Everything the board endpoint answers, in a FIXED number of SQL
    statements (see `board` module docstring): the page, the KPIs over the
    whole filtered set and every chip count. Split out of the endpoint so the
    Postgres volume test can drive exactly this.

    `scope_pairs` is required: callers must choose the visibility explicitly
    (`None` = full view, `[]` = nothing, a list = only those pairs)."""
    grouped = f.group_by == "group"
    with board.Board(db, f, scope_pairs=scope_pairs) as b:
        kpis = b.kpis()
        facets = b.facets()
        if grouped:
            # The money and the units are the products' (the groups add up to
            # them); what is counted -- and paged -- is the GROUPS.
            kpis.rows, kpis.with_sales = b.group_counts()
            rows = b.group_page(limit, offset)
        else:
            rows = b.page(limit, offset)
    prev_from, prev_to = board.previous_period(f)
    return BoardResponse(
        period=BoardPeriod(date_from=f.date_from, date_to=f.date_to, prev_from=prev_from, prev_to=prev_to),
        group_by=f.group_by,
        dimension=f.dimension if grouped else None,
        levels=list(groups.levels_of(f.dimension)) if grouped else None,
        total=kpis.rows,
        with_sales_count=kpis.with_sales,
        limit=limit,
        offset=offset,
        can_see_margin=can_see_margin,
        refreshed_at=board.refreshed_at(db),
        kpis=build_kpis(kpis, can_see_margin),
        facets=_facets(facets, can_see_margin),
        rows=[_row_out(row, can_see_margin, group_view=grouped) for row in rows],
    )


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/board", response_model=BoardResponse)
def get_board(
    f: board.BoardFilter = Depends(board_filter),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> BoardResponse:
    """The board: rows of the requested grouping (sorted and paged in SQL),
    the KPI strip over the WHOLE filtered set (never the page), and every
    chip count scoped by the other filters. Every number -- money, units, all
    windows, the 24h included -- from the orders themselves
    (`ml_daily_metrics.sales.sale_lines`), the same rules as Ventas ML."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    return build_board_response(
        db,
        f,
        limit=limit,
        offset=offset,
        can_see_margin=can_see_margin,
        scope_pairs=_scope_pairs(db, current_user),
    )


@router.get("/board/products/{product_item_id}/publications", response_model=PublicationsResponse)
def get_product_publications(
    product_item_id: int,
    f: board.BoardFilter = Depends(board_filter),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> PublicationsResponse:
    """A product row's publications (the expandable sub-rows), under the same
    filters as the board. `is_best` marks the one that earned the most in the
    period (Total Gauss, or gross without the margin permission).

    The ROW filters (alerts, stock, ageing, "solo con ventas") already decided that the
    product is on the board: its sub-rows are every publication passing the
    PAIR filters (store, status, type, brand, search), so they add up to the
    product row."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    by_pub = replace(
        f,
        group_by="publication",
        alerts=(),
        stock=(),
        stock_exclude=(),
        ageing=(),
        ageing_exclude=(),
        solo_con_ventas=False,
    )
    with board.Board(db, by_pub, product_item_id=product_item_id, scope_pairs=_scope_pairs(db, current_user)) as b:
        rows = b.page(limit=None, apply_alerts=False)
    out = [_row_out(row, can_see_margin) for row in rows]
    earned = (lambda r: (r.tg, r.units)) if can_see_margin else (lambda r: (r.gross, r.units))
    best = max(rows, key=earned, default=None)
    for row, item in zip(rows, out):
        item.is_best = best is not None and row is best and best.units > 0
    return PublicationsResponse(rows=out)


# A path is at most as long as the longest tree; each key is a brand, a store
# clave, an id... -- a few hundred characters at the very most.
MAX_PATH_KEY_LENGTH = 300


def _parse_path(raw: str, dimension: str) -> Tuple[str, ...]:
    """The node's path: a JSON list of 1..N keys (N = the group levels of the
    dimension's tree). It travels as ONE query param because a key may hold any
    character."""
    max_keys = len(groups.levels_of(dimension)) - 1
    try:
        keys = json.loads(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="path inválido: tiene que ser una lista JSON de claves") from e
    valid = (
        isinstance(keys, list)
        and 1 <= len(keys) <= max_keys
        and all(isinstance(key, str) and 0 < len(key) <= MAX_PATH_KEY_LENGTH for key in keys)
    )
    if not valid:
        raise HTTPException(
            status_code=422, detail=f"path inválido: de 1 a {max_keys} claves de texto para la dimensión {dimension!r}"
        )
    return tuple(keys)


@router.get("/board/group-nodes", response_model=GroupNodesResponse)
def get_group_nodes(
    path: str = Query(..., min_length=2, description="JSON list: the keys of the node's ancestors and its own"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    f: board.BoardFilter = Depends(board_filter),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> GroupNodesResponse:
    """What a node of the "Agrupado" tree opens into: the nodes of the level
    below it, or -- below the last level -- its PRODUCTS. Under the same filters
    as the board and the same `dimension`; every row of the page carries only
    the sales of its own path (under "tienda", the sales of that store's
    publications), so the page adds up to the node. Paged (a brand can hold
    thousands of products), in the board's sort order."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    scope = _parse_path(path, f.dimension)
    levels = groups.levels_of(f.dimension)
    leaf = len(scope) == len(levels) - 1
    with board.Board(
        db,
        replace(f, group_by="product" if leaf else "group"),
        scope=scope,
        scope_pairs=_scope_pairs(db, current_user),
    ) as b:
        if leaf:
            total = b.product_count()
            rows = b.page(limit, offset)
        else:
            total = b.group_counts()[0]
            rows = b.group_page(limit, offset)
    return GroupNodesResponse(
        level=levels[len(scope)],
        rows=[_row_out(row, can_see_margin, group_view=not leaf, leaf=leaf) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _csv_money(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.2f}".replace(".", ",")


class CsvLayout(NamedTuple):
    """How a board layout writes its lines: the columns that differ (named
    before the metric columns every layout shares) and how a row fills them."""

    header: List[str]
    head_of: Callable[[board.Row], list]


def _csv_layout(f: board.BoardFilter) -> CsvLayout:
    """The product/publication view names a row by its product, SKU, brand and
    MLA; the "Agrupado" view writes ONE row per product under each path of the
    tree, led by the display names of the path's levels."""
    if f.group_by != "group":
        return CsvLayout(
            ["Producto", "SKU", "Marca", "MLA"],
            lambda row: [csv_text(row.title), csv_text(row.sku), csv_text(row.marca), csv_text(row.mla)],
        )
    levels = groups.levels_of(f.dimension)[:-1]
    # The brand is a column of its own only when no level of the path is it.
    with_marca = "marca" not in levels
    header = [LEVEL_HEADERS[kind] for kind in levels] + ["Producto", "SKU"] + (["Marca"] if with_marca else [])
    return CsvLayout(
        header + ["Publicaciones"],
        lambda row: [
            *(csv_text(name) for name in row.path),
            csv_text(row.title),
            csv_text(row.sku),
            *([csv_text(row.marca)] if with_marca else []),
            row.publications_count,
        ],
    )


def _csv_line(row: board.Row, can_see_margin: bool, layout: CsvLayout) -> list:
    """One CSV line: the layout's own columns, then the ones every layout
    shares, in the same order (units and windows, money, margin when allowed,
    last sale, ageing, stock)."""
    line = layout.head_of(row) + [
        row.units,
        row.units_24h,
        row.windows["3d"],
        row.windows["7d"],
        row.windows["15d"],
        row.windows["30d"],
        _csv_money(round_money(row.gross)),
    ]
    if can_see_margin:
        line += [
            _csv_money(round_money(row.tg)),
            _csv_money(round_pp(row.markup)),
            _csv_money(round_pp(row.markup_prev)),
            _csv_money(round_pp(row.markup_delta)),
        ]
    line += [
        row.last_sale_at.isoformat() if row.last_sale_at else "",
        row.ageing_days if row.ageing_days is not None else "",
        row.stock if row.stock is not None else "",
    ]
    return line


# The CSV header of each level of the "Agrupado" tree.
LEVEL_HEADERS = {
    "marca": "Marca",
    "categoria": "Categoría",
    "subcategoria": "Subcategoría",
    groups.SUBCATEGORIA_IN_CATEGORIA: "Subcategoría · Categoría",
    "tienda": "Tienda",
    "pm": "PM",
}
# A level added to the board without its header would KeyError the export.
if set(LEVEL_HEADERS) != set(groups.LEVEL_KINDS):
    raise RuntimeError("LEVEL_HEADERS must cover groups.LEVEL_KINDS")


@router.get("/board/export")
def export_board(
    f: board.BoardFilter = Depends(board_filter),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """CSV of every filtered row, same columns as the board (no sparklines),
    STREAMED page by page. Margin columns only with `ml_metricas.ver_ganancia`.

    The first short transaction fixes the ORDERED list of row keys (at most
    `EXPORT_MAX_ROWS`, else 422) and reads page 1, before the 200, so a bad
    state fails as a normal HTTP error. Each later page of
    `EXPORT_PAGE_SIZE` keys runs on its OWN short session
    (`get_background_db`) and fetches its rows BY KEY, so a change between
    pages can never repeat or drop a row. The request session is closed
    before the first byte: the response outlives the handler, and a session
    held for the whole download pins a pooled connection while the client
    reads (QueuePool incident, PR #811) -- same discipline as the Ventas ML
    export. Each page builds its own pair table in its own transaction
    (PgBouncer, see `board`). A page failing mid-stream ends the file with an
    explicit error line."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    # Resolved ONCE, here, on the request session: every page runs on its own
    # background session and gets the plain list.
    scope_pairs = _scope_pairs(db, current_user)

    # The FIRST short transaction fixes the ordered keys of every row (and
    # reads page 1): the pages after it fetch rows BY KEY, so a sale or a
    # metrics recompute between pages can never repeat or drop a row. A key whose
    # row stopped matching the filters meanwhile is skipped; every other row
    # is written once, with its values as of its own page.
    grouped = f.group_by == "group"
    layout = _csv_layout(f)
    # The layout is chosen ONCE: how the keys and the rows of a page are read.
    # The "Agrupado" export is one row per product under each path of the tree.
    keys_of = board.Board.leaf_keys if grouped else board.Board.ordered_keys
    rows_of = board.Board.leaves_for_keys if grouped else board.Board.rows_for_keys
    with get_background_db() as first_db:
        with board.Board(first_db, f, through_leaves=grouped, scope_pairs=scope_pairs) as b:
            keys = keys_of(b, EXPORT_MAX_ROWS + 1)
            if len(keys) > EXPORT_MAX_ROWS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Son más de {EXPORT_MAX_ROWS} filas, demasiadas para exportar de una vez. "
                        "Acotá los filtros (tienda, marca, búsqueda...)."
                    ),
                )
            first = rows_of(b, keys[:EXPORT_PAGE_SIZE])

    def fetch_page(page_keys: Sequence) -> List[board.Row]:
        with get_background_db() as page_db:
            with board.Board(page_db, f, through_leaves=grouped, scope_pairs=scope_pairs) as b:
                return rows_of(b, page_keys)

    def lines_of(rows: List[board.Row]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        for row in rows:
            writer.writerow(_csv_line(row, can_see_margin, layout))
        return buffer.getvalue()

    # CLOSE the request session (the permission check left it holding a
    # pooled connection): nothing may stay tied to the response's lifetime.
    db.close()

    header = layout.header + ["Unidades", "24h", "3d", "7d", "15d", "30d", "Facturado"]
    if can_see_margin:
        header += ["Total Gauss", "Markup %", "Markup anterior %", "Variación pp"]
    header += ["Última venta", "Ageing (días)", "Stock"]

    def stream():
        head = io.StringIO()
        csv.writer(head, delimiter=";").writerow(header)
        # BOM so Excel reads the accents as UTF-8.
        yield "\ufeff" + head.getvalue()
        rows, exported = first, 0
        for start in range(0, len(keys), EXPORT_PAGE_SIZE):
            if start:
                try:
                    rows = fetch_page(keys[start : start + EXPORT_PAGE_SIZE])
                except Exception:  # noqa: BLE001
                    # The 200 and the header are already on the wire: the
                    # status cannot change, so the FILE says it is incomplete.
                    logger.exception("metricas-ml export: page at %s failed", start)
                    yield (
                        f"# ERROR: exportación incompleta — {exported} de {len(keys)} filas exportadas. "
                        "Volvé a intentar.\n"
                    )
                    return
            yield lines_of(rows)
            exported += len(rows)

    by = f"por-{f.dimension}-" if grouped else ""
    filename = f"metricas-ml-{by}{f.date_from.isoformat()}-{f.date_to.isoformat()}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
