"""The costo SI arithmetic (S1, S5, S9, S10), pure: no database, no clock.

A product starts at its first sell-in date with the stock it had then, valued at the historical list cost of that day
(`Inicio`), less every brand loyalty in force that day (owner L39/L40: the stock on hand gets the loyalty too). Every purchase invoice after that enters in two steps (S5, L3): its stored NET unit cost, then every sell
in that applies to it, all as a % of that same net and added up: 100 x (1 - 0.05 - 0.036) = 91.40 (L5). Then

    new average = (stock before x average + qty x net-net) / (stock before + qty)            (S1)

Sales, returns and adjustments never change the average: they only move the stock, which the caller reads before each
purchase (`Compra.stock_antes`). A stock of zero or less counts as zero, so the average restarts at that purchase's
net-net (S9, L4.6). A product no sell in reaches (L21) also re-anchors at every change of its list cost (`Lista`,
L23): from that day the average is the new list cost, and later purchases average from it. Averages are kept with 5 decimals (S10); each step uses the stored, rounded value, so the history
can be re-derived from the stored rows alone.

A suspicious purchase (owner L29) does not enter the average until a reviewer accepts it: its net unit price, before
sell ins, is below 1/10 or above 10x the reference, the average in force right before it (after a same-day list
re-anchor), or, with no average yet, the list cost on its date (`Compra.referencia_lista`). Without any reference it
is not checked. It becomes an 'excluido' step: its units are valued at the average in force, which carries forward
(at the reference when there was no average). Accepted (`aceptadas`), it averages in like any purchase. Either way
the step carries its reference, so the caller can list it for review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import AbstractSet, Iterable, List, Optional, Tuple

DECIMALS = Decimal("0.00001")
CIEN = Decimal(100)
SOSPECHA_FACTOR = Decimal(10)  # L29: below 1/10 or above 10x the reference
FUENTE_REF_COSTO_SI = "costo_si"
FUENTE_REF_LISTA = "lista"


def redondear(value: Decimal) -> Decimal:
    """5 decimals, half up (S10)."""
    return value.quantize(DECIMALS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SellIn:
    """One sell in applied to a purchase: `origen` 'compra' (a Compras sell in, `ref` = `sell_in_compras.id`) or
    'bono' (a brand bonus such as a loyalty, `ref` = `sell_in_bonos_marca.id`), as a % of the purchase's net."""

    origen: str
    ref: int
    porcentaje: Decimal


@dataclass(frozen=True)
class Inicio:
    fecha: date
    stock: int
    costo_usd: Optional[Decimal]  # historical list cost in force; None: there is none
    # The brand loyalties in force on `fecha` (owner L39/L40): the starting stock gets them too, as a % of its cost.
    sell_ins: Tuple[SellIn, ...] = ()


@dataclass(frozen=True)
class Lista:
    """A list-cost change of a product without sell in (L23): from 00:00 of `fecha` the average is `costo_usd`."""

    fecha: date
    costo_usd: Decimal
    stock: int  # available stock at that instant


@dataclass(frozen=True)
class Compra:
    fecha: date  # supplier invoice date (S4, L4.4)
    ct_transaction: int
    cantidad: int
    costo_neto_usd: Decimal  # net unit cost in USD, before any sell in
    sell_ins: Tuple[SellIn, ...]
    stock_antes: int  # available stock right before it (S3), as the source reconstructed it
    tipo_cambio: Optional[Decimal] = None
    fuente_tc: Optional[str] = None  # 'usd' | 'ars' (in the product's currency) | 'manual' | 'pedido' | 'fecha_factura'
    en_compras: bool = False  # linked to a Compras operation (S7)
    referencia_lista: Optional[Decimal] = None  # list cost on its date: the L29 reference when there is no average
    # The unit price as loaded on the invoice, in its own currency (L29: what a reviewer looks for on the invoice).
    precio_factura: Optional[Decimal] = None
    moneda_factura: Optional[str] = None


@dataclass(frozen=True)
class Paso:
    """One step of a product's history: the average in force from `fecha` on, with its breakdown."""

    tipo: str  # 'inicio' | 'compra' | 'lista' (L23) | 'excluido' (L29)
    fecha: date
    ct_transaction: Optional[int]
    cantidad: int
    costo_neto_usd: Optional[Decimal]
    sell_ins: Tuple[SellIn, ...]
    sell_in_pct: Decimal
    costo_neto_neto_usd: Optional[Decimal]
    stock_antes: int
    stock_base: int  # the stock the average weighs: stock_antes, or 0 when it was 0 or less (S9)
    stock_despues: int
    promedio_usd: Optional[Decimal]
    tipo_cambio: Optional[Decimal] = None
    fuente_tc: Optional[str] = None
    en_compras: bool = False
    # A suspicious purchase (L29), excluded or accepted: the cost it was checked against, and where it came from
    # ('costo_si' | 'lista'). Not stored in the steps: the review table keeps it.
    referencia: Optional[Decimal] = None
    fuente_ref: Optional[str] = None
    precio_factura: Optional[Decimal] = None  # the invoice's own unit price and currency, set with `referencia`
    moneda_factura: Optional[str] = None


