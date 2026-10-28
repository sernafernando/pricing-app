"""Sell in and sell out of a product TODAY, for the Productos screens (sell-in-sell-out T9).

Owner rule: "Always show both: cost and cost with sell in; markup and totals
without and with sell out." Display-only: nothing here is stored, and the
existing cost and markup fields are never touched.

- Sell in (option A, `SellInCosting.vigentes`): the purchase line the next sale
  would consume, FIFO, with the units the stored consumptions left. Its
  discount per unit is in ARS (a USD purchase at its own rate). A product whose
  lines are used up has none: its cost is back to normal.
- Sell out: the active campaigns reaching the product today whose cap is not
  used up (units or money left after the allocator's `sell_out_consumos`),
  taken in id order with the allocator's precedence (a non-`acumulable`
  campaign does not stack with an earlier one), credited per unit by
  `asignacion.credito_unitario` (with the product's own amount in the
  campaign, when it has one, T22b) and turned into ARS at the campaign's rate.
  With money left under the unit credit, the unit gets what is left, as
  `tope.asignar` would. A percentage base is, per unit, the product's current
  cost in ARS (`costo`) or its ML list price without VAT (`precio_neto`). A
  missing rate, VAT rate or base leaves the amount unknown (None), never a
  partial sum.

Markups (`SellInOutMarkups`, recorded at every site that records the PPP ones,
same keys and scale): with sell in, `limpio` over the cost with sell in; with
sell in + sell out, `limpio + sell out` over the cost with sell in, or the plain
cost when there is no sell in.

Batch: `resolver_sell_in_out_batch` reads a whole page in at most six queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutCampanaItem, SellOutConsumo
from app.schemas.sell_in_out_producto import SellInOutProducto, SellInProducto, SellOutProducto
from app.services.pricing_calculator import calcular_markup, convertir_a_pesos
from app.services.sell_in.bonos import tasas_bna_por_fecha
from app.services.sell_in.costing import LoteVigente, get_costing
from app.services.sell_out import alcance, asignacion
from app.services.sell_out.tope import cents


@dataclass(frozen=True)
class _Campana:
    campana: SellOutCampana
    monto_libre: Optional[Decimal]  # money cap left, campaign currency; None: no money cap
    montos_item: Dict[int, Decimal]  # item_id -> its own amount per unit in the campaign (T22b)


class SellInOutMarkups:
    """Per-product accumulator, the `PppMarkups` interface: `.record()` per markup site, `.payload()`."""

    def __init__(self, sell_in: Optional[SellInProducto], sell_out: Optional[SellOutProducto], costo: Optional[float]):
        self._sell_in = sell_in
        self._sell_out = sell_out
        self._costo_sell_in = sell_in.costo if sell_in else None
        self._costo_sell_out = self._costo_sell_in if sell_in else costo
        self._credito = sell_out.monto_unit if sell_out else None
        self._markups_sell_in: Dict[str, float] = {}
        self._markups_sell_in_out: Dict[str, float] = {}

    @staticmethod
    def _escala(raw: float, percent: bool) -> float:
        return round(raw * 100, 2) if percent else raw

    def record(self, key: str, limpio: float, *, percent: bool = True) -> None:
        if self._costo_sell_in is not None:
            self._markups_sell_in[key] = self._escala(calcular_markup(limpio, self._costo_sell_in), percent)
        if self._credito is not None and self._costo_sell_out is not None:
            raw = calcular_markup(limpio + self._credito, self._costo_sell_out)
            self._markups_sell_in_out[key] = self._escala(raw, percent)

    def payload(self) -> Optional[SellInOutProducto]:
        if self._sell_in is None and self._sell_out is None:
            return None
        return SellInOutProducto(
            sell_in=self._sell_in,
            sell_out=self._sell_out,
            markups_sell_in=dict(self._markups_sell_in),
            markups_sell_in_out=dict(self._markups_sell_in_out),
        )


class MarkupCompanions:
    """Records each markup site once into the PPP and the sell in / sell out accumulators."""

    def __init__(self, ppp, sell_in_out: SellInOutMarkups):
        self.ppp = ppp
        self.sell_in_out = sell_in_out

    def record(self, key: str, limpio: float, *, percent: bool = True) -> None:
        self.ppp.record(key, limpio, percent=percent)
        self.sell_in_out.record(key, limpio, percent=percent)


@dataclass(frozen=True)
class SellInOutBatch:
    hoy: date
    sell_in: Dict[int, LoteVigente]
    campanas: Dict[int, List[_Campana]]  # item_id -> campaigns with cap left, in id order
    bna: Optional[Decimal]

    def markups(self, producto, *, precio_lista_ml=None, tipo_cambio: Optional[float] = None) -> SellInOutMarkups:
        """`producto` is a `ProductoERP`; `tipo_cambio` the USD rate its cost converts at, as `PppMarkups`."""
        moneda = getattr(producto.moneda_costo, "value", producto.moneda_costo) or "ARS"
        costo = None
        if producto.costo is not None and (moneda == "ARS" or tipo_cambio):
            costo = float(convertir_a_pesos(producto.costo, moneda, tipo_cambio))
        lote = self.sell_in.get(producto.item_id)
        sell_in = None
        if lote is not None:
            sell_in = SellInProducto(
                compra_item_id=lote.compra_item_id,
                descuento_unit=float(lote.descuento_unit_ars),
                costo=None if costo is None else float(Decimal(str(costo)) - lote.descuento_unit_ars),
                unidades_restantes=lote.unidades_restantes,
            )
        iva = Decimal(str(producto.iva)) if producto.iva is not None else None
        neto = None
        if precio_lista_ml and iva is not None:
            neto = Decimal(str(precio_lista_ml)) / (1 + iva / 100)
        base = {"costo": None if costo is None else Decimal(str(costo)), "precio_neto": neto}
        sell_out = self._sell_out(producto.item_id, self.campanas.get(producto.item_id, []), iva, base)
        return SellInOutMarkups(sell_in, sell_out, costo)

    def _sell_out(
        self, item_id: int, campanas: List[_Campana], iva: Optional[Decimal], base: dict
    ) -> Optional[SellOutProducto]:
        tomadas: List[SellOutCampana] = []
        total: Optional[Decimal] = Decimal(0)
        for x in campanas:
            c = x.campana
            if any(not (p.acumulable and c.acumulable) for p in tomadas):
                continue  # an earlier non-stackable campaign holds the unit (asignacion module docstring)
            tomadas.append(c)
            try:
                credito = asignacion.credito_unitario(
                    c, self.hoy, iva, base.get(c.base_porcentaje), self.bna, monto_item=x.montos_item.get(item_id)
                )
            except asignacion.SellOutAsignacionError:
                credito = None
            if credito is None or total is None:
                total = None
                continue
            unitario, tasa = credito
            monto = cents(unitario) if x.monto_libre is None else min(cents(unitario), x.monto_libre)
            total += monto if c.moneda == "ARS" else cents(monto * tasa)
        if not tomadas:
            return None
        return SellOutProducto(monto_unit=None if total is None else float(total), campana_ids=[c.id for c in tomadas])


def resolver_sell_in_out_batch(db: Session, item_ids: Iterable[int], hoy: date) -> SellInOutBatch:
    """What `hoy`'s next sale of each product would get (module docstring), for a whole page."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    sell_in = get_costing().vigentes(db, ids, hoy)
    por_item = alcance.campanas_por_item(db, {(i, hoy) for i in ids})
    cids = sorted(set().union(*por_item.values()))
    vigentes: Dict[int, _Campana] = {}
    bna = None
    if cids:
        t = SellOutConsumo
        usado = {
            cid: (int(unidades or 0), Decimal(monto or 0))
            for cid, unidades, monto in db.query(t.campana_id, func.sum(t.unidades), func.sum(t.monto))
            .filter(t.campana_id.in_(cids))
            .group_by(t.campana_id)
        }
        # Each campaign with this page's products' own amounts in it (T22b), in the same query.
        i = SellOutCampanaItem
        filas = db.query(SellOutCampana, i.item_id, i.monto_unit).outerjoin(
            i, and_(i.campana_id == SellOutCampana.id, i.item_id.in_(ids))
        )
        agotadas = set()
        for c, item_id, monto_item in filas.filter(SellOutCampana.id.in_(cids)):
            if c.id not in vigentes and c.id not in agotadas:
                unidades, monto = usado.get(c.id, (0, Decimal(0)))
                libre = None if c.tope_monto is None else Decimal(c.tope_monto) - monto
                if (c.tope_unidades is not None and c.tope_unidades <= unidades) or (libre is not None and libre <= 0):
                    agotadas.add(c.id)  # the cap is used up: this campaign credits nothing more
                    continue
                vigentes[c.id] = _Campana(c, libre, {})
            if c.id in vigentes and item_id is not None:
                vigentes[c.id].montos_item[item_id] = Decimal(monto_item)
        if any(x.campana.moneda == "USD" for x in vigentes.values()):
            bna = tasas_bna_por_fecha(db, {hoy})[hoy]
    campanas = {item: [vigentes[c] for c in sorted(cs) if c in vigentes] for item, cs in por_item.items()}
    return SellInOutBatch(hoy, sell_in, campanas, bna)
