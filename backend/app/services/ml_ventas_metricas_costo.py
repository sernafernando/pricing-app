"""The sale cost of the legacy ML metrics (`ml_ventas_metricas`, /ventas-ml): costo SI in force on the sale date.

Costo SI is THE cost for everything (handoffs/sell-in-costo-si-feature.md S13, owner L6/L14). The metrics crons
(`agregar_metricas_ml_incremental` / `_diario` / `_local`) and the /ventas-ml live queries used to carry three copies
of a list-1 cost SQL; they now share this one, built on the costo SI reader (`costo_si.lote`): costo SI on the sale
date, list cost when the product has none (Q1), combos as the sum of their components (S11), in the product's cost
currency (L18) converted to pesos at the sale date's USD rate. TP-Link list 8 is not costo SI (D3) and keeps its own SQL.

An unknown cost (no cost of any kind, or a USD cost without a rate on the sale date) stays unknown: NULL, never 0
(handoffs/sell-in-costo-si-interfaz.md §7), and so do the figures computed from it (costo total, ganancia, markup,
cost-percentage offsets); each gap is logged with `sin_costo`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple, Union

from sqlalchemy.orm import Session

from app.services.costo_si import lote

logger = logging.getLogger(__name__)

# Joins the cost in force for the ML order line `tmlod` on its order date `tmloh.mlo_cd` as `cs`.
COSTO_SI_JOIN = f"LEFT JOIN LATERAL ({lote.sql_en_fecha('tmlod.item_id', 'tmloh.mlo_cd::date')}) cs ON true"

# 'USD' | 'ARS' (NULL when the product has no cost at all).
MONEDA_COSTO_SQL = "cs.costo_si_moneda"

# Unit cost without VAT in pesos; NULL when unknown (§7: never 0).
COSTO_SIN_IVA_SQL = "cs.costo_si_ars"

# The `ml_ventas_metricas` figures that need the cost: NULL with it.
CAMPOS_DEL_COSTO = ("costo_unitario_sin_iva", "costo_total_sin_iva", "ganancia", "markup_porcentaje")


def sin_costo(item_id: int, fecha: Union[date, datetime, None]) -> None:
    """Logs a sale whose cost is unknown (it is stored / shown without cost, never at 0)."""
    dia = fecha.date() if isinstance(fecha, datetime) else fecha
    logger.warning("costo SI: no cost for item %s on %s", item_id, dia)


def sin_cifras_del_costo(data: Dict[str, Any]) -> Dict[str, Any]:
    """`data` (a metrics row) with every cost-dependent figure unknown."""
    return {**data, **dict.fromkeys(CAMPOS_DEL_COSTO)}


def costo_actual(db: Session, item_id: int) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """The product's current cost in pesos and the USD rate used (None for an ARS cost), for the low-markup
    notification's "costo actual". (None, None) when the product has no cost."""
    costo = lote.actuales(db, [item_id]).get(item_id)
    if costo is None:
        return None, None
    return costo.costo_ars, costo.tipo_cambio
