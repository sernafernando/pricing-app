"""envio_tramos — an ML shipping cost that depends on the price it is evaluated at.

ML charges the seller shipping by item-price bracket (e.g. below 33000 nothing, 33000-49999 one cost,
from 50000 another). ml-webhook stores, per MLA, `list_cost` at the publication's current sale price and
`cost_by_bracket` with the cost of every bracket.

`CostoEnvioTramos` IS that `list_cost` (a float: what screens display, today's cost at the sale price) and
also carries the brackets, so `calcular_limpio` prices any candidate price with ITS bracket. Because it is a
float, it travels unchanged through every resolver dict and helper that only passes the cost along; the
pricing formula is the one place that resolves it (`costo_envio_para`). Arithmetic on it yields a plain float.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional, TypeVar

K = TypeVar("K")


class CostoEnvioTramos(float):
    """A shipping cost (ARS, with IVA): its float value is the cost at the sale price; `tramos` holds
    `(min_price, cost)` per bracket, ascending."""

    tramos: tuple[tuple[float, float], ...]

    def __new__(cls, valor: float, tramos: Iterable[tuple[float, float]]) -> "CostoEnvioTramos":
        obj = super().__new__(cls, valor)
        obj.tramos = tuple(sorted((float(piso), float(costo)) for piso, costo in tramos))
        return obj

    def __reduce__(self) -> tuple[Any, ...]:
        return (CostoEnvioTramos, (float(self), self.tramos))

    def __repr__(self) -> str:
        return f"CostoEnvioTramos({float(self)!r}, {self.tramos!r})"

    @classmethod
    def desde_fila(cls, list_cost: float, cost_by_bracket: Any) -> float:
        """The cost of one `ml_seller_shipping_costs` row: bracketed when `cost_by_bracket` is a valid list,
        else the plain `list_cost` (rows written before ml-webhook stored brackets)."""
        tramos = _tramos_validos(cost_by_bracket)
        return cls(list_cost, tramos) if tramos else float(list_cost)

    def para(self, precio: float) -> float:
        """The cost at `precio`: its bracket's cost when that is > 0, else the float value (a bracket without a
        cost is one where ML charges nothing; `calcular_limpio` already skips shipping below its threshold)."""
        costo = next((c for piso, c in reversed(self.tramos) if piso <= precio), None)
        return costo if costo is not None and costo > 0 else float(self)


def _tramos_validos(raw: Any) -> Optional[list[tuple[float, float]]]:
    if not isinstance(raw, list) or not raw:
        return None
    tramos = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            return None
        piso, costo = entry.get("min_price"), entry.get("list_cost")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (piso, costo)):
            return None
        tramos.append((float(piso), float(costo)))
    return tramos


def costo_envio_para(costo: float, precio: float) -> float:
    """The shipping cost to subtract at `precio`: the bracket's for a `CostoEnvioTramos`, else `costo` as is."""
    return costo.para(precio) if isinstance(costo, CostoEnvioTramos) else costo


def por_tramo(agregar: Callable[[Mapping[K, float]], Optional[float]], costs: Mapping[K, float]) -> Optional[float]:
    """`agregar(costs)` (a max, a mean, a choice), also applied bracket by bracket when any cost is bracketed.

    The float value aggregates the costs at their sale prices (what is shown today); bracket `p` aggregates
    every cost evaluated at `p`, so a product's MAX at 41999 is the MAX of its MLAs' costs AT 41999."""
    valor = agregar({k: float(c) for k, c in costs.items()})
    pisos = sorted({piso for c in costs.values() if isinstance(c, CostoEnvioTramos) for piso, _ in c.tramos})
    if valor is None or not pisos:
        return valor
    tramos = []
    for piso in pisos:
        costo = agregar({k: costo_envio_para(c, piso) for k, c in costs.items()})
        tramos.append((piso, costo if costo is not None else 0.0))
    return CostoEnvioTramos(valor, tramos)
