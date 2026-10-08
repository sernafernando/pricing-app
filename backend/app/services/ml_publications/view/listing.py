"""The list of publications (design §3.1, §5.1): one row per MLA, filtered, sorted and paged, plus facets.

Statement count is constant for the size of the page: one COUNT, one page SELECT, and one statement per
page-level extra (variation counts, last event, store labels), however many rows the page holds (spec NFR-3).
Reads run under `SET LOCAL statement_timeout` (PgBouncer in transaction mode: LOCAL only, never session state).

Every ordering ends with `item_id`, so paging never repeats or skips a row (spec SRT-2).

Postgres only (`DISTINCT ON` for the last event of each item, `FILTER` for the facet counters, `SET LOCAL`);
its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.orm import Session

from app.models.marca_pm import MarcaPM
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.services.ml_publications.view.filters import (
    AXES,
    FULFILLMENT,
    NO_STORE,
    FilterError,
    PublicationFilter,
    T,
    build_base_select,
    link_state,
    listing_clauses,
    price_amount,
    status_value,
    stock_clauses,
)

STATEMENT_TIMEOUT = "8s"
SORT_ACTIVITY = "actividad"
# sort key -> (expression of the first ordering column, descending by default)
SORT_COLUMNS: dict[str, tuple[Any, bool]] = {
    SORT_ACTIVITY: (lambda: T.i.last_trigger_received_at, True),
    "precio": (price_amount, False),
    "titulo": (lambda: func.lower(T.i.title), False),
    "stock_full": (lambda: T.st.full_quantity, True),
    "actualizado": (lambda: T.i.ml_last_updated, True),
}
DIRECTIONS = ("asc", "desc")
FACET_AXES = AXES
FACET_MAX_BRANDS = 100
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


def parse_sort(orden: Optional[str], direction: Optional[str]) -> Sort:
    key = (orden or "").strip() or SORT_ACTIVITY
    if key not in SORT_COLUMNS:
        raise FilterError("orden", f"unknown value {key!r}; known: {', '.join(SORT_COLUMNS)}")
    wanted = (direction or "").strip().lower()
    if wanted and wanted not in DIRECTIONS:
        raise FilterError("dir", f"unknown value {wanted!r}; known: {', '.join(DIRECTIONS)}")
    return Sort(key, descending=(wanted == "desc") if wanted else SORT_COLUMNS[key][1])


def bound(db: Session) -> None:
    """Bound the rest of the request's transaction in time (released by the commit or rollback that ends it)."""
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))


def resolve_pm_pairs(db: Session, f: PublicationFilter) -> PublicationFilter:
    """Fill `pm_pairs` from the PMs' (marca, categoria) assignments, the same upper-cased rule as the sales query.

    Idempotent: a filter whose pairs are already resolved (or that has no `pms`) comes back as it is, with no
    query, so the router resolves once and `list_items` / `facets` may call it again safely."""
    if not f.pms or f.pm_pairs is not None:
        return f
    rows = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(f.pms)).all()
    pairs = {(marca.upper(), categoria.upper()) for marca, categoria in rows if marca and categoria}
    return replace(f, pm_pairs=tuple(sorted(pairs)))


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
    """The sort key (missing values last in either direction), then `item_id`, which makes the order total."""
    expression = SORT_COLUMNS[sort.key][0]()
    primary = expression.desc() if sort.descending else expression.asc()
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


def _grouped(
    db: Session, f: PublicationFilter, axis: str, key: Any, *, present: bool = False, limit: Optional[int] = None
) -> dict:
    """`key -> rows` over the base select without `axis`' own selection, biggest first. `present` drops NULL keys."""
    query = build_base_select(f, key, func.count().label("n"), skip=axis)
    if present:
        query = query.where(key.isnot(None))
    query = query.group_by(key).order_by(text("n DESC"), key)
    rows = db.execute(query.limit(limit) if limit else query)
    return {name: count for name, count in rows}


def _flags(db: Session, f: PublicationFilter, axis: str, clauses: dict) -> dict[str, int]:
    counts = [func.count().filter(clause).label(name) for name, clause in clauses.items()]
    return dict(db.execute(build_base_select(f, *counts, skip=axis)).one()._mapping)


def facets(db: Session, f: PublicationFilter) -> dict[str, dict[str, int]]:
    """Counts per value of each facet axis: one grouped COUNT per axis over the base select, each axis with its
    own selection left out (so choosing a value never makes its siblings read zero)."""
    f = resolve_pm_pairs(db, f)
    brand = func.upper(T.p.marca)
    by_status = _grouped(db, f, "status", status_value())
    by_store = _grouped(db, f, "stores", func.coalesce(cast(T.i.official_store_id, Text), NO_STORE))
    by_brand = _grouped(db, f, "marcas", brand, present=True, limit=FACET_MAX_BRANDS)
    return {
        "status": by_status,
        "stores": by_store,
        "marcas": by_brand,
        "listing": _flags(db, f, "listing", listing_clauses()),
        "link": _grouped(db, f, "link", link_state()),
        "stock": _flags(db, f, "stock", stock_clauses()),
    }
