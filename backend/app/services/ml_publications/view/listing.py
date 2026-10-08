"""The list of publications (design §3.1, §5.1): one row per MLA, filtered, sorted and paged, plus facets.

Statement count is constant for the size of the page: one COUNT, one page SELECT, and one statement per
page-level extra (variation counts, last event, store labels), however many rows the page holds (spec NFR-3).
Reads run under `SET LOCAL statement_timeout` (PgBouncer in transaction mode: LOCAL only, never session state).

Every ordering ends with `item_id`, so paging never repeats or skips a row (spec SRT-2).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.marca_pm import MarcaPM
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.services.ml_publications.view.filters import (
    FULFILLMENT,
    FilterError,
    PublicationFilter,
    T,
    build_base_select,
    link_state,
)

STATEMENT_TIMEOUT = "8s"
SORT_ACTIVITY = "actividad"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


@dataclass(frozen=True)
class Sort:
    key: str
    descending: bool


@dataclass(frozen=True)
class ItemsPage:
    items: list[dict[str, Any]]
    total: int


def parse_sort(orden: Optional[str], dir: Optional[str]) -> Sort:
    key = (orden or SORT_ACTIVITY).strip()
    if key != SORT_ACTIVITY:
        raise FilterError("orden", f"unknown value {key!r}; known: {SORT_ACTIVITY}")
    return Sort(key, descending=True)


def bound(db: Session) -> None:
    """Bound the rest of the request's transaction in time (released by the commit or rollback that ends it)."""
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))


def resolve_pm_pairs(db: Session, f: PublicationFilter) -> PublicationFilter:
    """Fill `pm_pairs` from the PMs' (marca, categoria) assignments, the same upper-cased rule as the sales query."""
    if not f.pms or f.pm_pairs is not None:
        return f
    rows = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(f.pms)).all()
    return replace(f, pm_pairs=tuple(sorted({(marca.upper(), categoria.upper()) for marca, categoria in rows})))


def _row_columns() -> list[Any]:
    i, sp, l, p, st = T.i, T.sp, T.l, T.p, T.st  # noqa: E741
    return [
        i.item_id,
        i.title,
        i.thumbnail,
        i.permalink,
        i.status,
        i.sub_status,
        i.listing_type_id,
        i.catalog_listing,
        i.logistic_type,
        i.official_store_id,
        i.brand.label("ml_brand"),
        i.family_id,
        i.family_name,
        i.user_product_id,
        i.available_quantity,
        i.price.label("item_price"),
        i.last_trigger_received_at,
        i.gone_at,
        sp.amount.label("sale_amount"),
        sp.regular_amount,
        sp.promotion_type,
        sp.campaign_id,
        link_state().label("link_state"),
        l.producto_item_id,
        p.codigo,
        p.descripcion,
        p.marca,
        st.full_quantity,
        st.own_quantity,
        st.ml_last_updated.label("stock_as_of"),
    ]


def _order_by(sort: Sort) -> list[Any]:
    activity = T.i.last_trigger_received_at
    primary = activity.desc() if sort.descending else activity.asc()
    return [primary.nulls_last(), T.i.item_id]


def _price(row: Any) -> dict[str, Any]:
    if row.sale_amount is not None:
        amount, source = row.sale_amount, "sale_price"
    elif row.item_price is not None:
        amount, source = row.item_price, "item_price"
    else:
        amount, source = None, None
    return {
        "amount": amount,
        "source": source,
        "regular_amount": row.regular_amount if source == "sale_price" else None,
        "promotion_type": row.promotion_type if source == "sale_price" else None,
        "campaign": row.campaign_id if source == "sale_price" else None,
        "pricelist_id": None,  # resolved with the markup (P6)
    }


def _item(row: Any, variations: dict[str, int], labels: dict[int, str], last_events: Optional[dict[str, Any]]) -> dict:
    item = {
        "item_id": row.item_id,
        "title": row.title,
        "thumbnail": row.thumbnail,
        "permalink": row.permalink,
        "status": row.status,
        "sub_status": list(row.sub_status or []),
        "listing_type_id": row.listing_type_id,
        "catalog_listing": row.catalog_listing,
        "logistic_type": row.logistic_type,
        "is_full": row.logistic_type == FULFILLMENT,
        "official_store_id": row.official_store_id,
        "store_label": labels.get(row.official_store_id),
        "ml_brand": row.ml_brand,
        "family_id": row.family_id,
        "family_name": row.family_name,
        "user_product_id": row.user_product_id,
        "variations_count": variations.get(row.item_id, 0),
        "gone": row.gone_at is not None,
        "gone_at": row.gone_at,
        "price": _price(row),
        "stock": {
            "available": row.available_quantity,
            "full": row.full_quantity,
            "own": row.own_quantity,
            "as_of": row.stock_as_of,
        },
        "link": {
            "state": row.link_state,
            "producto_item_id": row.producto_item_id,
            "codigo": row.codigo,
            "descripcion": row.descripcion,
            "marca": row.marca,
        },
        "last_activity_at": row.last_trigger_received_at,
    }
    if last_events is not None:
        item["last_event"] = last_events.get(row.item_id)
    return item


def _variation_counts(db: Session, ids: list[str]) -> dict[str, int]:
    rows = db.execute(
        select(T.v.item_id, func.count()).where(T.v.item_id.in_(ids), T.v.gone_at.is_(None)).group_by(T.v.item_id)
    )
    return {item_id: count for item_id, count in rows}


def _store_labels(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = db.query(MlTiendaOficial.store_id, MlTiendaOficial.nombre).filter(MlTiendaOficial.store_id.in_(ids))
    return {store_id: nombre for store_id, nombre in rows}


def _last_events(db: Session, ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        select(T.e.item_id, T.e.event_type, T.e.observed_at)
        .where(T.e.item_id.in_(ids))
        .distinct(T.e.item_id)
        .order_by(T.e.item_id, T.e.observed_at.desc(), T.e.id.desc())
    )
    return {item_id: {"event_type": event_type, "observed_at": at} for item_id, event_type, at in rows}


def list_items(db: Session, f: PublicationFilter, sort: Sort, limit: int, offset: int, *, events: bool) -> ItemsPage:
    """One page of publications. `events` is the `events.enabled` flag: the event filter needs it and the last
    event is only read while it is on."""
    if f.needs_events and not events:
        raise FilterError("evento", "requires the events flag (events.enabled) to be on")
    f = resolve_pm_pairs(db, f)
    total = db.execute(build_base_select(f, func.count())).scalar_one()
    if total == 0 or offset >= total:
        return ItemsPage([], total)
    rows = db.execute(
        build_base_select(f, *_row_columns()).order_by(*_order_by(sort)).limit(limit).offset(offset)
    ).all()
    ids = [row.item_id for row in rows]
    variations = _variation_counts(db, ids)
    labels = _store_labels(db, sorted({row.official_store_id for row in rows if row.official_store_id is not None}))
    last_events = _last_events(db, ids) if events else None
    return ItemsPage([_item(row, variations, labels, last_events) for row in rows], total)
