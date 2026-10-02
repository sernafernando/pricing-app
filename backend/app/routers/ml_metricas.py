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
import logging
import io
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_background_db, get_db
from app.models.usuario import Usuario
from app.services.ml_sales_query.params import parse_csv_ids, parse_csv_stores, parse_csv_strings
from app.services.ml_daily_metrics import board
from app.services.permisos_service import PermisosService
from app.utils.csv_cells import csv_text

PERMISO_VER = "ml_metricas.ver"
PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
DEFAULT_PERIOD_DAYS = 30
# The KPI daily series holds one entry per day of the period: an unbounded
# range would build millions of them in memory. One year (a leap year
# included) is the most the screen offers ("3m" preset, custom ranges).
MAX_PERIOD_DAYS = 366
# The CSV streams this many rows per page, each page on its own short DB
# session: memory and the pooled connection follow ONE page, never the file.
EXPORT_PAGE_SIZE = 500
# The export fixes the ordered list of row keys up front (see `export_board`);
# beyond this many rows it refuses and asks for narrower filters, like the
# Ventas ML export.
EXPORT_MAX_ROWS = 10_000
# Sane ends for the period AND its comparison period (a year back, or the
# same length back), so the date arithmetic can never underflow/overflow.
MIN_BOARD_DATE = date(2001, 1, 1)
MAX_BOARD_DATE = date(2100, 12, 31)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml-metricas", tags=["ML Métricas"])


