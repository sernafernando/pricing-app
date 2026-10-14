"""PVP prices published in `precios_ml` and the rule that shows them.

When a product has ANY PVP row in `precios_ml` (lists 12, 18-21), the screens
show the PVP prices from there -- the whole set: a list without a row shows no
price -- instead of the `productos_pricing` columns, and price their markups
from those figures. The Productos listing and the product detail both read the
rule here so they always show the same PVP.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.precio_ml import PrecioML
from app.services.pricing_columns import PVP_PRICELIST_TO_CAMPO

PVP_PRICELISTS: list[int] = list(PVP_PRICELIST_TO_CAMPO)


def fetch_pvp_precios_ml(db: Session, item_ids: Sequence[int]) -> dict[int, dict[int, Optional[float]]]:
    """`{item_id: {pricelist_id: precio}}` of the products that have PVP rows in `precios_ml`."""
    if not item_ids:
        return {}
    rows = (
        db.query(PrecioML.item_id, PrecioML.pricelist_id, PrecioML.precio)
        .filter(PrecioML.item_id.in_(list(item_ids)), PrecioML.pricelist_id.in_(PVP_PRICELISTS))
        .all()
    )
    found: dict[int, dict[int, Optional[float]]] = {}
    for item_id, pricelist_id, precio in rows:
        found.setdefault(item_id, {})[pricelist_id] = float(precio) if precio else None
    return found


def pvp_precios_mostrados(
    precios_pricing: Mapping[int, Any], precios_ml: Optional[Mapping[int, Optional[float]]]
) -> dict[int, Any]:
    """The PVP prices a screen shows, by pricelist: `precios_ml`'s whole set when
    the product has one, else its `productos_pricing` prices."""
    if precios_ml is None:
        return {pricelist_id: precios_pricing.get(pricelist_id) for pricelist_id in PVP_PRICELISTS}
    return {pricelist_id: precios_ml.get(pricelist_id) for pricelist_id in PVP_PRICELISTS}
