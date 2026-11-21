"""An offset that is a percentage of the sale's cost cannot be computed when that cost is unknown.

Costo SI interface §7 (handoffs/sell-in-costo-si-interfaz.md): an unknown cost is NULL, never 0, and every figure
computed from it stays unknown. The ML metrics cron already records no `porcentaje_costo` consumption for such a sale;
the offset recalculation endpoints and scripts follow the same rule through `omitir`: skip the sale and log it, never
record a consumption of 0. Offsets that do not depend on the cost (fixed amount, per unit) are not affected.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PORCENTAJE_COSTO = "porcentaje_costo"


def omitir(offset: Any, costo: Optional[Any], tipo_venta: str, id_operacion: Any) -> bool:
    """True when `offset` is a percentage of the cost and the sale's `costo` is unknown (None): the caller records no
    consumption for it. The skip is logged with the sale."""
    if getattr(offset, "tipo_offset", None) != PORCENTAJE_COSTO or costo is not None:
        return False
    logger.warning(
        "offset %s (porcentaje_costo): sale %s %s has no known cost, no consumption recorded",
        getattr(offset, "id", None),
        tipo_venta,
        id_operacion,
    )
    return True
