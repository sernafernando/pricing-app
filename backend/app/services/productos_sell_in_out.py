"""Sell out of a product TODAY, for the Productos screens (sell-in-sell-out T9; costo SI T5 PR B).

Display-only: nothing here is stored, and the existing cost and markup fields are never touched. There is no sell in
part any more: costo SI replaced the FIFO lots and the per-sale cost bonuses (owner L24: no per-sale loyalty ever), so
a product's sell in is already inside its costo SI, and the screens show only the sell out ("c/ SO").

- Sell out: the active campaigns reaching the product today whose cap is not
  used up (units or money left after the allocator's `sell_out_consumos`),
  taken in id order with the allocator's precedence (a non-`acumulable`
  campaign does not stack with an earlier one), credited per unit by
  `asignacion.credito_unitario` (with the product's own amount in the
  campaign, when it has one, T22b) and turned into ARS at the campaign's rate.
  With money left under the unit credit, the unit gets what is left, as
  `tope.asignar` would. A percentage base is, per unit, the product's current
  costo SI in ARS (`costo`, Q7) or its ML list price without VAT (`precio_neto`). A
  missing rate, VAT rate or base leaves the amount unknown (None), never a
  partial sum.

Markups (`SellInOutMarkups`, recorded at every site that records the PPP ones,
same keys and scale): with sell out, `costo_si.so.markup_con_so` = (limpio +
sell out - cost) / cost, where the cost is the product's costo SI in pesos
(`costo_si.lote.actuales`; its list cost when it has no costo SI step). D1 (owner
L12): "el costo siso no existe, es costo SI y SO va en la venta, como ganancia
adicional": there is no "with sell in" markup (`markups_sell_in` stays empty).
Productos, Tienda, the Publicaciones ML panel and the promos all price on this one
cost and formula (sell-in-costo-si T3 PR 5), whatever cost the caller's product
carries.

Batch: `resolver_sell_in_out_batch` reads a whole page in at most five queries: the
campaigns reaching its products, and only when there is one, their consumptions and
their rows (with the products' own amounts), plus today's BNA rate only when one is
in USD; and one for the products' costo SI (`costo_si.lote.actuales`, the cost of
every markup) unless the caller already read it. A store context adds the
campaigns' scopes and, with a per-target cap, their use per store.

Store scope (`contextos`): when the caller passes `(canal, store_id)` pairs, tactical
sell out campaigns are filtered with `tienda_scope.alcanza_alguno` (union) and
per-target caps (`tope_compartido=false`) stay active while any matching context
still has room. `contextos=None` is the pre-scope global read (Productos "Todas").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Hashable, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutCampanaItem, SellOutConsumo
from app.schemas.sell_in_out_producto import SellInOutProducto, SellOutProducto
from app.services.costo_si import lote as costo_si_lote, so
from app.services.pricing_calculator import convertir_a_pesos, moneda_de
from app.services.sell_in.bonos import tasas_bna_por_fecha
from app.services.sell_out import alcance, asignacion
from app.services.sell_out.tienda_scope import (
    Scope,
    TargetKey,
    alcanza,
    alcanza_alguno,
    scopes_de,
    target_key,
    usado_por_contador,
)
from app.services.sell_out.tope import cents

# (canal, store_id) the operator is pricing against; None on the batch = Todas / global (pre-scope).
ContextoMarkup = Tuple[str, Optional[int]]


def parse_contextos_query(raw: Optional[str]) -> Optional[List[ContextoMarkup]]:
    """CSV from Productos `markup_contextos`: `ml:<store_id>`, `fuera`, `tn`. Empty / `todas` / None → global."""
    if raw is None:
        return None
    texto = raw.strip()
    if not texto or texto.lower() == "todas":
        return None
    salida: List[ContextoMarkup] = []
    for token in texto.split(","):
        tok = token.strip()
        if not tok:
            continue
        if tok in ("fuera", "tn"):
            salida.append((tok, None))
            continue
        if tok.startswith("ml:"):
            try:
                salida.append(("ml", int(tok[3:])))
            except ValueError as exc:
                raise ValueError(f"markup_contextos store id inválido: {tok}") from exc
            continue
        raise ValueError(f"markup_contextos token inválido: {tok}")
    return salida or None


@dataclass(frozen=True)
class _Campana:
    campana: SellOutCampana
    monto_libre: Optional[Decimal]  # money cap left, campaign currency; None: no money cap
    montos_item: Dict[int, Decimal]  # item_id -> its own amount per unit in the campaign (T22b)


class SellInOutMarkups:
    """Per-product accumulator, the `PppMarkups` interface: `.record()` per markup site, `.payload()`."""

    def __init__(self, sell_out: Optional[SellOutProducto], costo: Optional[float]):
        """`costo`: the product's costo SI in pesos (None when unknown)."""
        self._sell_out = sell_out
        self._costo = costo
        self._credito = sell_out.monto_unit if sell_out else None
        self._markups_sell_in: Dict[str, float] = {}  # D1: never filled (no markup "with sell in"); the key stays
        self._markups_sell_in_out: Dict[str, float] = {}

    @staticmethod
    def _escala(raw: float, percent: bool) -> float:
        return round(raw * 100, 2) if percent else raw

    def record(self, key: str, limpio: float, *, percent: bool = True) -> None:
        """The markup with sell out at `limpio` (D1, `so.markup_con_so`); nothing without a known sell out or cost."""
        if self._credito is None or self._costo is None:
            return
        raw = so.markup_con_so(float(limpio), float(self._credito), float(self._costo))
        if raw is not None:
            self._markups_sell_in_out[key] = self._escala(raw, percent)

    def payload(self) -> Optional[SellInOutProducto]:
        if self._sell_out is None:
            return None
        return SellInOutProducto(
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
    campanas: Dict[int, List[_Campana]]  # item_id -> campaigns with cap left, in id order
    bna: Optional[Decimal]
    costos: Dict[int, costo_si_lote.Costo] = field(
        default_factory=dict
    )  # item_id -> its current costo SI (`lote.actuales`)

    def markups(self, producto, *, precio_lista_ml=None, tipo_cambio: Optional[float] = None) -> SellInOutMarkups:
        """`producto` is a `ProductoERP`; `tipo_cambio` the USD rate its cost converts at, as `PppMarkups`. The cost
        is the product's costo SI in pesos when the batch resolved it (every product it was asked for), else the
        product's own cost (a product outside the batch)."""
        moneda = moneda_de(producto.moneda_costo)
        costo = None
        resuelto = self.costos.get(producto.item_id)
        if resuelto is not None:
            # the caller's rate when it gives one (the rest of its screen converts at it), else the batch's latest
            en_pesos = costo_si_lote.en_pesos(resuelto.costo, resuelto.moneda, tipo_cambio) if tipo_cambio else None
            en_pesos = en_pesos if en_pesos is not None else resuelto.costo_ars
            costo = None if en_pesos is None else float(en_pesos)
        elif producto.costo is not None and (moneda == "ARS" or tipo_cambio):
            costo = float(convertir_a_pesos(producto.costo, moneda, tipo_cambio))
        iva = Decimal(str(producto.iva)) if producto.iva is not None else None
        neto = None
        if precio_lista_ml and iva is not None:
            neto = Decimal(str(precio_lista_ml)) / (1 + iva / 100)
        base = {"costo": None if costo is None else Decimal(str(costo)), "precio_neto": neto}
        sell_out = self._sell_out(producto.item_id, self.campanas.get(producto.item_id, []), iva, base)
        return SellInOutMarkups(sell_out, costo)

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
    contextos: Optional[Sequence[ContextoMarkup]] = None,
    costos: Optional[Mapping[int, costo_si_lote.Costo]] = None,
) -> SellInOutBatch:
    """What `hoy`'s next sale of each product would get (module docstring), for a whole page.

    `contextos`: optional (canal, store_id) selection the operator is pricing against. `None` keeps the pre-scope
    global read (Productos "Todas"). A non-empty list is a **union**: a tactical sell out campaign is included when it
    reaches any context (`tienda_scope.alcanza_alguno`); per-target caps (`tope_compartido=false`) stay active while
    any matching context still has room.

    `costos`: the page's `lote.actuales` when the caller already read them (Productos' live markups and costo SI
    column), so the page reads its costs once; None reads them here.
    """
    return resolver_sell_in_out_por_contexto(db, item_ids, hoy, {None: contextos}, costos=costos)[None]


