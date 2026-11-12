"""Sell in and sell out of a product today, as the Productos screens show them (sell-in-sell-out T9).

Owner rule: "Always show both: cost and cost with sell in; markup and totals
without and with sell out." Display-only and additive: the existing cost and
markup fields stay as they are; see `app.services.productos_sell_in_out`.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


class SellInProducto(BaseModel):
    """Where the next sale takes its sell in from: the purchase line (option A, FIFO), or, with no lot left, the
    active % of cost bonuses (T25; rule 5, a FIFO lot's units go first)."""

    compra_item_id: Optional[int] = None  # the FIFO lot; None for a cost bonus
    bono_id: Optional[int] = None  # the first cost bonus (id order) of the stack; None for a FIFO lot
    bono_ids: List[int] = []  # every cost bonus giving part of `descuento_unit`, in id order; empty for a FIFO lot
    descuento_unit: float  # ARS per unit
    costo: Optional[float]  # ARS per unit with sell in; None when the cost has no ARS value (no rate)
    unidades_restantes: Optional[int] = None  # the lot's units left; None for a cost bonus (no stock)
    # S10: the same two figures in the product's cost currency, converted back at the very rate the cost was turned
    # into ARS with (never another one), for display only; equal to the ARS ones for an ARS cost, None without it.
    moneda_costo: str = "ARS"
    costo_moneda: Optional[float] = None
    descuento_unit_moneda: Optional[float] = None


class SellOutProducto(BaseModel):
    """The campaigns that would credit the next unit sold today."""

    monto_unit: Optional[float]  # ARS per unit, without VAT; None when a rate or base is missing
    campana_ids: List[int]


class SellInOutProducto(BaseModel):
    """Null as a whole when neither applies. Markups use the keys of `PppPayload.markups`:
    `markups_sell_in` only when sell in applies (cost with sell in), `markups_sell_in_out` only
    when sell out applies (that cost, or the plain one, plus the credit added to the net)."""

    sell_in: Optional[SellInProducto] = None
    sell_out: Optional[SellOutProducto] = None
    markups_sell_in: Dict[str, float] = {}
    markups_sell_in_out: Dict[str, float] = {}


class SellInOutTienda(BaseModel):
    """The Tienda listing's sell in / sell out (`app.services.tienda_sell_in_out`). Sell in ignores stores, so it is
    one figure; sell out depends on the channel each price sells through, so it is one per markup key (`gremio`,
    `sugerido`: off-ML; `web_transf`: Tienda Nube), each with its own price as the percentage base. Null as a whole
    when neither applies."""

    sell_in: Optional[SellInProducto] = None
    sell_out: Dict[str, SellOutProducto] = {}
    markups_sell_in: Dict[str, float] = {}
    markups_sell_in_out: Dict[str, float] = {}
