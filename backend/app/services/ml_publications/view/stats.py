"""Productos' stat cards (`GET /stats-dinamicos`) over the Publicaciones ML filters (S12d4).

Each card counts the linked products a click on it lists: the screen's filter plus the card's own filter, with the
very meaning those filters have (`filters._precio`, `erp_stock`, `_oferta`, `_pricing_flag`, `_markup_sign`), so a
count and the list it opens can never disagree (`test_stats_postgres.py` checks each card against its list).
Products are the Producto view's rows (`products.product_ids`): the item-level link's product, in the ERP catalog.

ONE statement, built to scale: the filtered rows collapse to one row per product first, and only then meet the
product's pricing, ERP row and offers, each once. The filters' own clauses are correlated `EXISTS` per publication;
asked eleven times over a whole unfiltered set they cost seconds (`test_view_volume_postgres.py`).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, false, func, select, true
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.ml_publications import MlItemProductLink
from app.models.oferta_ml import OfertaML
from app.models.producto import ProductoERP, ProductoPricing
from app.services.ml_publications.view.filters import (
    LINK_ITEM_LEVEL,
    LINK_LINKED,
    PublicationFilter,
    T,
    current_offer,
    build_base_select,
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


def compute(db: Session, f: PublicationFilter, *, markups: bool) -> dict[str, int]:
    """The count of every card over `f`; the markup cards only with `markups` (`ml_metricas.ver_ganancia`)."""
    f = resolve_pm_pairs(db, f)
    offered = _offered_mlas()
    members = (
        build_base_select(
            f,
            T.p.item_id.label("product"),  # NULL with no link or a product gone from the ERP: in no card
            # the ERP stock only counts through a link in state `linked` (`filters.erp_stock`)
            func.bool_or(T.l.match_status == LINK_LINKED).label("linked"),
            # mejor oferta of the publication itself: some matching publication of the product has one
            func.bool_or(offered.c.mla.isnot(None)).label("own_offer"),
        )
        .outerjoin(offered, offered.c.mla == T.i.item_id)
        .where(T.p.item_id.isnot(None))
        .group_by(T.p.item_id)
        .subquery("members")
    )
    p = aliased(ProductoERP, name="p_stats")
    pp = aliased(ProductoPricing, name="pp_stats")
    query = (
        select()
        .select_from(members)
        .join(p, p.item_id == members.c.product)
        .outerjoin(pp, pp.item_id == members.c.product)
    )
    if f.oferta_per_product:
        by_product = _offered_products(offered)
        query = query.outerjoin(by_product, by_product.c.product == members.c.product)
        has_offer: ColumnElement = by_product.c.product.isnot(None)
    else:
        has_offer = members.c.own_offer.is_(True)

    con_stock = and_(members.c.linked.is_(True), p.stock > 0)
    con_precio = pp.precio_lista_ml.isnot(None)
    sin_precio = ~con_precio  # no pricing row reads "sin", as `filters._precio`
    nuevos = p.fecha_sync >= func.now() - timedelta(days=7)
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
    return {card: int(getattr(row, card)) for card in cards}
