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
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.routers.ml_ventas_ops import _parse_csv_ids, _parse_csv_stores, _parse_csv_strings
from app.services.ml_daily_metrics import board
from app.services.permisos_service import PermisosService

PERMISO_VER = "ml_metricas.ver"
PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
DEFAULT_PERIOD_DAYS = 30

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
    avg_days: Optional[float] = None
    over_60: int


class BoardKpis(BaseModel):
    units: KpiUnits
    gross: KpiMoney
    total_gauss: KpiMoney
    markup: KpiMarkup
    products_with_sales: KpiShare
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
    values = _parse_csv_strings(raw, field)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise HTTPException(status_code=422, detail=f"{field} inválido: {bad} (esperado {', '.join(allowed)})")
    return values


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
    desde = _parse_day(date_from, "date_from") or hasta - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if desde > hasta:
        raise HTTPException(status_code=422, detail="date_from es posterior a date_to")
    return board.BoardFilter(
        date_from=desde,
        date_to=hasta,
        compare=comparar_con,
        group_by=group_by,
        stores=_parse_csv_stores(stores),
        marcas=_parse_csv_strings(marcas, "marcas"),
        subcategorias=_parse_csv_ids(subcategorias, "subcategorias"),
        pms=_parse_csv_ids(pms, "pms"),
        q=q.strip() if q and q.strip() else None,
        pub_status=_parse_choices(pub_status, "pub_status", board.PUB_STATUSES),
        pub_type=_parse_choices(pub_type, "pub_type", board.PUB_TYPES),
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


def _row_out(u: board.Universe, row: board.Row, f: board.BoardFilter, can_see_margin: bool) -> BoardRow:
    units_series, markup_series = board.series_for(u, row, f)
    known = [m for m in markup_series if m is not None]
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
        series_units_90d=units_series,
        series_markup_90d=markup_series if can_see_margin else None,
        last_sale_at=row.last_sale_at,
        ageing_days=row.ageing_days,
        alerts=alerts,
        status=pub.status if pub else None,
        listing_type=pub.listing_type if pub else None,
        is_catalog=pub.is_catalog if pub else None,
        is_full=pub.is_full if pub else None,
        store_id=pub.store_id if pub else None,
    )


def _kpis(u: board.Universe, rows: List[board.Row], f: board.BoardFilter, can_see_margin: bool) -> BoardKpis:
    units = sum(r.units for r in rows)
    gross = sum((r.gross for r in rows), start=Decimal("0"))
    tg = sum((r.tg for r in rows), start=Decimal("0"))
    costo = sum((r.costo for r in rows), start=Decimal("0"))
    prev_units = sum(u.pairs[p].prev_units for r in rows for p in r.pairs)
    prev_gross = sum((u.pairs[p].prev_gross for r in rows for p in r.pairs), start=Decimal("0"))
    prev_tg = sum((r.prev_tg for r in rows), start=Decimal("0"))
    prev_costo = sum((r.prev_costo for r in rows), start=Decimal("0"))
    markup = board.markup_of(tg, costo)
    markup_prev = board.markup_of(prev_tg, prev_costo)
    series = board.period_series(u, rows, f, f.date_from, f.date_to)
    ageing = [r.ageing_days for r in rows if r.ageing_days is not None]
    return BoardKpis(
        units=KpiUnits(value=units, delta_pct=_delta_pct(units, prev_units), series=series["units"]),
        gross=KpiMoney(value=_f(gross), delta_pct=_delta_pct(gross, prev_gross), series=series["gross"]),
        total_gauss=(
            KpiMoney(value=_f(tg), delta_pct=_delta_pct(tg, prev_tg), series=series["total_gauss"])
            if can_see_margin
            else KpiMoney()
        ),
        markup=(
            KpiMarkup(
                value=_pp(markup),
                delta_pp=_pp(markup - markup_prev) if markup is not None and markup_prev is not None else None,
                series=series["markup"],
            )
            if can_see_margin
            else KpiMarkup()
        ),
        products_with_sales=KpiShare(value=sum(1 for r in rows if r.units > 0), of_total=len(rows)),
        ageing=KpiAgeing(
            avg_days=round(sum(ageing) / len(ageing), 1) if ageing else None,
            over_60=sum(1 for r in rows if "ageing_60d" in r.alerts()),
        ),
    )


