"""Sell-out cap allocation (sell-in-sell-out T7): a pure function, no database.

A campaign has ONE cap shared by every product of all its groups (owner,
2026-10-19), in units (`tope_unidades`), money (`tope_monto`, in the campaign
currency), both, or none. `asignar` gives one campaign's sales their credit
until the cap runs out and returns exactly the `sell_out_consumos` rows to
store. It is a function of its inputs only: the allocator rebuilds a whole
campaign from scratch on every recompute, so a late sale dated earlier
displaces a later one, and a cancellation frees units for the next sale.

Ordering (deterministic, the same tuple sell in uses in `sell_in.fifo`):
`(fecha, unidades < 0, canal, venta_ref)`. A day's returns come after its
sales: dates carry no time, so a same-day return must find its sale done.

A sale takes the units the cap still has left, so the line that reaches the
cap is split: it keeps only what was left. With a money cap, the line that
reaches it takes the units needed to cover the money left (rounded up) and
its amount is capped at that money.

`ocupadas` are the line's units already taken by an exclusive (non
`acumulable`) campaign with precedence; only the rest is available here. On a
return they are the returned units given back to that campaign instead.

Returns mirror sell in (`sell_in.fifo`, owner's decision 2026-10-17): a return
(`unidades < 0`) frees its units, in order, from
1. its `objetivo`, the sale it reverses (resolved by the caller, like
   `sell_in.costing._objetivos`), up to what that sale still holds here;
2. then the most recent earlier sale OF THE SAME PRODUCT still holding units.
Freed units and money go to LATER sales, in order. A return finding nothing to
free frees nothing. A sale whose units all go back leaves no row.

Amount per unit, in the campaign currency (VAT: owner, 2026-10-20; sell out
applies against the net without VAT):
- `por_unidad`: `monto_unit`, divided by `1 + iva_pct / 100` of the line's own
  product when the campaign was loaded with VAT (`monto_incluye_iva`);
- `porcentaje`: `base_unit * porcentaje / 100`. The caller passes the base
  without VAT already (the cost, or the net sale price) converted to the
  campaign currency, so `monto_incluye_iva` does not apply to it.

Rounding: the unit amount is kept unrounded; each row's amount is
`units * unit amount` rounded ONCE to cents, half up (like Postgres NUMERIC).
The money cap is enforced on those rounded amounts, so the stored rows never
add up to more than `tope_monto`. When a return shrinks a row, its amount
becomes its remaining units' rounded worth. That is never more than it held: a
capped row holds at most `ceil(money / unit amount)` units, so all but one of
them are worth less than its money.

Inputs are checked, never repaired: anything inconsistent raises `ValueError`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple

CENT = Decimal("0.01")
CIEN = Decimal(100)

Clave = Tuple[str, int]  # (canal, venta_ref)


@dataclass(frozen=True)
class Campana:
    """What the allocation needs from a `SellOutCampana`."""

    tipo: str  # 'por_unidad' | 'porcentaje'
    moneda: str  # every amount here is in this currency
    monto_unit: Optional[Decimal] = None
    porcentaje: Optional[Decimal] = None
    monto_incluye_iva: bool = False
    tope_unidades: Optional[int] = None
    tope_monto: Optional[Decimal] = None


@dataclass(frozen=True)
class Linea:
    """A sale line (`unidades > 0`) or a return (`unidades < 0`) of a campaign product."""

    canal: str
    venta_ref: int
    item_id: int
    fecha: date
    unidades: int
    iva_pct: Decimal = Decimal(0)  # the product's own VAT rate, in percent
    base_unit: Optional[Decimal] = None  # `porcentaje` only: per unit, campaign currency, without VAT
    ocupadas: int = 0
    objetivo: Optional[Clave] = None  # a return's original sale, when the caller resolved one


@dataclass(frozen=True)
class Consumo:
    """One `sell_out_consumos` row (without `campana_id` and `tc_venta`, set by the writer)."""

    canal: str
    venta_ref: int
    item_id: int
    fecha_venta: date
    unidades: int
    monto: Decimal  # campaign currency, cents


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _unitario(campana: Campana, linea: Linea) -> Decimal:
    if campana.tipo == "porcentaje":
        if linea.base_unit is None:
            raise ValueError(f"sale {(linea.canal, linea.venta_ref)} has no percentage base")
        return linea.base_unit * campana.porcentaje / CIEN
    if campana.monto_incluye_iva:
        return campana.monto_unit / (1 + linea.iva_pct / CIEN)
    return campana.monto_unit


def _validar(campana: Campana, lineas: List[Linea]) -> None:
    if campana.tipo == "por_unidad":
        if campana.monto_unit is None or campana.monto_unit < 0:
            raise ValueError("a per-unit campaign needs a non-negative monto_unit")
    elif campana.tipo == "porcentaje":
        if campana.porcentaje is None or campana.porcentaje < 0:
            raise ValueError("a percentage campaign needs a non-negative porcentaje")
    else:
        raise ValueError(f"unknown campaign tipo {campana.tipo!r}")
    if campana.tope_unidades is not None and campana.tope_unidades <= 0:
        raise ValueError("tope_unidades must be positive")
    if campana.tope_monto is not None and campana.tope_monto <= 0:
        raise ValueError("tope_monto must be positive")
    vistas = set()
    for linea in lineas:
        clave = (linea.canal, linea.venta_ref)
        if clave in vistas:
            raise ValueError(f"sale {clave} appears more than once")
        vistas.add(clave)
        if not 0 <= linea.ocupadas <= abs(linea.unidades):
            raise ValueError(f"sale {clave} has ocupadas {linea.ocupadas} for {linea.unidades} units")
        if linea.iva_pct < 0:
            raise ValueError(f"sale {clave} has a negative iva_pct")
        if linea.base_unit is not None and linea.base_unit < 0:
            raise ValueError(f"sale {clave} has a negative base")


def asignar(campana: Campana, lineas: Iterable[Linea]) -> List[Consumo]:
    """The consumption rows of ONE campaign, in sale order."""
    lineas = sorted(lineas, key=lambda x: (x.fecha, x.unidades < 0, x.canal, x.venta_ref))
    _validar(campana, lineas)
    unidades_libres = campana.tope_unidades  # None: no unit cap
    monto_libre = None if campana.tope_monto is None else _cents(campana.tope_monto)  # None: no money cap
    # sale -> [units, amount, unit amount], in the order the sales were processed
    tenencia: Dict[Clave, List] = {}
    ventas: Dict[Clave, Linea] = {}
    for linea in lineas:
        clave = (linea.canal, linea.venta_ref)
        disponibles = abs(linea.unidades) - linea.ocupadas
        if disponibles == 0:
            continue
        if linea.unidades > 0:
            unitario = _unitario(campana, linea)
            toma = disponibles
            if unidades_libres is not None:
                toma = min(toma, unidades_libres)
            if monto_libre is not None and unitario > 0:
                toma = min(toma, math.ceil(monto_libre / unitario))
            if toma <= 0:
                continue
            monto = _cents(unitario * toma)
            if monto_libre is not None:
                monto = min(monto, monto_libre)
                monto_libre -= monto
            if unidades_libres is not None:
                unidades_libres -= toma
            tenencia[clave] = [toma, monto, unitario]
            ventas[clave] = linea
            continue
        # A return: its target first, then the latest earlier holder of the same product.
        mismo_producto = [c for c in reversed(tenencia) if ventas[c].item_id == linea.item_id]
        candidatas = [linea.objetivo] if linea.objetivo in mismo_producto else []
        candidatas += [c for c in mismo_producto if c != linea.objetivo]
        falta = disponibles
        for candidata in candidatas:
            if falta == 0:
                break
            unidades, monto, unitario = tenencia[candidata]
            suelta = min(falta, unidades)
            restante = unidades - suelta
            nuevo_monto = _cents(unitario * restante)  # <= monto: see the module docstring
            tenencia[candidata] = [restante, nuevo_monto, unitario]
            falta -= suelta
            if unidades_libres is not None:
                unidades_libres += suelta
            if monto_libre is not None:
                monto_libre += monto - nuevo_monto
    return [
        Consumo(
            canal=clave[0],
            venta_ref=clave[1],
            item_id=ventas[clave].item_id,
            fecha_venta=ventas[clave].fecha,
            unidades=unidades,
            monto=monto,
        )
        for clave, (unidades, monto, _) in tenencia.items()
        if unidades > 0
    ]
