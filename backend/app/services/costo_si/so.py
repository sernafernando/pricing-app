"""Sell out on top of costo SI, one rule for every area (D1, plan sell-in-costo-si-t3-paralelo.md Q6/Q7; interface
handoffs/sell-in-costo-si-interfaz.md §2).

D1 (owner L12): "el costo siso no existe, es costo SI y SO va en la venta, como ganancia adicional, si de ganancia tenés
1000 y le agregás 10% tenés 1100 de ganancia". The cost is costo SI only; a sell out is added to the profit and never
comes off the cost. Markups keep each area's existing net base `limpio` (Q6):

    ganancia c/ SO = limpio + SO - costo SI
    markup c/ SO   = (limpio + SO - costo SI) / costo SI     (a ratio, like `pricing_calculator.calcular_markup`)

A sell out of base 'costo' is a % of costo SI (Q7, L4.7: one cost everywhere). Numbers of one type in (all float or all
Decimal), that type out; an unknown input is an unknown result, never 0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional, TypeVar

N = TypeVar("N", float, Decimal)


def base_sell_out(costo_si: Optional[Decimal], precio_neto: Optional[Decimal]) -> Dict[str, Optional[Decimal]]:
    """The base each `sell_out_campanas.base_porcentaje` applies to: 'costo' = costo SI (same currency the caller
    computes the sell out in), 'precio_neto' = the net price."""
    return {"costo": costo_si, "precio_neto": precio_neto}


def ganancia_con_so(limpio: Optional[N], sell_out: Optional[N], costo_si: Optional[N]) -> Optional[N]:
    if limpio is None or sell_out is None or costo_si is None:
        return None
    return limpio + sell_out - costo_si


def markup_con_so(limpio: Optional[N], sell_out: Optional[N], costo_si: Optional[N]) -> Optional[N]:
    ganancia = ganancia_con_so(limpio, sell_out, costo_si)
    if ganancia is None or not costo_si:
        return None
    return ganancia / costo_si
