"""Sell in and sell out credited to each sale of a page, for the operations lists (sell-in-sell-out T14).

Owner: "Always show both: cost and cost with sell in; markup and totals without and with sell out."
Sell in lowers cost; sell out is a credit added to profit, applied against the net without VAT (the
allocator already wrote each row net of VAT).

Read only, from what the allocators wrote, for any channel (`ml`, `fuera`, `tn`; `venta_ref` is the
channel's sale line, `ventas_fuera_ml_metricas.it_transaction` for `fuera`):
- `sell_in_ars`: the sum of the sale's `sell_in_consumos.descuento_ars` (already ARS);
- `sell_out_ars`: the sum of the sale's `sell_out_consumos` in ARS, converted per campaign like the
  sell-out screen (`resumen.monto_ars`). A USD row without its rate leaves it unknown (None), never a
  partial sum, and makes it `sell_out_estimado`, as does an `al_cobro` campaign whose rate is not set
  yet (`resumen.ars_estimado`).
A sale without rows of a kind has None for that kind (`sell_out_estimado` too); a sale without rows
of either kind is not in the result. Two queries for the whole page, whatever its size.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sell_in import SellInConsumo
from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.services.sell_out import resumen


@dataclass(frozen=True)
class MontosVenta:
    sell_in_ars: Optional[Decimal] = None
    sell_out_ars: Optional[Decimal] = None
    sell_out_estimado: Optional[bool] = None

    @property
    def credito_ars(self) -> Optional[Decimal]:
        """What sell in and sell out add to the sale's profit; None while the sell out is unknown."""
        if self.sell_out_estimado and self.sell_out_ars is None:
            return None
        return (self.sell_in_ars or Decimal(0)) + (self.sell_out_ars or Decimal(0))


def _sell_in(db: Session, canal: str, refs: List[int]) -> Dict[int, Decimal]:
    t = SellInConsumo
    rows = (
        db.query(t.venta_ref, func.sum(t.descuento_ars))
        .filter(t.canal == canal, t.venta_ref.in_(refs))
        .group_by(t.venta_ref)
    )
    return {int(ref): Decimal(total) for ref, total in rows}


def _sell_out(db: Session, canal: str, refs: List[int]) -> Dict[int, tuple]:
    """`{venta_ref: (sell_out_ars, estimado)}`, from one row per sale and campaign."""
    t = SellOutConsumo
    rows = (
        db.query(
            t.venta_ref,
            SellOutCampana,
            func.sum(t.monto),
            func.sum(resumen.ARS_FILA),
            func.count() - func.count(t.tc_venta),
        )
        .join(SellOutCampana, SellOutCampana.id == t.campana_id)
        .filter(t.canal == canal, t.venta_ref.in_(refs))
        .group_by(t.venta_ref, SellOutCampana.id)
    )
    por_venta: Dict[int, List[tuple]] = defaultdict(list)
    for ref, campana, monto, monto_ars_fila, sin_tasa in rows:
        ars = resumen.monto_ars(campana, Decimal(monto), [monto_ars_fila], int(sin_tasa))
        por_venta[int(ref)].append((ars, resumen.ars_estimado(campana)))
    salida = {}
    for ref, campanas in por_venta.items():
        montos = [ars for ars, _ in campanas]
        desconocido = any(ars is None for ars in montos)
        total = None if desconocido else sum(montos, Decimal(0))
        salida[ref] = (total, desconocido or any(estimado for _, estimado in campanas))
    return salida


def montos_por_venta(db: Session, canal: str, refs: Iterable[int]) -> Dict[int, MontosVenta]:
    """`{venta_ref: MontosVenta}` for the page's sales of `canal` that have sell in or sell out."""
    refs = sorted(set(refs))
    if not refs:
        return {}
    sell_in = _sell_in(db, canal, refs)
    sell_out = _sell_out(db, canal, refs)
    salida = {}
    for ref in sell_in.keys() | sell_out.keys():
        ars, estimado = sell_out.get(ref, (None, None))
        salida[ref] = MontosVenta(sell_in_ars=sell_in.get(ref), sell_out_ars=ars, sell_out_estimado=estimado)
    return salida


def con_sell_in_out(
    costo: Decimal, ganancia: Decimal, montos: Optional[MontosVenta], *, ganancia_markup: Optional[Decimal] = None
) -> dict:
    """A sale's figures with sell in and sell out, from the ones its list shows without them: sell in
    lowers the cost, both add to the profit. The markup is `ganancia_markup` (the profit the list's own
    markup is computed from, `ganancia` by default) plus both, over the cost with sell in, as a
    fraction, only while that cost is positive. `{}` for a sale without either (the response fields
    stay null); profit and markup null while its sell out is unknown."""
    if montos is None:
        return {}
    costo_con = costo - (montos.sell_in_ars or Decimal(0))
    credito = montos.credito_ars
    ganancia_con = None if credito is None else ganancia + credito
    base = ganancia if ganancia_markup is None else ganancia_markup
    markup_con = (base + credito) / costo_con if credito is not None and costo_con > 0 else None
    return {
        "sell_in_ars": None if montos.sell_in_ars is None else float(montos.sell_in_ars),
        "sell_out_ars": None if montos.sell_out_ars is None else float(montos.sell_out_ars),
        "sell_out_estimado": montos.sell_out_estimado,
        "costo_con_sell_in": float(costo_con),
        "ganancia_con_sell_in_out": None if ganancia_con is None else float(ganancia_con),
        "markup_con_sell_in_out": None if markup_con is None else float(markup_con),
    }
