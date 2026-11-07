"""Sell in and sell out of a product TODAY, for the Productos screens (sell-in-sell-out T9).

Owner rule: "Always show both: cost and cost with sell in; markup and totals
without and with sell out." Display-only: nothing here is stored, and the
existing cost and markup fields are never touched.

- Sell in (option A, `SellInCosting.vigentes`): the purchase line the next sale
  would consume, FIFO, with the units the stored consumptions left. Its
  discount per unit is in ARS (a USD purchase at its own rate). A product whose
  lines are used up has none: its cost is back to normal.
- Sell in from a % of cost bonus (T25, S31): only when no lot has units left
  (rule 5, exclusive per unit: the next sale takes FIFO units first). The
  active `costo_venta` bonuses reaching the product today whose cap is not
  used up (after `sell_in_bono_consumos`), in id order, each giving its % (the
  model's own one, when set) of the product's current cost in ARS (`costo`),
  or its ARS amount per unit on a `por_unidad` bonus (tacticals T1),
  divided by (1 + the product's VAT rate) when loaded with VAT
  (`bonos_costo.unitario`, the allocator's rule); they stack up to the cost,
  with the allocator's precedence (T27b: a bonus does not stack with an
  earlier one that gave something when either is not `acumulable`),
  and a money cap with less left than the unit amount gives what is left. A
  cost without an ARS value, or a VAT-loaded bonus on a product without a VAT
  rate (the allocator refuses it too), leaves no sell in, never a guess.
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

Batch: `resolver_sell_in_out_batch` reads a whole page in at most nine queries:
seven for FIFO and sell out (the cost bonuses' scope rides on the campaigns'
query; one reads the products' cost modes), one more for the stored
consumptions only when a product has cost modes, and one for the reached cost
bonuses' rows and caps, only when a product without a lot has one.

Store scope (`contextos`): when the caller passes `(canal, store_id)` pairs, tactical
campaigns/bonuses are filtered with `tienda_scope.alcanza_alguno` (union) and
per-target caps (`tope_compartido=false`) stay active while any matching context
still has room. `contextos=None` is the pre-scope global read (Productos "Todas").
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import Numeric, and_, case, cast, func, literal, null, or_, select, true, union_all
from sqlalchemy.orm import Session, selectinload

from app.models.ml_sale_line import MlSaleLine
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoConsumo, SellInBonoItem, SellInBonoMarca
from app.models.sell_out import SellOutCampana, SellOutCampanaItem, SellOutConsumo
from app.models.tactical import Tactical
from app.schemas.sell_in_out_producto import SellInOutProducto, SellInProducto, SellOutProducto
from app.services.pricing_calculator import calcular_markup, convertir_a_pesos
from app.services.sell_in import bonos_costo
from app.services.sell_in.bonos import tasas_bna_por_fecha
from app.services.sell_in.costing import LoteVigente, get_costing
from app.services.sell_out import alcance, asignacion
from app.services.sell_out.tienda_scope import (
    Scope,
    TargetKey,
    alcanza,
    alcanza_alguno,
    scope_desde_tactical,
    target_key,
)
from app.services.sell_out.tope import cents

# (canal, store_id) the operator is pricing against; None on the batch = Todas / global (pre-scope).
ContextoMarkup = Tuple[str, Optional[int]]


@dataclass(frozen=True)
class _Campana:
    campana: SellOutCampana
    monto_libre: Optional[Decimal]  # money cap left, campaign currency; None: no money cap
    montos_item: Dict[int, Decimal]  # item_id -> its own amount per unit in the campaign (T22b)


@dataclass(frozen=True)
class _BonoCosto:
    bono: SellInBonoMarca
    valor: Decimal  # the product's own % (or ARS per unit) in the bonus, or the bonus's
    monto_libre: Optional[Decimal]  # ARS cap left; None: no money cap


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
    bonos_costo: Dict[int, List[_BonoCosto]] = field(default_factory=dict)  # item_id -> cost bonuses, id order

    def markups(self, producto, *, precio_lista_ml=None, tipo_cambio: Optional[float] = None) -> SellInOutMarkups:
        """`producto` is a `ProductoERP`; `tipo_cambio` the USD rate its cost converts at, as `PppMarkups`."""
        moneda = getattr(producto.moneda_costo, "value", producto.moneda_costo) or "ARS"
        costo = None
        if producto.costo is not None and (moneda == "ARS" or tipo_cambio):
            costo = float(convertir_a_pesos(producto.costo, moneda, tipo_cambio))
        lote = self.sell_in.get(producto.item_id)
        iva = Decimal(str(producto.iva)) if producto.iva is not None else None
        sell_in = None
        if lote is not None:
            sell_in = SellInProducto(
                compra_item_id=lote.compra_item_id,
                descuento_unit=float(lote.descuento_unit_ars),
                costo=None if costo is None else float(Decimal(str(costo)) - lote.descuento_unit_ars),
                unidades_restantes=lote.unidades_restantes,
            )
        elif costo is not None:
            sell_in = self._sell_in_costo(producto.item_id, Decimal(str(costo)), iva)
        neto = None
        if precio_lista_ml and iva is not None:
            neto = Decimal(str(precio_lista_ml)) / (1 + iva / 100)
        base = {"costo": None if costo is None else Decimal(str(costo)), "precio_neto": neto}
        sell_out = self._sell_out(producto.item_id, self.campanas.get(producto.item_id, []), iva, base)
        return SellInOutMarkups(sell_in, sell_out, costo)

    def _sell_in_costo(self, item_id: int, costo: Decimal, iva: Optional[Decimal]) -> Optional[SellInProducto]:
        """The cost bonuses' sell in of the next unit (module docstring), None when none gives anything."""
        total, tomados = Decimal(0), []
        for x in self.bonos_costo.get(item_id, []):
            if any(not (p.acumulable and x.bono.acumulable) for p in tomados):
                continue  # an earlier bonus it does not stack with holds the unit (`bonos_costo`, T27b)
            try:
                monto = bonos_costo.unitario(x.bono, x.valor, costo, item_id, iva, self.hoy)
            except ValueError:
                # A VAT-loaded bonus on a product without a VAT rate: the allocator (`bonos_costo.recalcular`) fails
                # the product's whole component, every cost bonus of it, so none is shown either.
                return None
            unitario = min(monto, costo - total)
            if unitario <= 0:
                continue
            total += cents(unitario) if x.monto_libre is None else min(cents(unitario), x.monto_libre)
            tomados.append(x.bono)
        if not tomados:
            return None
        ids = [b.id for b in tomados]
        return SellInProducto(bono_id=ids[0], bono_ids=ids, descuento_unit=float(total), costo=float(costo - total))

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


