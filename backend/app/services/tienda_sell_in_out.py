"""Sell in and sell out on the Tienda listing (`GET /productos/tienda`), display only.

Owner (2026-11-12): "en tienda tienen que aplicar los sell in y sell out igual que en el resto de las cosas, tienen
que figurarle los costos más bajos y el plus de ganancia, acordate que tienda no usa las mismas fórmulas porque no
es sobre ml."

The sources are the Productos ones (`app.services.productos_sell_in_out`: the same FIFO lots, cost bonuses and
campaigns, the cost converted at the same rate). Only the net they are measured against is Tienda's own, never the
ML one (no ML commission or shipping):

- `gremio`, `sugerido`: `precio_sin_iva / (1 + varios%)`, the net their markups are built on.
- `web_transf`: `pricing_calculator.limpio_web_transferencia`, the net its price is solved for.

Markups (`SellInOutMarkups.record`): with sell in, `limpio / costo c/ sell in - 1`; with sell out,
`(limpio + sell out) / (costo c/ sell in, or the plain cost) - 1`.

Store scope applies to sell OUT only (sell in ignores stores): each key reads the campaigns of the channel its price
sells through, `gremio` and `sugerido` the off-ML one (`fuera`), `web_transf` Tienda Nube (`tn`). A campaign with
the default reach (every channel) applies to every key; one narrowed to ML stores applies to none. A percentage of
price campaign takes each key's OWN price with VAT as its base, never a shared one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Mapping, Optional

from sqlalchemy.orm import Session

from app.schemas.sell_in_out_producto import SellInOutTienda, SellOutProducto
from app.services.productos_sell_in_out import ContextoMarkup, SellInOutBatch, resolver_sell_in_out_por_contexto

CLAVE_GREMIO = "gremio"
CLAVE_SUGERIDO = "sugerido"
CLAVE_WEB_TRANSF = "web_transf"

_FUERA = "fuera"
_TN = "tn"
CONTEXTOS_TIENDA: Dict[str, List[ContextoMarkup]] = {_FUERA: [(_FUERA, None)], _TN: [(_TN, None)]}
CONTEXTO_DE_CLAVE: Dict[str, str] = {CLAVE_GREMIO: _FUERA, CLAVE_SUGERIDO: _FUERA, CLAVE_WEB_TRANSF: _TN}


@dataclass(frozen=True)
class PrecioTienda:
    """One Tienda price: `con_iva` is its percentage of price sell out base; `limpio` its net, ARS without VAT."""

    con_iva: float
    limpio: float


def limpio_lista(precio_sin_iva: float, varios_porcentaje: float) -> float:
    """The net of a Gremio / Sugerido price: the inverse of `costo * (1 + varios%) * (1 + markup%)`."""
    return precio_sin_iva / (1 + varios_porcentaje / 100)


def resolver_tienda_batches(db: Session, item_ids: Iterable[int], hoy: date) -> Dict[str, SellInOutBatch]:
    """One batch per channel context, from ONE database read for the whole page."""
    return resolver_sell_in_out_por_contexto(db, item_ids, hoy, CONTEXTOS_TIENDA)


@dataclass(frozen=True)
class _ProductoConIva:
    """The product as `SellInOutBatch.markups` reads it, with the VAT rate Tienda's prices were built with."""

    item_id: int
    costo: Optional[float]
    moneda_costo: Optional[str]
    iva: float


def sell_in_out_tienda(
    batches: Mapping[str, SellInOutBatch],
    producto,
    precios: Mapping[str, Optional[PrecioTienda]],
    *,
    tipo_cambio: Optional[float],
    iva: float,
) -> Optional[SellInOutTienda]:
    """`producto` is a `ProductoERP`; `tipo_cambio` the USD rate its list cost converts at. `precios` maps each key
    to its price, None when the row has none (no markup, no sell out for that key). `iva` is the VAT rate Tienda's
    price formula used (the product's, or its default when the product has none): the percentage of price base
    and the VAT-loaded amounts read that SAME rate, never the product's raw empty one."""
    producto = _ProductoConIva(producto.item_id, producto.costo, producto.moneda_costo, iva)
    base = batches[_FUERA].markups(producto, tipo_cambio=tipo_cambio).payload()
    sell_in = base.sell_in if base else None
    sell_out: Dict[str, SellOutProducto] = {}
    markups_sell_in: Dict[str, float] = {}
    markups_sell_in_out: Dict[str, float] = {}
    for clave, precio in precios.items():
        if precio is None:
            continue
        acc = batches[CONTEXTO_DE_CLAVE[clave]].markups(
            producto, precio_lista_ml=precio.con_iva, tipo_cambio=tipo_cambio
        )
        acc.record(clave, precio.limpio)
        payload = acc.payload()
        if payload is None:
            continue
        if payload.sell_out is not None:
            sell_out[clave] = payload.sell_out
        markups_sell_in.update(payload.markups_sell_in)
        markups_sell_in_out.update(payload.markups_sell_in_out)
    if sell_in is None and not sell_out:
        return None
    return SellInOutTienda(
        sell_in=sell_in,
        sell_out=sell_out,
        markups_sell_in=markups_sell_in,
        markups_sell_in_out=markups_sell_in_out,
    )
