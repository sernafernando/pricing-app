"""Alejandro's criteria for AI writes: the C1 markup band (L13 Q4), read from #2333's per-MLA criteria.

There is ONE place the rules live: `ml_hay_mejores_criterios` (edited in the Promociones criteria panel), read
through `ml_hay_mejores_criterios_service.get_criterios`. This module only maps a write target to that band:

- promo apply/remove and mayorista target one MLA: its band when C1 is on, else no band.
- list price, cuota and bulk-markup changes target a product: the narrowest band across the product's ACTIVE
  publications with C1 on (the change reaches all of them), else no band. An empty intersection blocks every price.
- pause/activate carry no markup: no band.

Anything that cannot be read answers UNAVAILABLE, so the guard blocks the row (fail closed). Tests may replace
`band_for` with a double.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal, Union

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.envio_real_service import mlas_activas
from app.services.ml_hay_mejores_criterios_service import CriteriosView, get_criterios

logger = logging.getLogger(__name__)

UNAVAILABLE: Literal["unavailable"] = "unavailable"

Band = Union[tuple[float, float], None, Literal["unavailable"]]

# Source of the criteria a plan was checked against (stored with every audited row).
CRITERIA_VERSION: str | None = "ml_hay_mejores_criterios.c1"

_MLA_ACTIONS = frozenset({"promo_aplicar", "promo_quitar", "precio_mayorista"})
_PRODUCT_ACTIONS = frozenset({"precio_lista", "precio_cuota", "precio_markup_masivo"})


def _c1_band(view: CriteriosView) -> tuple[float, float] | None:
    if not view.c1_activo:
        return None
    lo = -math.inf if view.c1_markup_min is None else float(view.c1_markup_min)
    hi = math.inf if view.c1_markup_max is None else float(view.c1_markup_max)
    return (lo, hi)


def _product_id(accion: str, objetivo: str) -> int:
    # precio_cuota targets look like "<item_id>:<lista>:<cuota>".
    raw = objetivo.split(":", 1)[0] if accion == "precio_cuota" else objetivo
    return int(raw)


def _product_band(db: Session, item_id: int) -> tuple[float, float] | None:
    bands = [b for b in (_c1_band(get_criterios(db, mla)) for mla in mlas_activas(db, item_id)) if b is not None]
    if not bands:
        return None
    return (max(b[0] for b in bands), min(b[1] for b in bands))


def band_for(db: Session, target: dict[str, Any]) -> Band:
    """(min, max) markup band for `target` ({"accion", "objetivo"}), None when no band applies, or UNAVAILABLE."""
    accion, objetivo = str(target.get("accion")), str(target.get("objetivo"))
    try:
        if accion in _MLA_ACTIONS:
            return _c1_band(get_criterios(db, objetivo))
        if accion in _PRODUCT_ACTIONS:
            return _product_band(db, _product_id(accion, objetivo))
        if accion.startswith("estado_"):
            return None
    except (ValueError, SQLAlchemyError, RuntimeError):
        logger.warning("MCP write: C1 band unreadable for %s %s", accion, objetivo, exc_info=True)
        return UNAVAILABLE
    return UNAVAILABLE