def sospechoso(precio: Decimal, referencia: Optional[Decimal]) -> bool:
    """L29: below 1/10 or above 10x a positive reference; exactly 1/10 or 10x is not suspicious."""
    if referencia is None or referencia <= 0:
        return False
    return precio * SOSPECHA_FACTOR < referencia or precio > referencia * SOSPECHA_FACTOR


def neto_neto(neto: Decimal, sell_ins: Iterable[SellIn]) -> Tuple[Decimal, Decimal]:
    """(sum of the %, net-net): every sell in is a % of the same net and they add up (S5). Never below zero."""
    pct = sum((s.porcentaje for s in sell_ins), Decimal(0))
    return pct, redondear(max(neto * (1 - pct / CIEN), Decimal(0)))


def _anclaje(lista: Lista) -> Paso:
    costo = redondear(lista.costo_usd)
    base = max(lista.stock, 0)
    return Paso(
        tipo="lista",
        fecha=lista.fecha,
        ct_transaction=None,
        cantidad=lista.stock,
        costo_neto_usd=costo,
        sell_ins=(),
        sell_in_pct=Decimal(0),
        costo_neto_neto_usd=costo,
        stock_antes=lista.stock,
        stock_base=base,
        stock_despues=base,
        promedio_usd=costo,
    )


def calcular(
    inicio: Inicio,
    compras: Iterable[Compra],
    listas: Iterable[Lista] = (),
    aceptadas: AbstractSet[int] = frozenset(),
) -> List[Paso]:
    """The product's history: its start, then one step per purchase in the given order, with every list-cost
    re-anchor (L23) placed before the purchases of its own day (it is in force from 00:00). A suspicious purchase
    (L29) whose invoice is not in `aceptadas` is an 'excluido' step that leaves the average as it was."""
    pendientes = sorted(listas, key=lambda x: x.fecha)
    costo_inicio = redondear(inicio.costo_usd) if inicio.costo_usd is not None else None
    pct_inicio = sum((s.porcentaje for s in inicio.sell_ins), Decimal(0))
    # An unknown start cost stays unknown, loyalty or not: never a 0 (§7).
    promedio = neto_neto(costo_inicio, inicio.sell_ins)[1] if costo_inicio is not None else None
    base_inicio = max(inicio.stock, 0)
    pasos = [
        Paso(
            tipo="inicio",
            fecha=inicio.fecha,
            ct_transaction=None,
            cantidad=inicio.stock,
            costo_neto_usd=costo_inicio,
            sell_ins=inicio.sell_ins,
            sell_in_pct=pct_inicio,
            costo_neto_neto_usd=promedio,
            stock_antes=inicio.stock,
            stock_base=base_inicio,
            stock_despues=base_inicio,
            promedio_usd=promedio,
        )
    ]
    for c in compras:
        while pendientes and pendientes[0].fecha <= c.fecha:
            pasos.append(_anclaje(pendientes.pop(0)))
            promedio = pasos[-1].promedio_usd
        if c.cantidad <= 0:
            continue
        pct, nn = neto_neto(c.costo_neto_usd, c.sell_ins)
        base = max(c.stock_antes, 0)
        precio = redondear(c.costo_neto_usd)
        referencia, fuente_ref = (promedio, FUENTE_REF_COSTO_SI) if promedio is not None else (None, None)
        if referencia is None and c.referencia_lista is not None:
            referencia, fuente_ref = redondear(c.referencia_lista), FUENTE_REF_LISTA
        if not sospechoso(precio, referencia):
            referencia = fuente_ref = None
        excluida = referencia is not None and c.ct_transaction not in aceptadas
        if excluida:
            promedio = promedio if promedio is not None else referencia
        elif base == 0 or promedio is None:
            promedio = nn
        else:
            promedio = redondear((base * promedio + c.cantidad * nn) / (base + c.cantidad))
        pasos.append(
            Paso(
                tipo="excluido" if excluida else "compra",
                fecha=c.fecha,
                ct_transaction=c.ct_transaction,
                cantidad=c.cantidad,
                costo_neto_usd=precio,
                sell_ins=c.sell_ins,
                sell_in_pct=pct,
                costo_neto_neto_usd=nn,
                stock_antes=c.stock_antes,
                stock_base=base,
                stock_despues=base + c.cantidad,
                promedio_usd=promedio,
                tipo_cambio=c.tipo_cambio,
                fuente_tc=c.fuente_tc,
                en_compras=c.en_compras,
                referencia=referencia,
                fuente_ref=fuente_ref,
                precio_factura=c.precio_factura if referencia is not None else None,
                moneda_factura=c.moneda_factura if referencia is not None else None,
            )
        )
    pasos.extend(_anclaje(x) for x in pendientes)
    return pasos
