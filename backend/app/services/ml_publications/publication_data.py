"""A publication's title, description, pictures and attributes as the store last read them from ML.

The one place that turns the stored body (`ml_items.raw`) and description into that data: the product's copy
(Publicaciones ML T7) and a publication's original beside its override (T8) both read it here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.ml_publications import MlItem, MlItemDescription


def publication_data(db: Session, item: MlItem) -> dict[str, Any]:
    """`{titulo, descripcion, fotos: [{id, url}], atributos: [{id, name, value_name}]}` of `item`: the pictures with a
    URL (the secure one first), the attributes with a value, the description unless the store saw it gone."""
    raw = item.raw if isinstance(item.raw, dict) else {}
    description = db.get(MlItemDescription, item.item_id)
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
        "titulo": item.title or raw.get("title"),
        "descripcion": description_raw.get("plain_text") if isinstance(description_raw, dict) else None,
        "fotos": fotos,
        "atributos": atributos,
    }
