"""Our own product (Publicaciones ML T6, T7): the SKU and EAN of an ERP product, editable, computed on read, and its
data copied from a chosen publication.

- EAN: the manual one, else the ERP `codigo` (the ERP has no other barcode: the code IS the EAN).
- SKU: the manual one, else the one SKU every live publication linked to the product shares. When they disagree
  there is no SKU and the candidates are listed so the operator picks one (an assumption of T6, not a rule the
  owner set: guessing between two SKUs could write the wrong one to ML later).

A publication's SKU follows `links.sku_key` (the SELLER_SKU attribute, else `seller_custom_field`), read from the
variation the link names, or from the item for an item-level link. Deleted publications and gone variations do not
count.

The copied data (T7) is a copy, not a live link: the title, description, pictures and attributes of one live
publication of the product (a catalog one too: catalogs are a base, never edited), taken when it is chosen and
edited on the product afterwards. Choosing again replaces the copy; the manual SKU and EAN stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, exists, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ml_publications import MlItem, MlItemDescription, MlItemProductLink, MlItemVariation
from app.models.producto import ProductoERP
from app.models.producto_propio import ProductoPropio
from app.services.ml_publications.links import sku_key
from app.services.ml_publications.view.filters import LINK_ITEM_LEVEL


class FuenteNoValida(Exception):
    """The publication cannot be the product's source: it is not a live publication linked to the product."""


@dataclass(frozen=True)
class DatosCopiados:
    fuente_mla: str
    titulo: Optional[str]
    descripcion: Optional[str]
    fotos: list[dict[str, Any]]
    atributos: list[dict[str, Any]]
    copiado_at: Optional[datetime]


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
    datos: Optional[DatosCopiados]


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
        datos=_datos(manual),
    )


def _datos(manual: Optional[ProductoPropio]) -> Optional[DatosCopiados]:
    if manual is None or manual.fuente_mla is None:
        return None
    return DatosCopiados(
        fuente_mla=manual.fuente_mla,
        titulo=manual.titulo,
        descripcion=manual.descripcion,
        fotos=manual.fotos or [],
        atributos=manual.atributos or [],
        copiado_at=manual.fuente_copiada_at,
    )


def _manual_value(value: Optional[str]) -> Optional[str]:
    """What is stored for a typed value: trimmed, and None (back to the computed one) when blank."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _upsert(db: Session, item_id: int, values: dict[str, Any]) -> None:
    """Write `values` on the product's row, creating it: two first writes at once both land (the last wins) instead
    of one failing on the primary key."""
    db.execute(
        pg_insert(ProductoPropio)
        .values(item_id=item_id, **values)
        .on_conflict_do_update(index_elements=[ProductoPropio.item_id], set_={**values, "updated_at": func.now()})
    )


def save_producto_propio(
    db: Session, item_id: int, sku: Optional[str], ean: Optional[str], usuario_id: int
) -> Optional[ProductoPropioView]:
    """Store the manual SKU and EAN (blank or None drops each one) and commit; None when the product is unknown.

    The row stays when both are dropped: it may hold the copied data.
    """
    if db.get(ProductoERP, item_id) is None:
        return None
    _upsert(db, item_id, {"sku": _manual_value(sku), "ean": _manual_value(ean), "updated_by": usuario_id})
    db.commit()
    return read_producto_propio(db, item_id)


def _is_source_candidate(db: Session, item_id: int, mla: str) -> bool:
    """A live publication (not gone, not deleted at ML) linked to the product, at item level or by a variation."""
    linked = exists().where(MlItemProductLink.item_id == MlItem.item_id, MlItemProductLink.producto_item_id == item_id)
    return (
        db.execute(
            select(MlItem.item_id).where(
                MlItem.item_id == mla,
                linked,
                MlItem.gone_at.is_(None),
                MlItem.sub_status.any("deleted").isnot(true()),
            )
        ).first()
        is not None
    )


def _copy_of(db: Session, mla: str) -> dict[str, Any]:
    """The title, description, pictures and attributes of the publication as stored by the last read of ML."""
    item = db.get(MlItem, mla)
    raw = item.raw if isinstance(item.raw, dict) else {}
    description = db.get(MlItemDescription, mla)
    description_raw = description.raw if description is not None and description.gone_at is None else None
    fotos = []
    for picture in raw.get("pictures") or []:
        url = picture.get("secure_url") or picture.get("url")
        if url:
            fotos.append({"id": picture.get("id"), "url": url})
    atributos = [
        {"id": attribute.get("id"), "name": attribute.get("name"), "value_name": attribute["value_name"]}
        for attribute in raw.get("attributes") or []
        if attribute.get("value_name") is not None
    ]
    return {
        "fuente_mla": mla,
        "titulo": item.title or raw.get("title"),
        "descripcion": description_raw.get("plain_text") if isinstance(description_raw, dict) else None,
        "fotos": fotos,
        "atributos": atributos,
    }


def choose_source(db: Session, item_id: int, mla: str, usuario_id: int) -> Optional[ProductoPropioView]:
    """Copy the publication's data onto the product (replacing an earlier copy) and commit; None when the product is
    unknown. Raises `FuenteNoValida` when `mla` is not a live publication of the product."""
    if db.get(ProductoERP, item_id) is None:
        return None
    if not _is_source_candidate(db, item_id, mla):
        raise FuenteNoValida(f"La publicación {mla} no es una publicación vigente de este producto.")
    copy = _copy_of(db, mla)
    _upsert(db, item_id, {**copy, "fuente_copiada_por": usuario_id, "fuente_copiada_at": func.now()})
    db.commit()
    return read_producto_propio(db, item_id)
