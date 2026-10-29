"""Sell in and sell out credited to each sale of a page, for the operations lists (sell-in-sell-out T14).

Owner: "Always show both: cost and cost with sell in; markup and totals without and with sell out."
Sell in lowers cost; sell out is a credit added to profit, applied against the net without VAT (the
allocator already wrote each row net of VAT).

Read only, from what the allocators wrote, for any channel (`ml`, `fuera`, `tn`; `venta_ref` is the
channel's sale line, `ventas_fuera_ml_metricas.it_transaction` for `fuera`):
- `sell_in_ars`: the sum of the sale's `sell_in_consumos.descuento_ars` plus its `sell_in_bono_consumos` ones (the %
  of cost bonuses, T25: units the invoice sell in left, so they never overlap), already ARS;
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

from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

from app.models.sell_in import SellInBonoConsumo, SellInConsumo
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
    filas = union_all(
        *(
            select(t.venta_ref, t.descuento_ars).where(t.canal == canal, t.venta_ref.in_(refs))
            for t in (SellInConsumo, SellInBonoConsumo)
        )
    ).subquery()
    rows = db.query(filas.c.venta_ref, func.sum(filas.c.descuento_ars)).group_by(filas.c.venta_ref)
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


def sumar(partes: Iterable[Optional[MontosVenta]]) -> Optional[MontosVenta]:
    """Several sales' amounts as one (an ML order's item rows, a pack's orders), under each kind's rule:
    a part without rows of a kind adds nothing to it; an unknown sell out (`sell_out_estimado` without
    an amount) makes the total unknown, never a partial sum. None when no part has any row."""
    partes = [p for p in partes if p is not None]
    if not partes:
        return None
    sell_in = [p.sell_in_ars for p in partes if p.sell_in_ars is not None]
    con_sell_out = [p for p in partes if p.sell_out_estimado is not None]
    sell_out_ars = None
    estimado = None
    if con_sell_out:
        estimado = any(p.sell_out_estimado for p in con_sell_out)
        if not any(p.sell_out_ars is None for p in con_sell_out):
            sell_out_ars = sum((p.sell_out_ars for p in con_sell_out), Decimal(0))
    return MontosVenta(
        sell_in_ars=sum(sell_in, Decimal(0)) if sell_in else None,
        sell_out_ars=sell_out_ars,
        sell_out_estimado=estimado,
    )
