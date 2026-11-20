"""The costo SI arithmetic (S1, S5, S9, S10), pure: no database, no clock.

A product starts at its first sell-in date with the stock it had then, valued at the historical list cost of that day
(`Inicio`). Every purchase invoice after that enters in two steps (S5, L3): its stored NET unit cost, then every sell
in that applies to it, all as a % of that same net and added up: 100 x (1 - 0.05 - 0.036) = 91.40 (L5). Then

    new average = (stock before x average + qty x net-net) / (stock before + qty)            (S1)

Sales, returns and adjustments never change the average: they only move the stock, which the caller reads before each
purchase (`Compra.stock_antes`). A stock of zero or less counts as zero, so the average restarts at that purchase's
net-net (S9, L4.6). Averages are kept with 5 decimals (S10); each step uses the stored, rounded value, so the history
can be re-derived from the stored rows alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, List, Optional, Tuple

DECIMALS = Decimal("0.00001")
CIEN = Decimal(100)


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


@dataclass(frozen=True)
class Compra:
    fecha: date  # supplier invoice date (S4, L4.4)
    ct_transaction: int
    cantidad: int
    costo_neto_usd: Decimal  # net unit cost in USD, before any sell in
    sell_ins: Tuple[SellIn, ...]
    stock_antes: int  # available stock right before it (S3), as the source reconstructed it
    tipo_cambio: Optional[Decimal] = None
    fuente_tc: Optional[str] = None  # 'usd' | 'manual' | 'pedido' | 'fecha_factura'
    en_compras: bool = False  # linked to a Compras operation (S7)


@dataclass(frozen=True)
class Paso:
    """One step of a product's history: the average in force from `fecha` on, with its breakdown."""

    tipo: str  # 'inicio' | 'compra'
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


def neto_neto(neto: Decimal, sell_ins: Iterable[SellIn]) -> Tuple[Decimal, Decimal]:
    """(sum of the %, net-net): every sell in is a % of the same net and they add up (S5). Never below zero."""
    pct = sum((s.porcentaje for s in sell_ins), Decimal(0))
    return pct, redondear(max(neto * (1 - pct / CIEN), Decimal(0)))


def calcular(inicio: Inicio, compras: Iterable[Compra]) -> List[Paso]:
    """The product's history: its start, then one step per purchase, in the given order."""
    promedio = redondear(inicio.costo_usd) if inicio.costo_usd is not None else None
    base_inicio = max(inicio.stock, 0)
    pasos = [
        Paso(
            tipo="inicio",
            fecha=inicio.fecha,
            ct_transaction=None,
            cantidad=inicio.stock,
            costo_neto_usd=promedio,
            sell_ins=(),
            sell_in_pct=Decimal(0),
            costo_neto_neto_usd=promedio,
            stock_antes=inicio.stock,
            stock_base=base_inicio,
            stock_despues=base_inicio,
            promedio_usd=promedio,
        )
    ]
    for c in compras:
        if c.cantidad <= 0:
            continue
        pct, nn = neto_neto(c.costo_neto_usd, c.sell_ins)
        base = max(c.stock_antes, 0)
        if base == 0 or promedio is None:
            promedio = nn
        else:
            promedio = redondear((base * promedio + c.cantidad * nn) / (base + c.cantidad))
        pasos.append(
            Paso(
                tipo="compra",
                fecha=c.fecha,
                ct_transaction=c.ct_transaction,
                cantidad=c.cantidad,
                costo_neto_usd=redondear(c.costo_neto_usd),
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
            )
        )
    return pasos
