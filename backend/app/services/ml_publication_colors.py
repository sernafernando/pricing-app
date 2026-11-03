"""Productos' row colors on Publicaciones ML's rows (S8): the linked product's color on the active team layer.

A product's color lives per layer (`producto_color`, the `ml` slot; docs/color-teams-frontend-contract.md).
The layer is resolved like `GET /productos` resolves it (`resolver_layer_activo`: omitted = the global layer, another
team needs membership, else 403) and the colors are read with Productos' own `batch_colores`, from the application's
tables. It lives outside `app.services.ml_publications`, whose modules never import Productos' code (see
tests/services/ml_publications/test_resources.py). The row fields appear only when they have a value, so a list
nobody painted is unchanged:

- `color_marcado`: the row's color on the active layer.
- `color_hint_global`: its color on the global layer, on a team layer only (the dot it shows on a row it has not
  painted). On the global layer it would repeat `color_marcado` and outlive an unpaint.
- `color_hint_equipo_inicial`: the active team's initial, on a team layer (the same on every row).

A publication may also be painted on its own (`publicacion_color`, seleccion-por-publicacion S3): on each layer its
own color wins over its product's, so a publication row shows its EFFECTIVE color -- its own, otherwise its
product's -- and the color filter keeps it by that same color, the tree's filter too. Product rows (the Producto
view's, filtered by the product's color only: `color_per_product`) and tree nodes show the product's color.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.api.endpoints.productos_shared import batch_colores, get_global_equipo_id, resolver_layer_activo
from app.models.equipo import Equipo, ProductoColor, PublicacionColor
from app.models.usuario import Usuario
from app.services.ml_publications.view.filters import PublicationFilter


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


def _own_colors(db: Session, item_ids: list[str], equipo_ids: list[int]) -> dict[tuple[int, str], str]:
    """The publications' own colors, `(equipo_id, MLA) -> color`, on `equipo_ids`: one statement."""
    if not item_ids:
        return {}
    rows = db.query(PublicacionColor.equipo_id, PublicacionColor.item_id, PublicacionColor.color_ml).filter(
        PublicacionColor.equipo_id.in_(equipo_ids), PublicacionColor.item_id.in_(item_ids)
    )
    return {(equipo_id, item_id): color for equipo_id, item_id, color in rows}


def attach_colors(
    db: Session,
    layer: ColorLayer,
    rows: list[dict[str, Any]],
    product_of: Callable[[dict[str, Any]], Optional[int]],
    item_of: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
) -> None:
    """Sets the color fields on each row in place; `product_of(row)` is the row's product id, None for none.
    `item_of(row)`, a publication row's MLA: its own color, when it has one on a layer, wins on that layer."""
    product_ids = sorted({pid for pid in map(product_of, rows) if pid is not None})
    active = batch_colores(db, product_ids, layer.active)
    on_team = layer.active != layer.global_id
    global_ = batch_colores(db, product_ids, layer.global_id) if on_team else {}
    item_ids = sorted({mla for mla in map(item_of, rows) if mla}) if item_of is not None else []
    own = _own_colors(db, item_ids, [layer.active, layer.global_id] if on_team else [layer.active])
    for row in rows:
        pid = product_of(row)
        mla = item_of(row) if item_of is not None else None
        fields = {
            "color_marcado": own.get((layer.active, mla)) or (active[pid].color_ml if pid in active else None),
            "color_hint_global": (
                own.get((layer.global_id, mla)) or (global_[pid].color_ml if pid in global_ else None)
            )
            if on_team
            else None,
            "color_hint_equipo_inicial": layer.initial,
        }
        row.update({name: value for name, value in fields.items() if value is not None})


def resolve_color_filter(db: Session, layer: ColorLayer, f: PublicationFilter) -> PublicationFilter:
    """Fill the products the color filter (`colores`) keeps, on `layer`, read like Productos reads them (the `ml` slot
    of `producto_color`), and the publications painted on their own there (`publicacion_color`): one statement each
    for every painted product and publication of the layer. A filter with no `colores` comes back as it is, with no
    query."""
    if not (f.colors or f.no_color):
        return f
    painted = db.query(ProductoColor.item_id, ProductoColor.color_ml).filter(
        ProductoColor.equipo_id == layer.active, ProductoColor.color_ml.isnot(None)
    )
    by_color = [(int(item_id), color) for item_id, color in painted]
    own = (
        []  # the Producto view's rows: the product's color only
        if f.color_per_product
        # `publicacion_color.color_ml` is NOT NULL (an unpaint deletes the row): every row is an own color.
        else list(
            db.query(PublicacionColor.item_id, PublicacionColor.color_ml).filter(
                PublicacionColor.equipo_id == layer.active
            )
        )
    )
    return replace(
        f,
        color_ids=tuple(sorted(item_id for item_id, color in by_color if color in f.colors)),
        colored_ids=tuple(sorted(item_id for item_id, _ in by_color)),
        item_color_ids=tuple(sorted(mla for mla, color in own if color in f.colors)),
        item_colored_ids=tuple(sorted(mla for mla, _ in own)),
    )
