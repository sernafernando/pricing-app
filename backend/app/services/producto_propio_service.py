"""Our own product (Publicaciones ML T6): the SKU and EAN of an ERP product, editable, computed on read.

- EAN: the manual one, else the ERP `codigo` (the ERP has no other barcode: the code IS the EAN).
- SKU: the manual one, else the one SKU every live publication linked to the product shares. When they disagree
  there is no SKU and the candidates are listed so the operator picks one (an assumption of T6, not a rule the
  owner set: guessing between two SKUs could write the wrong one to ML later).

A publication's SKU follows `links.sku_key` (the SELLER_SKU attribute, else `seller_custom_field`), read from the
variation the link names, or from the item for an item-level link. Deleted publications and gone variations do not
count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, or_, select, true
from sqlalchemy.orm import Session

from app.models.ml_publications import MlItem, MlItemProductLink, MlItemVariation
from app.models.producto import ProductoERP
from app.models.producto_propio import ProductoPropio
from app.services.ml_publications.links import sku_key
from app.services.ml_publications.view.filters import LINK_ITEM_LEVEL


@dataclass(frozen=True)
class ProductoPropioView:
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    ean: Optional[str]
    ean_manual: bool
    sku: Optional[str]
    sku_manual: bool
    sku_candidatos: list[str]


def linked_skus(db: Session, item_id: int) -> list[str]:
    """The distinct SKUs of the live publications linked to the product, sorted."""
    rows = db.execute(
        select(
            MlItemProductLink.variation_id,
            MlItem.seller_sku,
            MlItem.seller_custom_field,
            MlItemVariation.seller_sku,
            MlItemVariation.seller_custom_field,
        )
        .join(MlItem, MlItem.item_id == MlItemProductLink.item_id)
        .outerjoin(
            MlItemVariation,
            and_(
                MlItemVariation.item_id == MlItemProductLink.item_id,
                MlItemVariation.variation_id == MlItemProductLink.variation_id,
            ),
        )
        .where(
            MlItemProductLink.producto_item_id == item_id,
            MlItem.gone_at.is_(None),
            # IS NOT TRUE: a NULL sub_status (most items) is not deleted
            MlItem.sub_status.any("deleted").isnot(true()),
            or_(MlItemProductLink.variation_id == LINK_ITEM_LEVEL, MlItemVariation.gone_at.is_(None)),
        )
    ).all()
    skus = set()
    for variation_id, item_sku, item_custom, variation_sku, variation_custom in rows:
        if variation_id == LINK_ITEM_LEVEL:
            key, _ = sku_key(item_sku, item_custom)
        else:
            key, _ = sku_key(variation_sku, variation_custom)
        if key is not None:
            skus.add(key)
    return sorted(skus)


def read_producto_propio(db: Session, item_id: int) -> Optional[ProductoPropioView]:
    """The product's SKU and EAN as the panel shows them; None when the ERP has no such product."""
    producto = db.get(ProductoERP, item_id)
    if producto is None:
        return None
    manual = db.get(ProductoPropio, item_id)
    manual_sku = manual.sku if manual is not None else None
    manual_ean = manual.ean if manual is not None else None
    candidatos = linked_skus(db, item_id)
    computed_sku = candidatos[0] if len(candidatos) == 1 else None
    return ProductoPropioView(
        item_id=item_id,
        codigo=producto.codigo,
        descripcion=producto.descripcion,
        ean=manual_ean if manual_ean is not None else producto.codigo,
        ean_manual=manual_ean is not None,
        sku=manual_sku if manual_sku is not None else computed_sku,
        sku_manual=manual_sku is not None,
        sku_candidatos=candidatos,
    )


def _manual_value(value: Optional[str]) -> Optional[str]:
    """What is stored for a typed value: trimmed, and None (back to the computed one) when blank."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def save_producto_propio(
    db: Session, item_id: int, sku: Optional[str], ean: Optional[str], usuario_id: int
) -> Optional[ProductoPropioView]:
    """Store the manual SKU and EAN (blank or None drops each one) and commit; None when the product is unknown.

    With neither left, the row is deleted: the product is back to its computed values.
    """
    if db.get(ProductoERP, item_id) is None:
        return None
    sku, ean = _manual_value(sku), _manual_value(ean)
    row = db.get(ProductoPropio, item_id)
    if sku is None and ean is None:
        if row is not None:
            db.delete(row)
    else:
        if row is None:
            row = ProductoPropio(item_id=item_id)
            db.add(row)
        row.sku, row.ean, row.updated_by = sku, ean, usuario_id
    db.commit()
    return read_producto_propio(db, item_id)
