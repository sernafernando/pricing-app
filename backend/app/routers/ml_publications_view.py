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

from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.services.ml_publications import settings_store
from app.services.ml_publications.view import listing, status_block
from app.services.ml_publications.view.filters import FilterError, parse_filter
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


# ── Reads (ml_ops.ver) ───────────────────────────────────────────


def _timed_out(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "pgcode", None) == QUERY_CANCELED


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
    tipo: Optional[str] = Query(None, description="csv of clasica,premium,catalogo,full"),
    vinculo: Optional[str] = Query(None, description="csv of auto,manual,sin_producto,conflicto,no_evaluado"),
    stock: Optional[str] = Query(None, description="csv of sin_stock,full_sin_stock"),
    evento: Optional[str] = Query(None, description="csv of event types; needs events.enabled"),
    evento_desde: Optional[str] = Query(None, description="24h, 7d or 30d"),
    orden: Optional[str] = Query(None, description="actividad (default), precio, titulo, stock_full, actualizado"),
    direction: Optional[str] = Query(None, alias="dir", description="asc or desc"),
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
) -> dict[str, Any]:
    """One page of publications (one row per MLA) with the honest-state block."""
    timer = Timer("items")
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
            tipo=tipo,
            vinculo=vinculo,
            stock=stock,
            evento=evento,
            evento_desde=evento_desde,
        )
        sort = listing.parse_sort(orden, direction)
        with timer.stage("flags"):
            events_enabled = settings_store.get_setting("events.enabled").value is True
        listing.bound(db)
        f = listing.resolve_pm_pairs(db, f)  # once: the list and the facets share the resolved pairs
        with timer.stage("list"):
            page = listing.list_items(db, f, sort, limit, offset, events=events_enabled)
        facet_counts = None
        if facets:
            with timer.stage("facets"):
                facet_counts = {**listing.facets(db, f), "total": page.total}
    except FilterError as exc:
        error = api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_ERROR, str(exc))
        error.detail["field"] = exc.field
        raise error from exc
    except DBAPIError as exc:
        if _timed_out(exc):
            raise api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE, SLOW_QUERY_CODE, "La consulta tardó demasiado; reintentá."
            ) from exc
        raise
    finally:
        db.rollback()  # ends the read-only work (and its SET LOCAL); nothing was written
    with timer.stage("status"):
        data_state = status_provider()
    response.headers["Server-Timing"] = timer.server_timing()
    timer.emit(rows=len(page.items), total=page.total)
    body: dict[str, Any] = {
        "items": page.items,
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "can_see_margin": PermisosService(auth_db).tiene_permiso(user, PERMISO_GANANCIA),
        "events_enabled": events_enabled,
        "data_state": data_state,
    }
    if facet_counts is not None:
        body["facets"] = facet_counts
    return body
