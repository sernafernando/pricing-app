"""FIFO sell-in allocation (sell-in-sell-out T5, option A): a pure function.

A sell in applies ONLY to the units of its purchase. A product's sales consume
those units in date order, oldest purchase first, and a sale only consumes a
purchase that counts from on or before its date (`fecha` is the purchase date
or the goods-receipt date, per `SellInCompra.cuenta_desde`). Once every unit is
used up the remaining sales get nothing: their cost goes back to normal.

The result is a function of the inputs only, so recomputing a product from
scratch is idempotent and a released sale's units go to the next sales in line.

Ordering (deterministic):
- purchase lines by (`fecha`, `compra_id`, `compra_item_id`);
- sales by (`fecha`, `canal`, `venta_ref`), a day's returns after its sales:
  dates carry no time, so a same-day return must find its sale already done.

Inputs are checked, never repaired: a sale key `(canal, venta_ref)` appears
once and a purchase line has units; anything else raises `ValueError`.

Money: a purchase line's discount (`descuento_ars`, unrounded) is spread over
its units by cumulative rounding: units [a, b) get
`cents(total * b / cantidad) - cents(total * a / cantidad)`, so the
consumptions of a fully used line add up to its rounded total exactly.

Returns (owner's decision, 2026-10-17): every return gives its units back to
the pool. A return (`unidades < 0`) takes them, in order, from:
1. its `objetivo`, the sale it reverses (resolved by the caller), up to what
   that sale still holds;
2. then the most recent sale processed before it that still holds units.
A sale gives back the units it took LAST first, each to its own purchase line.
Freed units go to LATER sales, FIFO. A return finding nothing to free frees
nothing.

Two passes: units first (events in order), then money per purchase line over
its final holders in sale order, so a fully used line still adds up exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Lote:
    """A purchase line's units: what a sell in can discount."""

    compra_item_id: int
    compra_id: int
    fecha: date  # the date the purchase counts from
    cantidad: int
    descuento_ars: Decimal  # the line's whole discount in ARS, unrounded


def orden_fifo(lote: Lote) -> Tuple[date, int, int]:
    """The order a product's lines are consumed in: the date the purchase counts from, then purchase, then line."""
    return (lote.fecha, lote.compra_id, lote.compra_item_id)


@dataclass(frozen=True)
class Venta:
    """A sale line (`unidades > 0`) or a return (`unidades < 0`). A return's
    `objetivo` is the `(canal, venta_ref)` of the sale it reverses, when the
    caller could resolve one."""

    canal: str
    venta_ref: int
    fecha: date
    unidades: int
    objetivo: Optional[Tuple[str, int]] = None


@dataclass(frozen=True)
class Consumo:
    compra_item_id: int
    canal: str
    venta_ref: int
    fecha_venta: date
    unidades: int
    descuento_ars: Decimal


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _tramo(lote: Lote, desde: int, hasta: int) -> Decimal:
    """The discount of units [desde, hasta) of `lote`."""
    total = lote.descuento_ars
    return _cents(total * hasta / lote.cantidad) - _cents(total * desde / lote.cantidad)


Clave = Tuple[str, int]


def _unidades(lotes: List[Lote], ventas: List[Venta]) -> Dict[Clave, List[List[int]]]:
    """Pass 1, units only: `{sale: [[lote index, units], ...]}` in the order taken."""
    libres = [lote.cantidad for lote in lotes]
    tenencia: Dict[Clave, List[List[int]]] = {}
    orden: List[Clave] = []  # the sales processed so far, in allocation order
    for venta in ventas:
        clave = (venta.canal, venta.venta_ref)
        if venta.unidades > 0:
            falta = venta.unidades
            tomado: List[List[int]] = []
            for i, lote in enumerate(lotes):
                if falta == 0 or lote.fecha > venta.fecha:
                    break
                toma = min(falta, libres[i])
                if toma > 0:
                    tomado.append([i, toma])
                    libres[i] -= toma
                    falta -= toma
            tenencia[clave] = tomado
            orden.append(clave)
        elif venta.unidades < 0:
            falta = -venta.unidades
            candidatas = ([venta.objetivo] if venta.objetivo in tenencia else []) + [
                c for c in reversed(orden) if c != venta.objetivo
            ]
            for candidata in candidatas:
                tomado = tenencia[candidata]
                # The units a sale took last go back first.
                while falta > 0 and tomado:
                    i, unidades = tomado[-1]
                    suelta = min(falta, unidades)
                    libres[i] += suelta
                    falta -= suelta
                    if suelta == unidades:
                        tomado.pop()
                    else:
                        tomado[-1][1] -= suelta
                if falta == 0:
                    break
    return tenencia


def _validar(lotes: List[Lote], ventas: List[Venta]) -> None:
    for lote in lotes:
        if lote.cantidad <= 0:
            raise ValueError(f"purchase line {lote.compra_item_id} has cantidad {lote.cantidad}")
    vistas = set()
    for venta in ventas:
        clave = (venta.canal, venta.venta_ref)
        if clave in vistas:
            raise ValueError(f"sale {clave} appears more than once")
        vistas.add(clave)


def asignar(lotes: Iterable[Lote], ventas: Iterable[Venta]) -> List[Consumo]:
    """The consumptions of ONE product: its active purchase lines against its sales and returns."""
    lotes = sorted(lotes, key=orden_fifo)
    ventas = sorted(ventas, key=lambda v: (v.fecha, v.unidades < 0, v.canal, v.venta_ref))
    _validar(lotes, ventas)
    if not lotes:
        return []
    fechas = {(v.canal, v.venta_ref): v.fecha for v in ventas}
    tenencia = _unidades(lotes, ventas)

    # Pass 2, money: each line's units are spread over its final holders in sale order.
    por_lote: Dict[int, Dict[Clave, int]] = {}
    for clave, tomado in tenencia.items():
        for i, unidades in tomado:
            por_lote.setdefault(i, {})
            por_lote[i][clave] = por_lote[i].get(clave, 0) + unidades
    consumos: List[Consumo] = []
    for i, holders in por_lote.items():
        lote = lotes[i]
        usadas = 0
        for clave in sorted(holders, key=lambda c: (fechas[c], c[0], c[1])):
            unidades = holders[clave]
            consumos.append(
                Consumo(
                    compra_item_id=lote.compra_item_id,
                    canal=clave[0],
                    venta_ref=clave[1],
                    fecha_venta=fechas[clave],
                    unidades=unidades,
                    descuento_ars=_tramo(lote, usadas, usadas + unidades),
                )
            )
            usadas += unidades
    return sorted(consumos, key=lambda c: (fechas[(c.canal, c.venta_ref)], c.canal, c.venta_ref, c.compra_item_id))