def resolver_sell_in_out_por_contexto(
    db: Session,
    item_ids: Iterable[int],
    hoy: date,
    contextos_por_clave: Mapping[Hashable, Optional[Sequence[ContextoMarkup]]],
    *,
    costos: Optional[Mapping[int, costo_si_lote.Costo]] = None,
) -> Dict[Hashable, SellInOutBatch]:
    """`resolver_sell_in_out_batch` for several store contexts at once (one per key, e.g. each official store of a
    Publicaciones page): the database is read ONCE for every key, and only the scope and cap rules run per key."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    con_scope = any(c is not None for c in contextos_por_clave.values())
    por_item = alcance.campanas_por_item(db, {(i, hoy) for i in ids})
    cids = sorted(set().union(*por_item.values())) if por_item else []
    filas: list = []
    usado_global: Dict[int, Tuple[int, Decimal]] = {}
    scopes: Dict[int, Optional[Scope]] = {}
    usado_por_target: Dict[int, Dict[TargetKey, Tuple[int, Decimal]]] = {}
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
        # Scopes only when a key asked for a store context — keeps the global query count.
        if con_scope:
            scopes = scopes_de(db, list({c.id: c for c, _, _ in filas}.values()))
            if any(s is not None and not s.tope_compartido for s in scopes.values()):
                usado_por_target = _uso_sell_out_por_target(db, cids)
    campanas_por_clave = {
        clave: _campanas_vigentes(filas, por_item, contextos, scopes, usado_global, usado_por_target)
        for clave, contextos in contextos_por_clave.items()
    }
    bna = None
    if any(x.campana.moneda == "USD" for cs in campanas_por_clave.values() for c in cs.values() for x in c):
        bna = tasas_bna_por_fecha(db, {hoy})[hoy]
    if costos is None:
        costos = costo_si_lote.actuales(db, ids)  # the one cost of every markup here (D1, S13)
    else:
        costos = {i: costos[i] for i in ids if i in costos}  # the caller's read (`markups` converts at its rate)
    return {clave: SellInOutBatch(hoy, campanas_por_clave[clave], bna, costos) for clave in contextos_por_clave}


def _campanas_vigentes(
    filas: list,
    por_item: Dict[int, Set[int]],
    contextos: Optional[Sequence[ContextoMarkup]],
    scopes: Dict[int, Optional[Scope]],
    usado_global: Dict[int, Tuple[int, Decimal]],
    usado_por_target: Dict[int, Dict[TargetKey, Tuple[int, Decimal]]],
) -> Dict[int, List[_Campana]]:
    """`{item_id: campaigns with cap left under contextos}`, in id order, from rows already read."""
    vigentes: Dict[int, _Campana] = {}
    agotadas = set()
    for c, item_id, monto_item in filas:
        if c.id not in vigentes and c.id not in agotadas:
            scope = scopes.get(c.id) if contextos is not None else None
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
    return {item: [vigentes[c] for c in sorted(cs) if c in vigentes] for item, cs in por_item.items()}


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


def _uso_sell_out_por_target(db: Session, campana_ids: List[int]) -> Dict[int, Dict[TargetKey, Tuple[int, Decimal]]]:
    """Units/money already taken per campaign and store/channel counter (per-target caps), read the way the tactical
    screen reads its "quedan" (`tienda_scope.usado_por_contador`), so both agree on what a store has left."""
    t = SellOutConsumo
    usados = usado_por_contador(db, (t.campana_id, t.canal, t.venta_ref, t.unidades, t.monto), campana_ids)
    return {
        cid: {key: (unidades[key], montos.get(key, Decimal(0))) for key in unidades}
        for cid, (unidades, montos) in usados.items()
    }
