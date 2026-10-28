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

from datetime import timedelta

from sqlalchemy import and_, false, func, select, true
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.oferta_ml import OfertaML
from app.services.ml_publications.view.filters import (
    LINK_LINKED,
    PublicationFilter,
    T,
    build_base_select,
    current_offer,
    product_has_offer,
    product_pricing,
)
from app.services.ml_publications.view.listing import resolve_pm_pairs
from app.services.ml_publications.view.products import product_pairs

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


def compute(db: Session, f: PublicationFilter, *, markups: bool) -> dict[str, int]:
    """The count of every card over `f`; the markup cards only with `markups` (`ml_metricas.ver_ganancia`)."""
    f = resolve_pm_pairs(db, f)
    offered = _offered_mlas()
    publications = build_base_select(
        f,
        T.i.item_id.label("mla"),
        # the ERP stock only counts through a link in state `linked` (`filters.erp_stock`)
        (T.l.match_status == LINK_LINKED).label("linked"),
    ).subquery("publications")
    # each publication once per linked product that passes `f`, as the Producto view groups them
    # (`products.product_pairs`; `T.p` the product's catalog row, NULL for a product gone from the ERP: in no card)
    pairs = product_pairs(
        f,
        publications,
        publications.c.mla,
        T.p.item_id.label("product"),
        publications.c.linked,
        T.p.stock,
        T.p.fecha_sync,
    ).subquery("pairs")
    members = (
        select(
            pairs.c.product,
            func.bool_or(pairs.c.linked).label("linked"),
            # mejor oferta of the publication itself: some matching publication of the product has one
            func.bool_or(offered.c.mla.isnot(None)).label("own_offer"),
            # the product's own ERP figures, one value per product
            func.max(pairs.c.stock).label("stock"),
            func.max(pairs.c.fecha_sync).label("fecha_sync"),
        )
        .outerjoin(offered, offered.c.mla == pairs.c.mla)
        .where(pairs.c.product.isnot(None))
        .group_by(pairs.c.product)
        .subquery("members")
    )
    pp = product_pricing("pp_stats")
    query = select().select_from(members).outerjoin(pp, pp.item_id == members.c.product)
    # mejor oferta of the product: one of the publications linked to it has one (`filters.product_has_offer`)
    has_offer = product_has_offer(members.c.product) if f.oferta_per_product else members.c.own_offer.is_(True)

    con_stock = and_(members.c.linked.is_(True), members.c.stock > 0)
    con_precio = pp.precio_lista_ml.isnot(None)
    sin_precio = ~con_precio  # no pricing row reads "sin", as `filters._precio`
    nuevos = members.c.fecha_sync >= func.now() - timedelta(days=7)
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
