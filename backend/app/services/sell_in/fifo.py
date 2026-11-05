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

Two passes: units first (events in order), then money over the final
holdings in sale order (within a sale, lot by lot in FIFO order), so a fully
used line still adds up exactly.

Cost modes (owner, 2026-11-02; handoffs `sell-in-costos-propuesta.md`): dated
`Periodo`s change only the MONEY pass. Units still come out of the lots in
FIFO order, so every lot keeps its consumed and left units. The period whose
`desde` is the latest on or before a sale's date governs it (same `desde`: the
later in the list); before the first one, FIFO.
- `fifo`: each lot's units at the lot's own value, by cumulative rounding.
- `ponderado` ("si compro 100 unidades a 10 y 100 a 8, ponderar eso en 200 a
  9"): the units left in every lot that already counts form one pool at one
  weighted value, by cumulative rounding over the pool. A lot that starts
  counting later joins it: what the pool still holds plus that lot, over the
  units left. The pool hands out exactly what it holds.
- `ultimo` ("que el costo sea el del último también combinando las
  cantidades"): every unit at the unit value of the newest lot that counts;
  this does NOT hand out what the lots hold (owner accepted, 2026-11-02).
A period takes over at its `desde` from what the previous one left, with or
without sales in between (D2): `fifo` puts each lot back at its own money left
(after FIFO it changes nothing), `ponderado` weighs the money the previous
period left (a pool continues, a last price's value is re-weighed), `ultimo`
re-anchors. A sale before a period's `desde` keeps exactly what it had.
- `manual` (D6: "setear cantidad y costo a mano, por si un sell in quedó
  defazado al stock actual"): its block (`lote_manual`) is a lot of the typed
  quantity at the typed value per unit (the product's cost frozen at save
  minus the typed cost, signed: a typed cost above the frozen one raises the
  sale's cost, owner 2026-11-02). From its `desde` it REPLACES the units left
  of every lot before it in FIFO order (those counting by then, an earlier
  block included): the UNITS pass zeroes them, and a return never brings them
  back. Lots counting later queue behind it, FIFO; the money pass runs FIFO
  over what is left, and a later row takes the block's units left in like any
  lot's. A block and its period go together: the block's `compra_item_id` is
  `-modo_id`, so its consumptions are filed under the mode row, not a line.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, timedelta
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
    modo_id: Optional[int] = None  # set on a manual block (`lote_manual`): its mode row


def lote_manual(modo_id: int, desde: date, cantidad: int, descuento_ars: Decimal) -> Lote:
    """A manual row's block: `cantidad` units handing out `descuento_ars` (signed) from `desde`, filed under
    `-modo_id` so no purchase line id can collide with it."""
    return Lote(
        compra_item_id=-modo_id,
        compra_id=modo_id,
        fecha=desde,
        cantidad=cantidad,
        descuento_ars=descuento_ars,
        modo_id=modo_id,
    )


def orden_fifo(lote: Lote) -> Tuple[date, bool, int, int]:
    """The order a product's lines are consumed in: the date the purchase counts from, then purchase, then line. A
    manual block goes after every line counting on its own date (it replaces them), and a later block after it."""
    return (lote.fecha, lote.modo_id is not None, lote.compra_id, lote.compra_item_id)


@dataclass(frozen=True)
class Periodo:
    """A product's cost mode from `desde` on (`fifo`, `ponderado`, `ultimo`, `manual`); see the module docstring."""

    desde: date
    modo: str
    modo_id: Optional[int] = None  # a `manual` period: the mode row its block (`lote_manual`) is filed under


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


def _escalon(total: Decimal, unidades: int, desde: int, hasta: int) -> Decimal:
    """Units [desde, hasta) of `total` spread over `unidades`, by cumulative rounding."""
    return _cents(total * hasta / unidades) - _cents(total * desde / unidades)


def gobiernan(periodos: List[Periodo]) -> List[int]:
    """The indexes of the periods that govern some day, in date order (an earlier one on the same `desde` never
    does)."""
    orden = sorted(range(len(periodos)), key=lambda k: (periodos[k].desde, k))
    return [k for n, k in enumerate(orden) if n + 1 == len(orden) or periodos[orden[n + 1]].desde != periodos[k].desde]


def _validar_manuales(lotes: List[Lote], periodos: List[Periodo]) -> None:
    """Every manual block has its governing manual period on its own date, and the other way round. A manual period
    read without its block (`modo_id` unset) is left out: it only fails once a sale reaches it (`Dinero`)."""
    bloques = sorted((lote.modo_id, lote.fecha) for lote in lotes if lote.modo_id is not None)
    manuales = sorted(
        (periodos[k].modo_id, periodos[k].desde)
        for k in gobiernan(periodos)
        if periodos[k].modo == "manual" and periodos[k].modo_id is not None
    )
    if bloques != manuales:
        raise ValueError(f"manual blocks {bloques} do not match the manual periods {manuales}")


def periodo_en(periodos: List[Periodo], fecha: date) -> Tuple[int, str]:
    """(index, mode) of the period governing `fecha`: the latest `desde` on or before it, the later in the list on the
    same `desde`; (-1, 'fifo') before the first one."""
    actual = (-1, "fifo")
    for i, periodo in enumerate(periodos):
        if periodo.desde <= fecha and (actual[0] < 0 or periodo.desde >= periodos[actual[0]].desde):
            actual = (i, periodo.modo)
    return actual


class Dinero:
    """The money pass: what each (sale, lot, units) row carries under the cost modes, fed in sale order.

    A period takes over at its `desde` from what the previous one left, sales or not in between (D2): `fifo` puts each
    lot's units back at the lot's own value (after FIFO it changes nothing); `ponderado` weighs the money the previous
    period left on the units left (a previous pool's money, a last price's value, or each lot's own money); `ultimo`
    values every unit at the newest lot's unit value; `manual` replaces what the lots before its block left and goes
    on FIFO."""

    def __init__(self, lotes: List[Lote], periodos: Iterable[Periodo] = ()) -> None:
        self.lotes = lotes
        self.periodos = list(periodos)
        _validar_manuales(lotes, self.periodos)
        self._pendientes = gobiernan(self.periodos)
        self.usadas = [0] * len(lotes)
        self._reemplazados: set = set()  # lots a manual block replaced: nothing left on them
        self._recargo = any(lote.descuento_ars < 0 for lote in lotes)  # a manual block raising the cost
        self._modo = "fifo"
        self._lote_seg: Dict[int, Tuple[int, Decimal, int]] = {}  # FIFO: lot -> (start used units, base, units)
        # `ponderado`: [lots counting, money, units, units taken];
        # `ultimo`: [lots counting, unit value, 1, units taken].
        self._seg: Optional[list] = None

    def _cuentan(self, fecha: date) -> int:
        """How many lots (FIFO order, dates never decrease) count on `fecha`."""
        return sum(1 for lote in self.lotes if lote.fecha <= fecha)

    def _libres(self, i: int) -> int:
        return 0 if i in self._reemplazados else self.lotes[i].cantidad - self.usadas[i]

    def _propio(self, i: int) -> Decimal:
        """The lot's own money left: its total minus what cumulative rounding gave the units already used, so a lot
        re-based mid-way still hands out exactly its total once used up."""
        lote = self.lotes[i]
        if i in self._reemplazados:
            return Decimal(0)
        resto = lote.descuento_ars - _cents(lote.descuento_ars * self.usadas[i] / lote.cantidad)
        # Never below zero: rounding up on a lot of a few thousandths can hand out more than it holds. A surcharge
        # block (negative) is below zero by design.
        return resto if lote.descuento_ars < 0 else max(resto, Decimal(0))

    def _resto_fifo(self, i: int) -> Decimal:
        if i in self._reemplazados:
            return Decimal(0)
        seg = self._lote_seg.get(i)
        if seg is None:
            return self._propio(i)
        inicio, base, unidades = seg
        return base - _cents(base * (self.usadas[i] - inicio) / unidades)

    def _resto_pool(self) -> Decimal:
        _, base, unidades, tomadas = self._seg
        return base - _cents(base * tomadas / unidades) if unidades else base

    def _dinero_restante(self, cuentan: int) -> Decimal:
        """The money the current state leaves on the units of the first `cuentan` lots."""
        if self._modo == "fifo":
            return sum((self._resto_fifo(j) for j in range(cuentan)), Decimal(0))
        hasta = self._seg[0]
        if self._modo == "ponderado":
            dentro = self._resto_pool()
        else:
            dentro = sum((self._seg[1] * self._libres(j) for j in range(hasta)), Decimal(0))
        return dentro + sum((self._propio(j) for j in range(hasta, cuentan)), Decimal(0))

    def _ultimo(self, cuentan: int) -> list:
        lote = self.lotes[cuentan - 1] if cuentan else None
        return [cuentan, lote.descuento_ars / lote.cantidad if lote else Decimal(0), 1, 0]

    def _avanzar(self, fecha: date) -> None:
        """Enters, in date order, every period that starts on or before `fecha`."""
        while self._pendientes and self.periodos[self._pendientes[0]].desde <= fecha:
            periodo = self.periodos[self._pendientes.pop(0)]
            if periodo.modo not in ("fifo", "ponderado", "ultimo", "manual"):
                # Refused only once it governs a sale: a row dated after them changes nothing yet.
                raise ValueError(f"cost mode {periodo.modo!r} is not supported here")
            if periodo.modo == "manual" and periodo.modo_id is None:
                raise ValueError("a manual cost mode read without its block cannot be replayed")
            if self._modo != "fifo":
                # The pool takes in the lots that started counting before the new period, sold from or not.
                self._unir(periodo.desde - timedelta(days=1))
            cuentan = self._cuentan(periodo.desde)
            if periodo.modo == "manual":
                bloque = next(i for i, lote in enumerate(self.lotes) if lote.modo_id == periodo.modo_id)
                self._reemplazados.update(range(bloque))
                self._lote_seg.clear()
                self._seg = None
                self._modo = "fifo"  # the block and the lots after it, each at its own value
                continue
            if periodo.modo == "fifo":
                if self._modo != "fifo":
                    self._lote_seg.clear()  # each lot back at its own value
                self._seg = None
            elif periodo.modo == "ponderado":
                dinero = self._dinero_restante(cuentan)
                self._seg = [cuentan, dinero, sum(self._libres(j) for j in range(cuentan)), 0]
            else:
                self._seg = self._ultimo(cuentan)
            self._modo = periodo.modo

    def _unir(self, fecha: date) -> None:
        """Lots that start counting inside a pool period join it: re-weighed (`ponderado`) or re-anchored (`ultimo`)."""
        cuentan = self._cuentan(fecha)
        if cuentan <= self._seg[0]:
            return
        if self._modo == "ultimo":
            self._seg = self._ultimo(cuentan)
            return
        dinero = self._dinero_restante(cuentan)
        self._seg = [cuentan, dinero, sum(self._libres(j) for j in range(cuentan)), 0]

    def fila(self, fecha: date, i: int, unidades: int) -> Decimal:
        self._avanzar(fecha)
        if self._modo == "fifo":
            seg = self._lote_seg.get(i)
            if seg is None:
                seg = (self.usadas[i], self._propio(i), self._libres(i))
                self._lote_seg[i] = seg
            k = self.usadas[i] - seg[0]
            monto = _escalon(seg[1], seg[2], k, k + unidades)
        else:
            self._unir(fecha)
            seg = self._seg
            k = seg[3]
            seg[3] += unidades
            monto = _escalon(seg[1], seg[2], k, k + unidades)
        self.usadas[i] += unidades
        # A used-up lot carries the half cent rounding gave it beyond its total (-0.005 at most) into what comes next;
        # only lots of a few thousandths, or none, can fail to cover it, and a row never goes below zero for that.
        # A product with a manual surcharge block hands out negative money as it is (the block's rows, or a pool
        # holding it).
        return monto if self._recargo else max(monto, Decimal("0.00"))

    def restante(self, fecha: date) -> Decimal:
        """The money every unit left would get, all sold on `fecha` after the rows fed so far, without feeding them:
        the lots' own money left under FIFO, the pool's under `ponderado`, the newest lot's value under `ultimo`."""
        sim = copy.deepcopy(self)
        sim._avanzar(fecha)
        if sim._modo != "fifo":
            sim._unir(fecha)
        return sim._dinero_restante(len(sim.lotes))

    def proximo(self, fecha: date) -> Optional[Tuple[int, Decimal, int, int]]:
        """What the next sale on `fecha` gets after the rows fed so far, without feeding it: `(lot the units come
        from, money, units it spreads over, units left at that value)`; None when no lot that counts has units."""
        sim = copy.deepcopy(self)
        sim._avanzar(fecha)
        libres = [j for j in range(sim._cuentan(fecha)) if sim._libres(j) > 0]
        if not libres:
            return None
        primero = libres[0]
        if sim._modo == "fifo":
            lote = sim.lotes[primero]
            return primero, lote.descuento_ars, lote.cantidad, sim._libres(primero)
        sim._unir(fecha)
        unidades = sum(sim._libres(j) for j in libres)
        if sim._modo == "ultimo":
            lote = sim.lotes[sim._seg[0] - 1]
            return primero, lote.descuento_ars, lote.cantidad, unidades
        return primero, sim._resto_pool(), unidades, unidades


Clave = Tuple[str, int]


def _unidades(lotes: List[Lote], ventas: List[Venta]) -> Dict[Clave, List[List[int]]]:
    """Pass 1, units only: `{sale: [[lote index, units], ...]}` in the order taken. From a manual block's date on,
    the lots before it have nothing left, and units freed into them are dropped."""
    libres = [lote.cantidad for lote in lotes]
    bloques = [i for i, lote in enumerate(lotes) if lote.modo_id is not None]  # FIFO order: dates never decrease
    reemplazados = [False] * len(lotes)
    tenencia: Dict[Clave, List[List[int]]] = {}
    orden: List[Clave] = []  # the sales processed so far, in allocation order
    for venta in ventas:
        while bloques and lotes[bloques[0]].fecha <= venta.fecha:
            for j in range(bloques.pop(0)):
                libres[j] = 0
                reemplazados[j] = True
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
                    if not reemplazados[i]:
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


def asignar(lotes: Iterable[Lote], ventas: Iterable[Venta], periodos: Iterable[Periodo] = ()) -> List[Consumo]:
    """The consumptions of ONE product: its active purchase lines against its sales and returns, under its dated
    cost modes (`periodos`, oldest first; none: FIFO)."""
    lotes = sorted(lotes, key=orden_fifo)
    ventas = sorted(ventas, key=lambda v: (v.fecha, v.unidades < 0, v.canal, v.venta_ref))
    _validar(lotes, ventas)
    periodos = list(periodos)
    _validar_manuales(lotes, periodos)
    if not lotes:
        return []
    fechas = {(v.canal, v.venta_ref): v.fecha for v in ventas}
    tenencia = _unidades(lotes, ventas)

    # Pass 2, money: the final holdings in sale order (within a sale, FIFO lot order), so a fully used line still
    # adds up exactly under FIFO and the money a period hands out only depends on the sales before it.
    dinero = Dinero(lotes, periodos)
    consumos: List[Consumo] = []
    for clave in sorted(tenencia, key=lambda c: (fechas[c], c[0], c[1])):
        por_lote: Dict[int, int] = {}
        for i, unidades in tenencia[clave]:
            por_lote[i] = por_lote.get(i, 0) + unidades
        for i in sorted(por_lote):
            consumos.append(
                Consumo(
                    compra_item_id=lotes[i].compra_item_id,
                    canal=clave[0],
                    venta_ref=clave[1],
                    fecha_venta=fechas[clave],
                    unidades=por_lote[i],
                    descuento_ars=dinero.fila(fechas[clave], i, por_lote[i]),
                )
            )
    return sorted(consumos, key=lambda c: (fechas[(c.canal, c.venta_ref)], c.canal, c.venta_ref, c.compra_item_id))
