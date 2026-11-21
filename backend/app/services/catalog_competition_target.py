"""Which MLA to refresh for catalog competition when hay_mejores flags an item.

Prefer the flagged MLA when it is a catalog listing; otherwise the catalog
sister linked to the same ERP product (stable pick: lowest item_id).
Returns None when neither applies — skip the expensive proxy call.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.models.ml_publications import MlItem, MlItemProductLink
from app.services.ml_publications.links import STATUS_LINKED


def mla_for_catalog_competition_refresh(db: Session, item_id: str) -> Optional[str]:
    if not item_id:
        return None
    item = db.query(MlItem.item_id, MlItem.catalog_listing).filter(MlItem.item_id == item_id).one_or_none()
    if item is None:
        return None
    if item.catalog_listing is True:
        return item.item_id

    link = (
        db.query(MlItemProductLink.producto_item_id)
        .filter(
            MlItemProductLink.item_id == item_id,
            MlItemProductLink.variation_id == 0,
            MlItemProductLink.match_status == STATUS_LINKED,
            MlItemProductLink.producto_item_id.isnot(None),
        )
        .one_or_none()
    )
    if link is None or link.producto_item_id is None:
        return None

    sibling_ids = [
        row.item_id
        for row in db.query(MlItemProductLink.item_id)
        .filter(
            MlItemProductLink.producto_item_id == link.producto_item_id,
            MlItemProductLink.variation_id == 0,
            MlItemProductLink.match_status == STATUS_LINKED,
        )
        .all()
    ]
    if not sibling_ids:
        return None

    catalog = (
        db.query(MlItem.item_id)
        .filter(MlItem.item_id.in_(sibling_ids), MlItem.catalog_listing.is_(True))
        .order_by(MlItem.item_id.asc())
        .first()
    )
    return catalog.item_id if catalog is not None else None


def mlas_for_catalog_competition_refresh(db: Session, item_ids: Iterable[str]) -> Set[str]:
    """`mla_for_catalog_competition_refresh` of many MLAs at once, without its Nones: three statements whatever the
    number of MLAs (the costo SI callback resolves every MLA priced with a product's cost, `costo_si.despues.pubml`).
    Same rule: a catalog listing is its own target; another MLA leads, through its item-level linked product, to the
    lowest catalog listing item-level linked to that product."""
    ids = sorted({i for i in item_ids if i})
    if not ids:
        return set()
    items = db.query(MlItem.item_id, MlItem.catalog_listing).filter(MlItem.item_id.in_(ids)).all()
    targets = {row.item_id for row in items if row.catalog_listing is True}
    others = [row.item_id for row in items if row.catalog_listing is not True]
    if not others:
        return targets
    products = {
        row.producto_item_id
        for row in db.query(MlItemProductLink.producto_item_id).filter(
            MlItemProductLink.item_id.in_(others),
            MlItemProductLink.variation_id == 0,
            MlItemProductLink.match_status == STATUS_LINKED,
            MlItemProductLink.producto_item_id.isnot(None),
        )
    }
    if not products:
        return targets
    sibling = aliased(MlItemProductLink)
    catalogs = (
        db.query(func.min(MlItem.item_id))
        .join(sibling, sibling.item_id == MlItem.item_id)
        .filter(
            sibling.producto_item_id.in_(products),
            sibling.variation_id == 0,
            sibling.match_status == STATUS_LINKED,
            MlItem.catalog_listing.is_(True),
        )
        .group_by(sibling.producto_item_id)
    )
    return targets | {row[0] for row in catalogs}
