"""Productos' row colors on Publicaciones ML's rows (S8): the linked product's color on the active team layer.

A color belongs to the product, per layer (`producto_color`, the `ml` slot; docs/color-teams-frontend-contract.md).
The layer is resolved like `GET /productos` resolves it (`resolver_layer_activo`: omitted = the global layer, another
team needs membership, else 403) and the colors are read with Productos' own `batch_colores`, from the application's
tables. It lives outside `app.services.ml_publications`, whose modules never import Productos' code (see
tests/services/ml_publications/test_resources.py). The row fields appear only when they have a value, so a list
nobody painted is unchanged:

- `color_marcado`: the product's color on the active layer.
- `color_hint_global`: its color on the global layer (the dot a team layer shows on a row it has not painted).
- `color_hint_equipo_inicial`: the active team's initial, on a team layer (the same on every row).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.api.endpoints.productos_shared import batch_colores, get_global_equipo_id, resolver_layer_activo
from app.models.equipo import Equipo
from app.models.usuario import Usuario


@dataclass(frozen=True)
class ColorLayer:
    active: int
    global_id: int
    initial: Optional[str]  # the active team's initial; None on the global layer


def resolve_layer(db: Session, user: Usuario, equipo_id: Optional[int]) -> ColorLayer:
    """The layer a read shows (403 for a team the user is not in, as in `GET /productos`)."""
    global_id = get_global_equipo_id(db)
    active = resolver_layer_activo(equipo_id, user, db, global_id)
    initial = None
    if active != global_id:
        team = db.query(Equipo).filter(Equipo.id == active).first()
        initial = team.nombre[0] if team is not None and team.nombre else None
    return ColorLayer(active=active, global_id=global_id, initial=initial)


def attach_colors(
    db: Session, layer: ColorLayer, rows: list[dict[str, Any]], product_of: Callable[[dict[str, Any]], Optional[int]]
) -> None:
    """Sets the color fields on each row in place; `product_of(row)` is the row's product id, None for none."""
    product_ids = sorted({pid for pid in map(product_of, rows) if pid is not None})
    active = batch_colores(db, product_ids, layer.active)
    global_ = active if layer.active == layer.global_id else batch_colores(db, product_ids, layer.global_id)
    for row in rows:
        pid = product_of(row)
        fields = {
            "color_marcado": active[pid].color_ml if pid in active else None,
            "color_hint_global": global_[pid].color_ml if pid in global_ else None,
            "color_hint_equipo_inicial": layer.initial,
        }
        row.update({name: value for name, value in fields.items() if value is not None})