def resolver_sell_in_out_batch(
    db: Session,
    item_ids: Iterable[int],
    hoy: date,
    *,
    sin_lotes: bool = False,
    contextos: Optional[Sequence[ContextoMarkup]] = None,
) -> SellInOutBatch:
    """What `hoy`'s next sale of each product would get (module docstring), for a whole page. `sin_lotes` resolves it
    as if no FIFO lot had units left (what applies once they run out: the lot viewer's question).

    `contextos`: optional (canal, store_id) selection the operator is pricing against. `None` keeps the pre-scope
    global read (Productos "Todas"). A non-empty list is a **union**: a tactical campaign/bonus is included when it
    reaches any context (`tienda_scope.alcanza_alguno`); per-target caps (`tope_compartido=false`) stay active while
    any matching context still has room.
    """
    ids = sorted({int(i) for i in item_ids if i is not None})
    sell_in = {} if sin_lotes else get_costing().vigentes(db, ids, hoy)
    por_item, pares = _campanas_y_bonos(db, ids, [i for i in ids if i not in sell_in], hoy)
    cids = sorted(set().union(*por_item.values())) if por_item else []
    vigentes: Dict[int, _Campana] = {}
    bna = None
    if cids:
        t = SellOutConsumo
        usado_global = {
            cid: (int(unidades or 0), Decimal(monto or 0))
            for cid, unidades, monto in db.query(t.campana_id, func.sum(t.unidades), func.sum(t.monto))
            .filter(t.campana_id.in_(cids))
            .group_by(t.campana_id)
        }
        # Each campaign with this page's products' own amounts in it (T22b), in the same query.
        i = SellOutCampanaItem
        filas = list(
            db.query(SellOutCampana, i.item_id, i.monto_unit)
            .outerjoin(i, and_(i.campana_id == SellOutCampana.id, i.item_id.in_(ids)))
            .filter(SellOutCampana.id.in_(cids))
        )
        campanas_obj = {c.id: c for c, _, _ in filas}
        scopes = _scopes_campanas(db, list(campanas_obj.values()))
        need_por_target = contextos is not None and any(
            scopes.get(cid) is not None and not scopes[cid].tope_compartido for cid in cids
        )
        usado_por_target = _uso_sell_out_por_target(db, cids) if need_por_target else {}
        agotadas = set()
        for c, item_id, monto_item in filas:
            if c.id not in vigentes and c.id not in agotadas:
                scope = scopes.get(c.id)
                if contextos is not None and not alcanza_alguno(scope, contextos):
                    agotadas.add(c.id)
                    continue
                activa, libre = _cap_campana(
                    c, scope, contextos, usado_global.get(c.id, (0, Decimal(0))), usado_por_target.get(c.id, {})
                )
                if not activa:
                    agotadas.add(c.id)  # the cap is used up: this campaign credits nothing more
                    continue
                vigentes[c.id] = _Campana(c, libre, {})
            if c.id in vigentes and item_id is not None:
                vigentes[c.id].montos_item[item_id] = Decimal(monto_item)
        if any(x.campana.moneda == "USD" for x in vigentes.values()):
            bna = tasas_bna_por_fecha(db, {hoy})[hoy]
    campanas = {item: [vigentes[c] for c in sorted(cs) if c in vigentes] for item, cs in por_item.items()}
    return SellInOutBatch(hoy, sell_in, campanas, bna, _bonos_costo(db, pares, contextos=contextos))


