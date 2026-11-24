"""Sell out of a product today, as the Productos screens show it (sell-in-sell-out T9; costo SI T5 PR B).

Display-only and additive: the existing cost and markup fields stay as they are; see
`app.services.productos_sell_in_out`. There is no sell in part: costo SI replaced the FIFO lots and the per-sale cost
bonuses, so a product's sell in is already inside its costo SI and the screens show only the sell out ("c/ SO").
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


class SellOutProducto(BaseModel):
    """The campaigns that would credit the next unit sold today."""

    monto_unit: Optional[float]  # ARS per unit, without VAT; None when a rate or base is missing
    campana_ids: List[int]


class SellInOutProducto(BaseModel):
    """Null as a whole when no sell out applies. Markups use the keys of `PppPayload.markups`:
    `markups_sell_in_out` only when sell out applies (the plain cost plus the credit added to the net);
    `markups_sell_in` is never filled (D1: no markup "with sell in"), kept for the callers that read it."""

    sell_out: Optional[SellOutProducto] = None
    markups_sell_in: Dict[str, float] = {}
    markups_sell_in_out: Dict[str, float] = {}


class SellInOutTienda(BaseModel):
    """The Tienda listing's sell out (`app.services.tienda_sell_in_out`): it depends on the channel each price sells
    through, so it is one per markup key (`gremio`, `sugerido`: off-ML; `web_transf`: Tienda Nube), each with its own
    price as the percentage base. Null as a whole when none applies."""

    sell_out: Dict[str, SellOutProducto] = {}
    markups_sell_in: Dict[str, float] = {}
    markups_sell_in_out: Dict[str, float] = {}
