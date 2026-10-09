"""The owner of an MLA's ads, defined ONCE (ml-billing-balance, design D7, owner answer Q3).

The Board and the ads read service both use `ads_owner_select`, so ads land on the same rows as sales:

1. the product (`M.item_id`) of the MLA's newest publication that has one -- the Board's `published` pairs;
2. else the product of the MLA's most recent sale (its frozen cost row; ties go to the higher product id);
3. else `NO_PRODUCT` ("sin producto").

`ml_item_product_links` is deliberately NOT used. Exactly one owner per MLA, so ads are counted once. The
mapping ignores PM scope, filters and the request window.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, union
from sqlalchemy.sql import Select

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as M
from app.services.ml_daily_metrics.sales import NO_PRODUCT, last_sales

__all__ = ["NO_PRODUCT", "ads_owner_select"]


def ads_owner_select(*, sqlite: bool, mlas: Optional[Select] = None) -> Select:
    """`(mla, owner_product)`. `mlas` is a one-column select: it narrows the answer and guarantees a row
    for each of its MLAs (`NO_PRODUCT` when nothing resolves). Without it, only MLAs that have a
    publication or a sale appear, so a caller outer-joins and treats a missing row as `NO_PRODUCT`."""
    newest = select(func.max(M.mlp_id)).where(M.mlp_publicationID.isnot(None), M.item_id.isnot(None))
    if mlas is not None:
        newest = newest.where(M.mlp_publicationID.in_(mlas))
    published = (
        select(M.mlp_publicationID.label("mla"), M.item_id.label("product"))
        .where(M.mlp_id.in_(newest.group_by(M.mlp_publicationID)))
        .subquery("ads_published")
    )

    last = last_sales(sqlite=sqlite).subquery("ads_last_sale")
    ranked = select(
        last.c.mla,
        last.c.product,
        func.row_number()
        .over(partition_by=last.c.mla, order_by=(last.c.last_at.desc(), last.c.product.desc()))
        .label("rn"),
    ).where(last.c.mla.notin_(select(published.c.mla)))  # only MLAs that reach the fallback
    if mlas is not None:
        ranked = ranked.where(last.c.mla.in_(mlas))
    sold = select(ranked.c.mla, ranked.c.product).where(ranked.c.rn == 1).subquery("ads_sold")

    universe = (mlas.distinct() if mlas is not None else union(select(published.c.mla), select(sold.c.mla))).subquery(
        "ads_mlas"
    )
    mla = universe.c[0]
    return (
        select(mla.label("mla"), func.coalesce(published.c.product, sold.c.product, NO_PRODUCT).label("owner_product"))
        .select_from(universe)
        .outerjoin(published, published.c.mla == mla)
        .outerjoin(sold, sold.c.mla == mla)
    )