_Par = Tuple[int, int, Optional[Decimal]]  # (bono_id, item_id, the product's own % or ARS per unit, or None)


def _campanas_y_bonos(db: Session, ids: List[int], sin_lote: List[int], hoy: date):
    """`(alcance.campanas_por_item of hoy, the (cost bonus, product) pairs of the products without a lot)` in ONE
    query: the cost bonuses ride on the campaigns' (a UNION ALL), so a page with none active costs nothing more.
    A pair is an active `costo_venta` bonus current on `hoy` reaching the product by the panel's scope rule
    (`bonos_alcance.del_alcance`: brand, category, or a model listed in `sell_in_bono_items`; a NULL brand or
    category matches nothing), set-based."""
    ventas = {(i, hoy) for i in ids}
    if not ventas:
        return {}, []
    campanas = alcance.consulta_campanas_por_item(db, ventas)
    if not sin_lote:
        return alcance.campanas_de_filas(campanas, ventas), []
    b, i, p = SellInBonoMarca, SellInBonoItem, ProductoERP
    bonos = (
        # A model's own value of the bonus's kind, picked like the allocator (`bonos_costo.recalcular`).
        select(
            b.id,
            p.item_id,
            b.fecha_desde,
            b.fecha_hasta,
            literal("bono"),
            case((b.tipo == "por_unidad", i.monto_unit), else_=i.porcentaje),
        )
        .select_from(p)
        .join(b, true())
        .outerjoin(i, and_(i.bono_id == b.id, i.item_id == p.item_id))
        .where(
            p.item_id.in_(sin_lote),
            b.base == bonos_costo.BASE,
            b.estado == "activa",
            b.fecha_desde <= hoy,
            b.fecha_hasta >= hoy,
            or_(
                and_(b.alcance == "marca", b.marca == p.marca),
                and_(b.alcance == "categoria", b.categoria == p.categoria),
                and_(b.alcance == "modelos", i.item_id.isnot(None)),
            ),
        )
    )
    filas = db.execute(
        union_all(campanas.add_columns(literal("campana"), cast(null(), Numeric)).statement, bonos)
    ).all()
    pares = [(int(r[0]), int(r[1]), r[5]) for r in filas if r[4] == "bono"]
    return alcance.campanas_de_filas([r[:4] for r in filas if r[4] == "campana"], ventas), pares