def require_ver(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not PermisosService(db).tiene_permiso(current_user, PERMISO_VER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Falta el permiso {PERMISO_VER}")
    return current_user


# ── Response models ──────────────────────────────────────────────


class BoardPeriod(BaseModel):
    date_from: date
    date_to: date
    prev_from: date
    prev_to: date


class BoardRow(BaseModel):
    key: str
    product_item_id: int
    mla: Optional[str] = None
    title: str
    sku: Optional[str] = None
    marca: Optional[str] = None
    publications_count: int
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
    alerts: List[str]
    # Publication attributes (publication rows and nested rows only).
    status: Optional[str] = None
    listing_type: Optional[str] = None
    is_catalog: Optional[bool] = None
    is_full: Optional[bool] = None
    store_id: Optional[int] = None
    is_best: Optional[bool] = None
    thumbnail: Optional[str] = None


class KpiMoney(BaseModel):
    value: Optional[float] = None
    delta_pct: Optional[float] = None
    series: Optional[List[float]] = None


class KpiUnits(BaseModel):
    value: int
    delta_pct: Optional[float] = None
    series: List[int]


class KpiMarkup(BaseModel):
    value: Optional[float] = None
    delta_pp: Optional[float] = None
    series: Optional[List[Optional[float]]] = None


class KpiShare(BaseModel):
    value: int
    of_total: int


class KpiAgeing(BaseModel):
    """Ageing of the filtered rows (days since the last sale, or since the
    publication started if it never sold). The three buckets split ALL the
    rows with an ageing and drive the card's bar: up to 30 days, 31 to 60
    days, over 60 days (the "Ageing > 60d" alert)."""

    avg_days: Optional[float] = None
    up_to_30: int
    from_31_to_60: int
    over_60: int


class BoardKpis(BaseModel):
    units: KpiUnits
    gross: KpiMoney
    total_gauss: KpiMoney
    markup: KpiMarkup
    # Rows with sales in the period / all rows: products, or publications
    # when the board is grouped by publication.
    rows_with_sales: KpiShare
    ageing: KpiAgeing


class BoardFacets(BaseModel):
    stores: Dict[str, int]
    stores_total: int
    pub_status: Dict[str, int]
    pub_type: Dict[str, int]
    alerts: Dict[str, Optional[int]]


class BoardResponse(BaseModel):
    period: BoardPeriod
    group_by: str
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
    stores: Optional[str] = Query(default=None, description="CSV de mlp_official_store_id y/o 'sin_tienda'"),
    marcas: Optional[str] = Query(default=None),
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
    sort: str = Query(default="gross", description=" | ".join(board.SORTS)),
    sort_dir: str = Query(default="desc", description="asc | desc"),
) -> board.BoardFilter:
    """Every board filter, validated (422 on anything unknown)."""
    if group_by not in board.GROUP_BY:
        raise HTTPException(status_code=422, detail=f"group_by inválido: {group_by!r}")
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
    return board.BoardFilter(
        date_from=desde,
        date_to=hasta,
        compare=comparar_con,
        group_by=group_by,
        stores=parse_csv_stores(stores),
        marcas=parse_csv_strings(marcas, "marcas"),
        subcategorias=parse_csv_ids(subcategorias, "subcategorias"),
        pms=parse_csv_ids(pms, "pms"),
        q=q.strip() if q and q.strip() else None,
        pub_status=pub_status_in,
        pub_type=pub_type_in,
        pub_status_exclude=pub_status_out,
        pub_type_exclude=pub_type_out,
        alerts=_parse_choices(alerts, "alerts", board.ALERTS),
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


def _f(value) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def _pp(value) -> Optional[float]:
    return None if value is None else round(float(value), 1)


def _delta_pct(now, before) -> Optional[float]:
    if not before:
        return None
    return round((float(now) - float(before)) / float(before) * 100, 1)


def _row_out(row: board.Row, can_see_margin: bool) -> BoardRow:
    known = [m for m in row.series_markup if m is not None]
    pub = row.pub
    alerts = sorted(row.alerts() - (set() if can_see_margin else {"margen_cayendo"}))
    return BoardRow(
        key=row.key,
        product_item_id=row.product_item_id,
        mla=row.mla,
        title=row.title,
        sku=row.sku,
        marca=row.marca,
        publications_count=row.publications_count,
        units=row.units,
        units_24h=row.units_24h,
        units_3d=row.windows["3d"],
        units_7d=row.windows["7d"],
        units_15d=row.windows["15d"],
        units_30d=row.windows["30d"],
        gross=_f(row.gross),
        total_gauss=_f(row.tg) if can_see_margin else None,
        markup_pct=_pp(row.markup) if can_see_margin else None,
        markup_prev_pct=_pp(row.markup_prev) if can_see_margin else None,
        markup_delta_pp=_pp(row.markup_delta) if can_see_margin else None,
        markup_min_90d=(min(known) if known else None) if can_see_margin else None,
        markup_max_90d=(max(known) if known else None) if can_see_margin else None,
        series_units_90d=row.series_units,
        series_markup_90d=row.series_markup if can_see_margin else None,
        last_sale_at=row.last_sale_at,
        ageing_days=row.ageing_days,
        alerts=alerts,
        status=pub.status if pub else None,
        listing_type=pub.listing_type if pub else None,
        is_catalog=pub.is_catalog if pub else None,
        is_full=pub.is_full if pub else None,
        store_id=pub.store_id if pub else None,
        thumbnail=row.thumbnail,
    )


def _kpis(k: board.Kpis, can_see_margin: bool) -> BoardKpis:
    markup = board.markup_of(k.mtg, k.costo)
    markup_prev = board.markup_of(k.prev_mtg, k.prev_costo)
    return BoardKpis(
        units=KpiUnits(value=k.units, delta_pct=_delta_pct(k.units, k.prev_units), series=k.series_units),
        gross=KpiMoney(value=_f(k.gross), delta_pct=_delta_pct(k.gross, k.prev_gross), series=k.series_gross),
        total_gauss=(
            KpiMoney(value=_f(k.tg), delta_pct=_delta_pct(k.tg, k.prev_tg), series=k.series_tg)
            if can_see_margin
            else KpiMoney()
        ),
        markup=(
            KpiMarkup(
                value=_pp(markup),
                delta_pp=_pp(markup - markup_prev) if markup is not None and markup_prev is not None else None,
                series=k.series_markup,
            )
            if can_see_margin
            else KpiMarkup()
        ),
        rows_with_sales=KpiShare(value=k.with_sales, of_total=k.rows),
        ageing=KpiAgeing(
            avg_days=round(k.ageing_avg, 1) if k.ageing_avg is not None else None,
            up_to_30=k.up_to_30,
            from_31_to_60=k.from_31_to_60,
            over_60=k.over_60,
        ),
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
    )


def _can_see_margin(db: Session, user: Usuario) -> bool:
    return PermisosService(db).tiene_permiso(user, PERMISO_GANANCIA)


def build_board_response(
    db: Session, f: board.BoardFilter, *, limit: int, offset: int, can_see_margin: bool
) -> BoardResponse:
    """Everything the board endpoint answers, in a FIXED number of SQL
    statements (see `board` module docstring): the page, the KPIs over the
    whole filtered set and every chip count. Split out of the endpoint so the
    Postgres volume test can drive exactly this."""
    with board.Board(db, f) as b:
        kpis = b.kpis()
        facets = b.facets()
        rows = b.page(limit, offset)
    prev_from, prev_to = board.previous_period(f)
    return BoardResponse(
        period=BoardPeriod(date_from=f.date_from, date_to=f.date_to, prev_from=prev_from, prev_to=prev_to),
        group_by=f.group_by,
        total=kpis.rows,
        with_sales_count=kpis.with_sales,
        limit=limit,
        offset=offset,
        can_see_margin=can_see_margin,
        refreshed_at=board.refreshed_at(db),
        kpis=_kpis(kpis, can_see_margin),
        facets=_facets(facets, can_see_margin),
        rows=[_row_out(row, can_see_margin) for row in rows],
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
    return build_board_response(db, f, limit=limit, offset=offset, can_see_margin=can_see_margin)


@router.get("/board/products/{product_item_id}/publications", response_model=PublicationsResponse)
def get_product_publications(
    product_item_id: int,
    f: board.BoardFilter = Depends(board_filter),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> PublicationsResponse:
    """A product row's publications (the expandable sub-rows), under the same
    filters as the board. `is_best` marks the one that earned the most in the
    period (Total Gauss, or gross without the margin permission)."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    by_pub = replace(f, group_by="publication", alerts=())
    with board.Board(db, by_pub, product_item_id=product_item_id) as b:
        rows = b.page(limit=None, apply_alerts=False)
    out = [_row_out(row, can_see_margin) for row in rows]
    earned = (lambda r: (r.tg, r.units)) if can_see_margin else (lambda r: (r.gross, r.units))
    best = max(rows, key=earned, default=None)
    for row, item in zip(rows, out):
        item.is_best = best is not None and row is best and best.units > 0
    return PublicationsResponse(rows=out)


def _csv_money(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.2f}".replace(".", ",")


def _csv_line(row: board.Row, can_see_margin: bool) -> list:
    line = [
        csv_text(row.title),
        csv_text(row.sku),
        csv_text(row.marca),
        csv_text(row.mla),
        row.units,
        row.units_24h,
        row.windows["3d"],
        row.windows["7d"],
        row.windows["15d"],
        row.windows["30d"],
        _csv_money(_f(row.gross)),
    ]
    if can_see_margin:
        line += [
            _csv_money(_f(row.tg)),
            _csv_money(_pp(row.markup)),
            _csv_money(_pp(row.markup_prev)),
            _csv_money(_pp(row.markup_delta)),
        ]
    line += [
        row.last_sale_at.isoformat() if row.last_sale_at else "",
        row.ageing_days if row.ageing_days is not None else "",
    ]
    return line


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

    # The FIRST short transaction fixes the ordered keys of every row (and
    # reads page 1): the pages after it fetch rows BY KEY, so a sale or a
    # metrics recompute between pages can never repeat or drop a row. A key whose
    # row stopped matching the filters meanwhile is skipped; every other row
    # is written once, with its values as of its own page.
    with get_background_db() as first_db:
        with board.Board(first_db, f) as b:
            keys = b.ordered_keys(EXPORT_MAX_ROWS + 1)
            if len(keys) > EXPORT_MAX_ROWS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Son más de {EXPORT_MAX_ROWS} filas, demasiadas para exportar de una vez. "
                        "Acotá los filtros (tienda, marca, búsqueda...)."
                    ),
                )
            first = b.rows_for_keys(keys[:EXPORT_PAGE_SIZE])

    def fetch_page(page_keys: List[str]) -> List[board.Row]:
        with get_background_db() as page_db:
            with board.Board(page_db, f) as b:
                return b.rows_for_keys(page_keys)

    def lines_of(rows: List[board.Row]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        for row in rows:
            writer.writerow(_csv_line(row, can_see_margin))
        return buffer.getvalue()

    # CLOSE the request session (the permission check left it holding a
    # pooled connection): nothing may stay tied to the response's lifetime.
    db.close()

    header = ["Producto", "SKU", "Marca", "MLA", "Unidades", "24h", "3d", "7d", "15d", "30d", "Facturado"]
    if can_see_margin:
        header += ["Total Gauss", "Markup %", "Markup anterior %", "Variación pp"]
    header += ["Última venta", "Ageing (días)"]

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

    filename = f"metricas-ml-{f.date_from.isoformat()}-{f.date_to.isoformat()}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
