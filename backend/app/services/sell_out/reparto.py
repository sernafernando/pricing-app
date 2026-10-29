"""A `monto_total` campaign's split (sell-in-sell-out T26b, S34/S35): a pure function, no database.

The PM or an admin shares the campaign's one amount out by hand per product
(`sell_out_campana_items`): a % of the total (`reparto_porcentaje`, so it has
the total's sign) or a fixed amount (`reparto_monto`). A product's share
(`cuota`), in the campaign currency, rounded once to cents half away from zero
(like Postgres NUMERIC), spreads over that product's sales in the campaign's
dates by units (owner: not equal, not by units across products; the split
across products is the manual share). `repartir` gets the sales' net units
from `tope.asignar` (its returns handling), so a return inside the dates moves
the share to the units kept. Cents by cumulative rounding: a row's amount is
`cents(share * units up to it / product units) - what the rows before it got`,
so the product's rows add up exactly to its share. A row left with no money
(a share of a few cents over many sales) is not written.

VAT: with `monto_incluye_iva` a share is divided by its own product's VAT,
like a per-unit amount (`tope.credito_unitario`), then rounded to cents.

Not written, only reported (`resumen_monto_total`; readers count both on the
campaign's `fecha_hasta`, T26b2): a share whose product has no sale in the
dates ("Asignado sin ventas", net of VAT like the rows it would have written)
and the remainder nobody was given, total − Σ shares ("Sin asignar", as
loaded: it has no product, so no VAT rate to strip).

Shares are checked, never repaired (`validar`, also run by `repartir` and
`resumen_monto_total`): a share must be a % or an amount, a fixed share has the
total's sign and |Σ shares| <= |total|, compared before rounding so a whole
split of an odd-cent total is not refused for its cents. Like `tope`, anything
inconsistent raises `ValueError`; the allocator fails the campaign with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from app.services.sell_out.tope import CIEN, Consumo, cents

Reparto = Tuple[Optional[Decimal], Optional[Decimal]]  # (reparto_porcentaje, reparto_monto): exactly one is set


@dataclass(frozen=True)
class MontoTotal:
    """What the split needs from a `monto_total` `SellOutCampana` and its shares."""

    monto_total: Decimal  # campaign currency; negative: a deduction (S35)
    repartos: Mapping[int, Reparto]  # item_id -> its share
    monto_incluye_iva: bool = False
    ivas: Mapping[int, Optional[Decimal]] = field(default_factory=dict)  # item_id -> its VAT rate, in percent


class RepartoInvalido(ValueError):
    """The shares cannot be split as they stand, with what broke for a message to the operator (`causa`):
    `signo`, the product whose share does not have the total's sign (`item_id`); `excede`, the shares' sum over
    the total (`suma`, `total`, both rounded to cents); `sin_iva`, a product without a VAT rate on a campaign
    loaded with VAT (`item_id`)."""

    def __init__(
        self,
        message: str,
        *,
        causa: str = "excede",
        item_id: Optional[int] = None,
        suma: Optional[Decimal] = None,
        total: Optional[Decimal] = None,
    ) -> None:
        super().__init__(message)
        self.causa, self.item_id, self.suma, self.total = causa, item_id, suma, total


def _exacta(c: MontoTotal, item_id: int) -> Decimal:
    porcentaje, monto = c.repartos[item_id]
    if porcentaje is None and monto is None:
        raise ValueError(f"product {item_id} has no share: neither a percent nor an amount")
    return Decimal(monto) if porcentaje is None else Decimal(c.monto_total) * Decimal(porcentaje) / CIEN


def _cargada(c: MontoTotal, item_id: int) -> Decimal:
    return cents(_exacta(c, item_id))


def validar(c: MontoTotal) -> None:
    """Raises `RepartoInvalido` (a `ValueError`) when the shares cannot be split as they stand (module docstring)."""
    total = Decimal(c.monto_total)
    suma = Decimal(0)
    for item_id in c.repartos:
        exacta = _exacta(c, item_id)
        if (exacta < 0) != (total < 0):
            raise RepartoInvalido(
                f"product {item_id}'s share {exacta} does not have the total's sign", causa="signo", item_id=item_id
            )
        suma += exacta
    if abs(suma) > abs(total):
        raise RepartoInvalido(
            f"the shares ({cents(suma)}) exceed the total ({cents(total)})", suma=cents(suma), total=cents(total)
        )


def cuota(c: MontoTotal, item_id: int) -> Decimal:
    """A product's share in the campaign currency, cents, net of its own VAT when loaded with it."""
    cargada = _cargada(c, item_id)
    if not c.monto_incluye_iva:
        return cargada
    iva = c.ivas.get(item_id)
    if iva is None:
        raise RepartoInvalido(f"product {item_id} has no VAT rate", causa="sin_iva", item_id=item_id)
    return cents(cargada / (1 + Decimal(iva) / CIEN))


def repartir(c: MontoTotal, consumos: Iterable[Consumo]) -> List[Consumo]:
    """The rows of the campaign: each product's share over its `consumos` (net units, sale order) by units."""
    validar(c)
    consumos = [x for x in consumos if x.item_id in c.repartos and x.unidades > 0]
    totales: Dict[int, int] = {}
    for x in consumos:
        totales[x.item_id] = totales.get(x.item_id, 0) + x.unidades
    cuotas = {item_id: cuota(c, item_id) for item_id in totales}
    llevadas: Dict[int, Tuple[int, Decimal]] = {}  # item_id -> (units so far, money so far)
    salida = []
    for x in consumos:
        unidades, dado = llevadas.get(x.item_id, (0, Decimal("0.00")))
        unidades += x.unidades
        acumulado = cents(cuotas[x.item_id] * unidades / totales[x.item_id])
        llevadas[x.item_id] = (unidades, acumulado)
        if acumulado != dado:
            salida.append(Consumo(x.canal, x.venta_ref, x.item_id, x.fecha_venta, x.unidades, acumulado - dado))
    return salida


def resumen_monto_total(c: MontoTotal, con_ventas: Iterable[int]) -> Dict[str, Decimal]:
    """`{asignado_sin_ventas, sin_asignar}`: what the campaign's rows do not carry (module docstring).
    `con_ventas`: the products with sales the campaign reaches in its dates."""
    validar(c)
    con_ventas = set(con_ventas)
    sin_ventas = sum((cuota(c, i) for i in c.repartos if i not in con_ventas), Decimal("0.00"))
    asignado = sum((_cargada(c, i) for i in c.repartos), Decimal("0.00"))
    return {"asignado_sin_ventas": sin_ventas, "sin_asignar": cents(Decimal(c.monto_total)) - asignado}