def _bonos_costo(
    db: Session, pares: List[_Par], *, contextos: Optional[Sequence[ContextoMarkup]] = None
) -> Dict[int, List[_BonoCosto]]:
    """`{item_id: cost bonuses}` from the (bonus, product) pairs, in id order, without the bonuses whose cap is used
    up (after `sell_in_bono_consumos`). One query, only when there is a pair. Same store-scope rules as sell-out."""
    if not pares:
        return {}
    bids = sorted({bid for bid, _, _ in pares})
    t = SellInBonoConsumo
    usado_global = {
        bid: (int(unidades or 0), Decimal(monto or 0))
        for bid, unidades, monto in db.query(t.bono_id, func.sum(t.unidades), func.sum(t.descuento_ars))
        .filter(t.bono_id.in_(bids))
        .group_by(t.bono_id)
    }
    bonos = {b.id: b for b in db.query(SellInBonoMarca).filter(SellInBonoMarca.id.in_(bids))}
    scopes = _scopes_bonos(db, list(bonos.values()))
    need_por_target = contextos is not None and any(
        scopes.get(bid) is not None and not scopes[bid].tope_compartido for bid in bids
    )
    usado_por_target = _uso_bono_por_target(db, bids) if need_por_target else {}
    activos: Dict[int, Tuple[SellInBonoMarca, Optional[Decimal]]] = {}  # bono_id -> (bonus, ARS cap left)
    for bid, bono in bonos.items():
        scope = scopes.get(bid)
        if contextos is not None and not alcanza_alguno(scope, contextos):
            continue
        activa, libre = _cap_bono(
            bono, scope, contextos, usado_global.get(bid, (0, Decimal(0))), usado_por_target.get(bid, {})
        )
        if not activa:
            continue  # the cap is used up: this bonus discounts nothing more
        activos[bid] = (bono, libre)
    salida: Dict[int, List[_BonoCosto]] = {}
    for bid, item_id, propio in sorted(pares, key=lambda x: (x[1], x[0])):
        if bid in activos:
            bono, libre = activos[bid]
            salida.setdefault(item_id, []).append(_BonoCosto(bono, bonos_costo.valor_del_bono(bono, propio), libre))
    return salida


def _scopes_campanas(db: Session, campanas: List[SellOutCampana]) -> Dict[int, Optional[Scope]]:
    ids = {c.tactical_id for c in campanas if c.tactical_id is not None}
    if not ids:
        return {c.id: None for c in campanas}
    tacticals = {
        t.id: t for t in db.query(Tactical).options(selectinload(Tactical.tiendas)).filter(Tactical.id.in_(ids))
    }
    return {
        c.id: (scope_desde_tactical(tacticals[c.tactical_id]) if c.tactical_id in tacticals else None) for c in campanas
    }


def _scopes_bonos(db: Session, bonos: List[SellInBonoMarca]) -> Dict[int, Optional[Scope]]:
    ids = {b.tactical_id for b in bonos if b.tactical_id is not None}
    if not ids:
        return {b.id: None for b in bonos}
    tacticals = {
        t.id: t for t in db.query(Tactical).options(selectinload(Tactical.tiendas)).filter(Tactical.id.in_(ids))
    }
    return {
        b.id: (scope_desde_tactical(tacticals[b.tactical_id]) if b.tactical_id in tacticals else None) for b in bonos
    }


def _cap_campana(
    c: SellOutCampana,
    scope: Optional[Scope],
    contextos: Optional[Sequence[ContextoMarkup]],
    usado_global: Tuple[int, Decimal],
    usado_target: Dict[TargetKey, Tuple[int, Decimal]],
) -> Tuple[bool, Optional[Decimal]]:
    """Whether the campaign still credits a next unit under `contextos`, and the money left to show."""
    return _cap_restante(
        tope_unidades=c.tope_unidades,
        tope_monto=None if c.tope_monto is None else Decimal(c.tope_monto),
        scope=scope,
        contextos=contextos,
        usado_global=usado_global,
        usado_target=usado_target,
    )


