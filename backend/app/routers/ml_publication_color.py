"""Per-publication ML color writes for Publicaciones ML (seleccion-por-publicacion S3).

A publication's color lives in `publicacion_color`, one row per team layer and MLA. It overrides its product's
`producto_color.color_ml` in that layer; without a row the publication shows its product's color. Writing here never
touches `producto_color`: Productos and every other screen keep reading the product color as they did.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.api.deps import require_algun_permiso
from app.api.endpoints.productos_colors import COLORES_VALIDOS, _puede_escribir_layer_lote
from app.api.endpoints.productos_shared import get_global_equipo_id, puede_escribir_layer
from app.core.constants import PERMISOS_PUBLICACIONES_ML
from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.models.equipo import PublicacionColor
from app.models.usuario import Usuario
from app.services.ml_publications import admin
from app.services.ml_publications.view import status_targets

router = APIRouter(prefix="/ml-publications", tags=["ML Publications Colors"])

# The column is VARCHAR(30): a longer id is a 422 here, never a 500 at commit.
ColorItemId = Annotated[str, StringConstraints(pattern=admin.ITEM_ID_PATTERN, max_length=30)]


class PublicationColorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a stray `producto_id` is refused, never read as a product paint

    # The bulk cap of Publicaciones ML (pause/activate's too): it also bounds the SSE event that lists them.
    item_ids: list[ColorItemId] = Field(min_length=1, max_length=status_targets.MAX_STATUS_ITEM_IDS)
    color: Optional[str]  # required; null unpaints (the publication falls back to its product's color)
    equipo_id: Optional[int] = None  # the team layer; none is the global layer

    @field_validator("color")
    @classmethod
    def _known_color(cls, color: Optional[str]) -> Optional[str]:
        if color not in COLORES_VALIDOS:
            raise ValueError(f"unknown color {color!r}")
        return color


class PublicationColorResponse(BaseModel):
    count: int
    color: Optional[str]


@router.put("/colors", response_model=PublicationColorResponse)
def put_publication_colors(
    body: PublicationColorRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_algun_permiso(PERMISOS_PUBLICACIONES_ML)),
) -> dict[str, Any]:
    """Paints `item_ids` with `color` in one team layer, or with `color: null` deletes their own rows there. Only
    those MLAs change: never the other publications of their product, never the product's color. The layer rule is
    Productos': a member of the team, or on the global layer `productos.marcar_color`, plus
    `productos.marcar_color_lote` for more than one MLA. Publishes `publicacion_color:changed`."""
    global_id = get_global_equipo_id(db)
    equipo_id = body.equipo_id if body.equipo_id is not None else global_id
    item_ids = list(dict.fromkeys(body.item_ids))
    if len(item_ids) > 1:
        _puede_escribir_layer_lote(db, current_user, equipo_id)
    else:
        puede_escribir_layer(db, current_user, equipo_id)

    mine = PublicacionColor.equipo_id == equipo_id
    if body.color is None:
        db.query(PublicacionColor).filter(mine, PublicacionColor.item_id.in_(item_ids)).delete(
            synchronize_session=False
        )
    else:
        # One upsert: two painters of the same new MLA never collide on the unique key.
        dialect = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
        rows = [
            {"equipo_id": equipo_id, "item_id": item_id, "color_ml": body.color, "updated_by": current_user.id}
            for item_id in item_ids
        ]
        db.execute(
            dialect.insert(PublicacionColor)
            .values(rows)
            .on_conflict_do_update(
                index_elements=["equipo_id", "item_id"],
                set_={"color_ml": body.color, "updated_by": current_user.id, "updated_at": func.now()},
            )
        )
    db.commit()

    sse_publish_bg(
        "publicacion_color:changed",
        {"equipo_id": equipo_id, "is_global": equipo_id == global_id, "item_ids": item_ids, "color": body.color},
    )
    return {"count": len(item_ids), "color": body.color}
