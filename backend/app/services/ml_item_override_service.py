"""A publication's data overridden locally (Publicaciones ML T8): read with its original, and saved.

The owner's rule: editing a publication never changes it on ML; it is kept as an override, and whoever reads it can
show both, the applicable one and the original (for instance to export the publication to another marketplace).
Pushing the override to ML is a separate action, only where ML allows it.

- The original is what the store last read from ML (`publication_data`); it changes when ML does.
- The override is field by field: a field left NULL follows ML. A blank description overrides with none.
- Pictures and attributes can only be kept (reordered, removed, the attribute's value changed) from the
  publication's own: the ones ML has now, or the ones the override already kept (ML may have dropped one since).
- Any live publication can be overridden, a catalog one too: only the push to ML is limited. A deleted one reads but
  cannot be edited.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ml_item_override import MlItemOverride
from app.models.ml_publications import MlItem
from app.services.ml_publications.publication_data import pick, publication_data

FIELDS = ("titulo", "descripcion", "fotos", "atributos")


class PublicacionNoEditable(Exception):
    """The publication was deleted (gone from ML, or deleted in its `sub_status`): it cannot be overridden."""


@dataclass(frozen=True)
class OverrideView:
    item_id: str
    original: dict[str, Any]
    override: Optional[dict[str, Any]]  # None: nothing overridden
    aplicado: dict[str, Any]
    editable: bool
    updated_at: Optional[datetime]


def _is_live(item: MlItem) -> bool:
    return item.gone_at is None and "deleted" not in (item.sub_status or [])


def _applicable(original: dict[str, Any], override: Optional[dict[str, Any]]) -> dict[str, Any]:
    if override is None:
        return dict(original)
    applied = {field: original[field] if override[field] is None else override[field] for field in FIELDS}
    applied["descripcion"] = applied["descripcion"] or None  # blank (the override's or ML's) is no description
    return applied


def read_override(db: Session, mla: str) -> Optional[OverrideView]:
    """The publication's original, override and applicable data; None when the store does not know the MLA."""
    item = db.get(MlItem, mla)
    if item is None:
        return None
    original = publication_data(db, item)
    row = db.get(MlItemOverride, mla)
    override = None if row is None else {field: getattr(row, field) for field in FIELDS}
    return OverrideView(
        item_id=mla,
        original=original,
        override=override,
        aplicado=_applicable(original, override),
        editable=_is_live(item),
        updated_at=None if row is None else row.updated_at,
    )


_NOT_OWN = "que no son de la publicación"


def save_override(
    db: Session,
    mla: str,
    titulo: Optional[str],
    descripcion: Optional[str],
    fotos: Optional[list[str]],
    atributos: Optional[list[tuple[str, str]]],
    usuario_id: int,
) -> Optional[OverrideView]:
    """Store the override (every field None drops it) and commit; None when the MLA is unknown. Nothing is sent to
    ML. Raises `PublicacionNoEditable` for a deleted publication and `DatosNoValidos` for a picture or attribute that is
    not the publication's, or repeated."""
    item = db.get(MlItem, mla)
    if item is None:
        return None
    if not _is_live(item):
        raise PublicacionNoEditable(f"La publicación {mla} está eliminada: no se puede editar.")
    original = publication_data(db, item)
    # Locked until the commit: two edits at once do not interleave their fields.
    row = db.get(MlItemOverride, mla, with_for_update=True)
    # The publication's own: what the override already kept (ML may have dropped it since), and what ML has now,
    # which wins for an entry in both (its current URL and name).
    own_fotos = ((row.fotos or []) if row else []) + original["fotos"]
    own_atributos = ((row.atributos or []) if row else []) + original["atributos"]
    if descripcion is not None and not descripcion.strip():
        descripcion = ""  # overrides with no description
    values = {
        "titulo": titulo,
        "descripcion": descripcion,
        "fotos": None if fotos is None else pick(own_fotos, fotos, "fotos", _NOT_OWN),
        "atributos": None
        if atributos is None
        else [
            {**kept, "value_name": value_name}
            for kept, (_, value_name) in zip(
                pick(own_atributos, [attribute_id for attribute_id, _ in atributos], "atributos", _NOT_OWN), atributos
            )
        ],
    }
    if all(value is None for value in values.values()):
        db.execute(delete(MlItemOverride).where(MlItemOverride.item_id == mla))
    else:
        stamp = {**values, "updated_by": usuario_id, "updated_at": func.now()}
        statement = pg_insert(MlItemOverride).values(item_id=mla, **stamp)
        db.execute(statement.on_conflict_do_update(index_elements=[MlItemOverride.item_id], set_=stamp))
    db.commit()
    return read_override(db, mla)
