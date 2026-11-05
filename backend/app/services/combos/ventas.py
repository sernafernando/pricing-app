"""A combo's sale seen as sales of its components, for sell in and sell out (owner, 2026-11-05).

Owner: "hay algo que no tuvimos en cuenta en sell in / sell out, las notebooks que son combos, por ejemplo una con -wh
resta stock de la notebook base?", then, choosing: "El combo consume los lotes de sell in de cada componente y cuenta
para sus campañas de sell out. En una campaña por % de precio, a la notebook le toca la parte del precio del combo
proporcional a su costo dentro del combo."

So a sale (or return) of `qty` combos is, for each component, a sale of `qty x cantidad` units of that component
under the component's `item_id`, keeping the sale's own `venta_ref`; the combo itself is never counted as its own item
(never twice). The bill of materials is `combo_componentes` through `componentes` (the one reader), and like ML costing
it fails closed while that table is empty (`CombosNoSincronizados`): a combo would otherwise count as a plain item.

Each component's share (`Parte.peso`) of the combo's price and recorded cost is its cost times its quantity over the
same sum for the whole combo. The cost is the product's own `productos_erp.costo` in ARS (a USD cost at today's rate,
`pricing_calculator.obtener_tipo_cambio_actual`), the same source the sell-in lot viewer and ML costing use for a
product's current cost, positive only (`costeo_service.tiene_costo_propio`). When any component of the combo has no
usable cost (none, zero, or USD with no rate), the combo is split equally per unit: `cantidad / sum of cantidades`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.services.combos.componentes import combos_que_contienen, componentes_de, exigir_combos_disponibles
from app.services.pricing_calculator import obtener_tipo_cambio_actual


@dataclass(frozen=True)
class Parte:
    componente: int  # the component's item_id
    cantidad: Decimal  # units of the component per unit of the combo
    peso: Decimal  # its share of the combo's price and cost; the parts of a combo add up to 1


def partes_de_combos(db: Session, item_ids: Iterable[int]) -> Dict[int, List[Parte]]:
    """`{combo: its parts, by component}` for every combo holding one of `item_ids`, and for the ones of `item_ids`
    that are combos themselves (so a reader can skip their own rows). A fixed number of queries. Raises
    `CombosNoSincronizados` while the bill of materials is empty."""
    ids = {int(i) for i in item_ids if i is not None}
    if not ids:
        return {}
    exigir_combos_disponibles(db)
    combos = set().union(*combos_que_contienen(db, ids).values()) | set(componentes_de(db, ids))
    composicion = componentes_de(db, combos)
    costos = _costos_ars(db, {c for comps in composicion.values() for c in comps})
    return {combo: _partes(comps, costos) for combo, comps in sorted(composicion.items())}


def unidades_de(qty: int, parte: Parte) -> int:
    """The component's units in `qty` combos (negative for a return). A fractional result is refused: units are
    whole, and rounding would hand out lots or campaign units nobody sold."""
    unidades = Decimal(qty) * parte.cantidad
    if unidades != unidades.to_integral_value():
        raise ValueError(f"combo component {parte.componente}: {qty} x {parte.cantidad} is not a whole number of units")
    return int(unidades)


def _partes(comps: Dict[int, Decimal], costos: Dict[int, Decimal]) -> List[Parte]:
    if all(c in costos for c in comps):
        valores = {c: costos[c] * cantidad for c, cantidad in comps.items()}
    else:
        valores = dict(comps)  # equal split per unit
    total = sum(valores.values(), Decimal(0))
    return [Parte(c, comps[c], valores[c] / total) for c in sorted(comps)]


def _costos_ars(db: Session, item_ids: set[int]) -> Dict[int, Decimal]:
    """`{item_id: positive unit cost in ARS}`; a product without a usable cost is absent."""
    if not item_ids:
        return {}
    filas = db.query(ProductoERP.item_id, ProductoERP.costo, ProductoERP.moneda_costo).filter(
        ProductoERP.item_id.in_(sorted(item_ids))
    )
    tasa: Optional[Decimal] = None
    salida: Dict[int, Decimal] = {}
    for item_id, costo, moneda in filas:
        if costo is None or Decimal(str(costo)) <= 0:
            continue
        valor = Decimal(str(costo))
        if str(getattr(moneda, "value", moneda) or "ARS").upper() == "USD":
            if tasa is None:
                actual = obtener_tipo_cambio_actual(db, "USD")
                if actual is None:
                    continue
                tasa = Decimal(str(actual))
            valor *= tasa
        salida[item_id] = valor
    return salida
