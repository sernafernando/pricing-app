"""Productos' stat cards (`GET /stats-dinamicos`) over the Publicaciones ML filters (S12d4).

Each card counts the linked products a click on it lists: the screen's filter plus the card's own filter, with the
very meaning those filters have (`filters._precio`, `erp_stock`, `_oferta`, `_pricing_flag`, `_markup_sign`), so a
count and the list it opens can never disagree (`test_stats_postgres.py` checks each card against its list).
Products are the Producto view's rows (`products.product_ids`): the item-level link's product, in the ERP catalog.

ONE statement, built to scale: the filtered rows collapse to one row per product first (with its ERP stock and
sync date, read through the view's catalog alias `T.p`), and only then meet the product's pricing and offers, each
once. The filters' own clauses are correlated `EXISTS` per publication;
asked eleven times over a whole unfiltered set they cost seconds (`test_view_volume_postgres.py`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, false, func, select, true
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.ml_publications import MlItemProductLink
from app.models.oferta_ml import OfertaML
from app.services.ml_publications.view.filters import (
    LINK_ITEM_LEVEL,
    LINK_LINKED,
    PublicationFilter,
    T,
    build_base_select,
    current_offer,
    product_pricing,
    product_select,
    publication_filter_in,
)
from app.services.ml_publications.view.listing import resolve_pm_pairs

# The markup cards, Productos' stored markup of each pricing: shown only to who may see the margin.
MARKUP_COLUMNS = {
    "markup_negativo_clasica": "markup_calculado",
    "markup_negativo_rebate": "markup_rebate",
    "markup_negativo_oferta": "markup_oferta",
    "markup_negativo_web": "markup_web_real",
}


def _offered_mlas():
    """The MLAs with a current offer that has a seller price (`filters.current_offer`), once each."""
    o = aliased(OfertaML, name="o_stats")
    return select(o.mla).where(*current_offer(o)).group_by(o.mla).subquery("offered")


def _offered_products(offered):
    """The products with a current offer on any of their item-level linked publications (the Producto view's
    `oferta_por_producto`, `filters._oferta`)."""
    sibling = aliased(MlItemProductLink, name="l_stats")
    return (
        select(sibling.producto_item_id.label("product"))
        .join(offered, offered.c.mla == sibling.item_id)
        .where(sibling.variation_id == LINK_ITEM_LEVEL, sibling.producto_item_id.isnot(None))
        .group_by(sibling.producto_item_id)
        .subquery("offered_products")
    )


NEW_DAYS = 7  # Productos' "Nuevos": synced from the ERP in the last 7 days (`filters` `nuevos_ultimos_7_dias`)


def _is_new(fecha_sync: Any) -> ColumnElement:
    return fecha_sync >= func.now() - timedelta(days=NEW_DAYS)


def _linked_members(f: PublicationFilter, offered: Any) -> Any:
    """The filtered publications collapsed to one row per linked product, with its ERP stock and sync date."""
    return (
        build_base_select(
            f,
            T.p.item_id.label("product"),  # NULL with no link or a product gone from the ERP: in no card
            # the ERP stock only counts through a link in state `linked` (`filters.erp_stock`)
            func.bool_or(T.l.match_status == LINK_LINKED).label("linked"),
            # mejor oferta of the publication itself: some matching publication of the product has one
            func.bool_or(offered.c.mla.isnot(None)).label("own_offer"),
            # the product's own ERP figures, one value per product (its catalog row, `T.p`)
            func.max(T.p.stock).label("stock"),
            func.max(T.p.fecha_sync).label("fecha_sync"),
        )
        .outerjoin(offered, offered.c.mla == T.i.item_id)
        .where(T.p.item_id.isnot(None))
        .group_by(T.p.item_id)
        .subquery("members")
    )


def _sin_mla_members(f: PublicationFilter) -> Any:
    """With Sin MLA on (`con_mla=false`) the rows are the products no publication is linked to (`product_select`),
    shaped as `members`: there is no link to ask, so its stock is the product's (`filters.PRODUCT_STOCK`), and no
    publication of its own holds an offer."""
    return product_select(
        f,
        T.p.item_id.label("product"),
        true().label("linked"),
        false().label("own_offer"),
        T.p.stock.label("stock"),
        T.p.fecha_sync.label("fecha_sync"),
    ).subquery("members")


def _sin_mla_counts(db: Session, f: PublicationFilter) -> dict[str, int]:
    """Productos' "Sin MLA" card: the products no publication is linked to, under the product filters of `f`; empty
    when `f` asks something of the publications (`products.sin_mla_count` answers None then)."""
    if publication_filter_in(f) is not None:
        return {}
    rows = product_select(replace(f, sin_mla=True), T.p.stock.label("stock"), T.p.fecha_sync.label("fecha_sync"))
    rows = rows.subquery("sin_mla")
    cards: dict[str, ColumnElement] = {
        "sin_mla": true(),
        "sin_mla_con_stock": rows.c.stock > 0,
        "sin_mla_sin_stock": rows.c.stock <= 0,  # `filters.PRODUCT_STOCK["erp_sin_stock"]`
        "sin_mla_nuevos": _is_new(rows.c.fecha_sync),
    }
    row = db.execute(select(*(func.count().filter(where).label(card) for card, where in cards.items()))).one()
    return {card: int(getattr(row, card)) for card in cards}


def compute(db: Session, f: PublicationFilter, *, markups: bool, sin_mla: bool = False) -> dict[str, int]:
    """The count of every card over `f`; the markup cards only with `markups` (`ml_metricas.ver_ganancia`), the Sin
    MLA card only with `sin_mla` (the Producto view) and when no publication filter is on."""
    f = resolve_pm_pairs(db, f)
    offered = _offered_mlas()
    members = _sin_mla_members(f) if f.sin_mla else _linked_members(f, offered)
    pp = product_pricing("pp_stats")
    query = select().select_from(members).outerjoin(pp, pp.item_id == members.c.product)
    if f.oferta_per_product:
        by_product = _offered_products(offered)
        query = query.outerjoin(by_product, by_product.c.product == members.c.product)
        has_offer: ColumnElement = by_product.c.product.isnot(None)
    else:
        has_offer = members.c.own_offer.is_(True)

    con_stock = and_(members.c.linked.is_(True), members.c.stock > 0)
    con_precio = pp.precio_lista_ml.isnot(None)
    sin_precio = ~con_precio  # no pricing row reads "sin", as `filters._precio`
    nuevos = _is_new(members.c.fecha_sync)
    cards: dict[str, ColumnElement] = {
        "total": true(),
        "con_stock": con_stock,
        "con_precio": con_precio,
        "con_stock_sin_precio": and_(con_stock, sin_precio),
        "nuevos": nuevos,
        "nuevos_sin_precio": and_(nuevos, sin_precio),
        "oferta_sin_rebate": and_(has_offer, func.coalesce(pp.participa_rebate, false()).is_not(True)),
    }
    if markups:
        # Productos' rule: negative is < 0; NULL or no pricing row is not negative (`filters._markup_sign`)
        cards.update({card: getattr(pp, column) < 0 for card, column in MARKUP_COLUMNS.items()})
    columns = [func.count().filter(where).label(card) for card, where in cards.items()]
    row = db.execute(query.add_columns(*columns)).one()
    counts = {card: int(getattr(row, card)) for card in cards}
    return {**counts, **_sin_mla_counts(db, f)} if sin_mla else counts