def _cap_bono(
    bono: SellInBonoMarca,
    scope: Optional[Scope],
    contextos: Optional[Sequence[ContextoMarkup]],
    usado_global: Tuple[int, Decimal],
    usado_target: Dict[TargetKey, Tuple[int, Decimal]],
) -> Tuple[bool, Optional[Decimal]]:
    return _cap_restante(
        tope_unidades=bono.tope_unidades,
        tope_monto=None if bono.tope_monto is None else Decimal(bono.tope_monto),
        scope=scope,
        contextos=contextos,
        usado_global=usado_global,
        usado_target=usado_target,
    )


def _cap_restante(
    *,
    tope_unidades: Optional[int],
    tope_monto: Optional[Decimal],
    scope: Optional[Scope],
    contextos: Optional[Sequence[ContextoMarkup]],
    usado_global: Tuple[int, Decimal],
    usado_target: Dict[TargetKey, Tuple[int, Decimal]],
) -> Tuple[bool, Optional[Decimal]]:
    """Shared / global pool, or per-target: active while any matching context still has room."""

    def _desde(unidades: int, monto: Decimal) -> Tuple[bool, Optional[Decimal]]:
        libre = None if tope_monto is None else tope_monto - monto
        if (tope_unidades is not None and tope_unidades <= unidades) or (libre is not None and libre <= 0):
            return False, libre
        return True, libre

    if contextos is None or scope is None or scope.tope_compartido:
        return _desde(*usado_global)

    matching = [(canal, store_id) for canal, store_id in contextos if alcanza(scope, canal, store_id)]
    if not matching:
        return False, None if tope_monto is None else Decimal(0)
    mejores: List[Tuple[bool, Optional[Decimal]]] = []
    for canal, store_id in matching:
        key = target_key(canal, store_id)
        if key is None:
            continue
        mejores.append(_desde(*usado_target.get(key, (0, Decimal(0)))))
    activas = [m for m in mejores if m[0]]
    if not activas:
        return False, None if tope_monto is None else Decimal(0)
    libres = [m[1] for m in activas if m[1] is not None]
    return True, (max(libres) if libres else None)


def _uso_sell_out_por_target(
    db: Session, campana_ids: List[int]
) -> Dict[int, Dict[TargetKey, Tuple[int, Decimal]]]:
    """Units/money already taken per campaign and store/channel target (for per-target caps)."""
    if not campana_ids:
        return {}
    t = SellOutConsumo
    rows = db.query(t.campana_id, t.canal, t.venta_ref, t.unidades, t.monto).filter(t.campana_id.in_(campana_ids))
    return _agrupar_uso_por_target(db, rows)


def _uso_bono_por_target(db: Session, bono_ids: List[int]) -> Dict[int, Dict[TargetKey, Tuple[int, Decimal]]]:
    if not bono_ids:
        return {}
    t = SellInBonoConsumo
    rows = db.query(t.bono_id, t.canal, t.venta_ref, t.unidades, t.descuento_ars).filter(t.bono_id.in_(bono_ids))
    return _agrupar_uso_por_target(db, rows)


def _agrupar_uso_por_target(
    db: Session, rows: Iterable[Tuple[int, str, int, object, object]]
) -> Dict[int, Dict[TargetKey, Tuple[int, Decimal]]]:
    filas = list(rows)
    ml_refs = {int(ref) for _, canal, ref, _, _ in filas if canal == "ml"}
    stores_por_ref: Dict[int, Optional[int]] = {}
    if ml_refs:
        mla_por_ref = {
            int(ref): mla for ref, mla in db.query(MlSaleLine.item_row_id, MlSaleLine.mla).filter(MlSaleLine.item_row_id.in_(ml_refs))
        }
        stores = alcance._stores_por_mla(db, {m for m in mla_por_ref.values() if m})
        stores_por_ref = {ref: stores.get(mla) for ref, mla in mla_por_ref.items()}
    salida: Dict[int, Dict[TargetKey, Tuple[int, Decimal]]] = defaultdict(lambda: defaultdict(lambda: (0, Decimal(0))))
    for oid, canal, ref, unidades, monto in filas:
        store_id = stores_por_ref.get(int(ref)) if canal == "ml" else None
        key = target_key(canal, store_id)
        if key is None:
            continue
        u0, m0 = salida[int(oid)][key]
        salida[int(oid)][key] = (u0 + int(unidades or 0), m0 + Decimal(monto or 0))
    return {oid: dict(targets) for oid, targets in salida.items()}