def _facets(u: board.Universe, f: board.BoardFilter, can_see_margin: bool) -> BoardFacets:
    def count_by(skip: str, buckets_of) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in board.build_rows(u, f, skip=skip):
            for bucket in buckets_of(row):
                counts[bucket] = counts.get(bucket, 0) + 1
        return counts

    def pubs_of(row: board.Row) -> List[board.Pub]:
        return [u.pubs.get(mla) or board.Pub(mla=mla) for _p, mla in row.pairs]

    store_rows = board.build_rows(u, f, skip="stores")
    stores: Dict[str, int] = {}
    for row in store_rows:
        for bucket in {p.store_bucket for p in pubs_of(row)}:
            stores[bucket] = stores.get(bucket, 0) + 1
    pub_status = count_by("pub_status", lambda row: {p.status for p in pubs_of(row) if p.status})
    pub_type = count_by("pub_type", lambda row: set().union(*(p.types() for p in pubs_of(row))))
    alert_rows = board.build_rows(u, f, skip="alerts")
    alerts: Dict[str, Optional[int]] = {
        name: sum(1 for row in alert_rows if name in row.alerts()) for name in board.ALERTS
    }
    if not can_see_margin:
        alerts["margen_cayendo"] = None
    return BoardFacets(
        stores=stores, stores_total=len(store_rows), pub_status=pub_status, pub_type=pub_type, alerts=alerts
    )


def _can_see_margin(db: Session, user: Usuario) -> bool:
    return PermisosService(db).tiene_permiso(user, PERMISO_GANANCIA)


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/board", response_model=BoardResponse)
def get_board(
    f: board.BoardFilter = Depends(board_filter),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> BoardResponse:
    """The board: rows of the requested grouping (sorted, paged), the KPI
    strip over the WHOLE filtered set (never the page), and every chip
    count scoped by the other filters. Money and units from the daily rollup
    (`ml_product_daily_metrics`); the 24h window from the orders."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    u = board.load_universe(db, f)
    rows = board.sort_rows(board.build_rows(u, f), f)
    page = rows[offset : offset + limit]
    prev_from, prev_to = board.previous_period(f)
    return BoardResponse(
        period=BoardPeriod(date_from=f.date_from, date_to=f.date_to, prev_from=prev_from, prev_to=prev_to),
        group_by=f.group_by,
        total=len(rows),
        with_sales_count=sum(1 for r in rows if r.units > 0),
        limit=limit,
        offset=offset,
        can_see_margin=can_see_margin,
        refreshed_at=board.refreshed_at(db),
        kpis=_kpis(u, rows, f, can_see_margin),
        facets=_facets(u, f, can_see_margin),
        rows=[_row_out(u, row, f, can_see_margin) for row in page],
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
    period (Total Gauss, or gross without the margin permission)."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    u = board.load_universe(db, f)
    by_pub = board.BoardFilter(**{**f.__dict__, "group_by": "publication", "alerts": ()})
    rows = [r for r in board.build_rows(u, by_pub) if any(p == product_item_id for p, _m in r.pairs)]
    rows = board.sort_rows(rows, by_pub)
    out = [_row_out(u, row, by_pub, can_see_margin) for row in rows]
    earned = (lambda r: (r.tg, r.units)) if can_see_margin else (lambda r: (r.gross, r.units))
    best = max(rows, key=earned, default=None)
    for row, item in zip(rows, out):
        item.is_best = best is not None and row is best and best.units > 0
    return PublicationsResponse(rows=out)


def _csv_money(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.2f}".replace(".", ",")


@router.get("/board/export")
def export_board(
    f: board.BoardFilter = Depends(board_filter),
    current_user: Usuario = Depends(require_ver),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """CSV of every filtered row (no paging), same columns as the board.
    Margin columns only with `ml_metricas.ver_ganancia`."""
    can_see_margin = _can_see_margin(db, current_user)
    _margin_gate(f, can_see_margin)
    u = board.load_universe(db, f)
    rows = board.sort_rows(board.build_rows(u, f), f)
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=";")
    header = ["Producto", "SKU", "Marca", "MLA", "Unidades", "24h", "3d", "7d", "15d", "30d", "Facturado"]
    if can_see_margin:
        header += ["Total Gauss", "Markup %", "Markup anterior %", "Variación pp"]
    header += ["Última venta", "Ageing (días)"]
    writer.writerow(header)
    for row in rows:
        line = [
            row.title,
            row.sku or "",
            row.marca or "",
            row.mla or "",
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
        writer.writerow(line)
    buffer.seek(0)
    filename = f"metricas-ml-{f.date_from.isoformat()}-{f.date_to.isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
