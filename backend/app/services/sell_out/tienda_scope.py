"""Official-store / channel scope for sell-out campaigns that belong to a tactical.

A campaign without `tactical_id` stays global (pre-scope behaviour). With a tactical:
`todas_tiendas` credits every ML sale, with or without an official store (what a tactical
credited before the scope existed); `fuera` / `tienda_nube` only when those synthetic rows are listed.
A tactical that predates the scope got both rows and a shared cap from migration `20261107_tacticals_tiendas`. `tope_compartido` is independent: False means
each target gets its own run of `tope.asignar` with the same cap numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, FrozenSet, Iterable, Optional, Protocol, Set, Tuple, TypeVar

from sqlalchemy.orm import Session, selectinload

from app.models.ml_sale_line import MlSaleLine
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tactical import Tactical

# tactical_tiendas.tipo for synthetic channels ↔ sell_out canal
_CANAL_A_TIPO = {"fuera": "fuera", "tn": "tienda_nube"}

# ('oficial', store_id) | ('sin_tienda', None) for ML without official store | ('fuera'|'tienda_nube', None)
TargetKey = Tuple[str, Optional[int]]


@dataclass(frozen=True)
class Scope:
    todas_tiendas: bool
    tope_compartido: bool
    oficiales: FrozenSet[int]
    canales: FrozenSet[str]  # 'fuera' | 'tienda_nube'


class _DeTactical(Protocol):
    id: int
    tactical_id: Optional[int]


def scopes_de(db: Session, hijos: Iterable[_DeTactical]) -> Dict[int, Optional[Scope]]:
    """The store scope of each child row (a sell out campaign, a sell in bonus) by its id, from its tactical in one
    read; a child without a tactical stays `None` (global). Every engine and the markup read scopes here."""
    hijos = list(hijos)
    ids = {h.tactical_id for h in hijos if h.tactical_id is not None}
    if not ids:
        return {h.id: None for h in hijos}
    tacticals = {
        t.id: t for t in db.query(Tactical).options(selectinload(Tactical.tiendas)).filter(Tactical.id.in_(ids))
    }
    return {
        h.id: (scope_desde_tactical(tacticals[h.tactical_id]) if h.tactical_id in tacticals else None) for h in hijos
    }


def scope_desde_tactical(tactical: Tactical) -> Scope:
    oficiales = frozenset(
        int(fila.store_id) for fila in tactical.tiendas if fila.tipo == "oficial" and fila.store_id is not None
    )
    canales = frozenset(fila.tipo for fila in tactical.tiendas if fila.tipo in ("fuera", "tienda_nube"))
    return Scope(
        todas_tiendas=bool(tactical.todas_tiendas),
        tope_compartido=bool(tactical.tope_compartido),
        oficiales=oficiales,
        canales=canales,
    )


def alcanza(scope: Optional[Scope], canal: str, store_id: Optional[int]) -> bool:
    """Whether a sale line is inside the tactical's store/channel selection."""
    if scope is None:
        return True
    if canal == "ml":
        if scope.todas_tiendas:
            return True  # every ML sale, an official store or not
        return store_id is not None and store_id in scope.oficiales
    tipo = _CANAL_A_TIPO.get(canal)
    if tipo is None:
        return False
    return tipo in scope.canales


def target_key(canal: str, store_id: Optional[int]) -> Optional[TargetKey]:
    """Counter bucket for per-target caps; None when the line has no countable target."""
    if canal == "ml":
        return ("sin_tienda", None) if store_id is None else ("oficial", int(store_id))
    tipo = _CANAL_A_TIPO.get(canal)
    return (tipo, None) if tipo else None


def orden_targets(keys: Iterable[TargetKey]) -> list[TargetKey]:
    return sorted(keys, key=lambda k: (k[0], k[1] is None, k[1] or 0))


def por_tienda(scope: Optional[Scope]) -> bool:
    """Whether each store or channel has its own cap counter (a tactical with `tope_compartido` false)."""
    return scope is not None and not scope.tope_compartido


def tiendas_activas(db: Session) -> Set[int]:
    """The active official stores: with every store, each one is a counter before it sells (`contadores`)."""
    return {int(s) for (s,) in db.query(MlTiendaOficial.store_id).filter(MlTiendaOficial.activa.is_(True))}


def contadores(scope: Scope, activas: Set[int]) -> Set[TargetKey]:
    """The cap counters a per-store scope has before any sale: each listed store (with every store, each active one
    plus the ML sales without one) and each listed channel. A counter that already credited a sale counts too."""
    keys: Set[TargetKey] = {(tipo, None) for tipo in scope.canales}
    if scope.todas_tiendas:
        keys |= {("oficial", s) for s in activas} | {("sin_tienda", None)}
    else:
        keys |= {("oficial", s) for s in scope.oficiales}
    return keys


def targets_de_ventas(db: Session, ventas: Iterable[Tuple[str, int]]) -> Dict[Tuple[str, int], Optional[TargetKey]]:
    """The counter of each credited sale `(canal, venta_ref)`, keyed as the engines key it: an ML sale by its
    publication's current official store (`alcance.stores_por_mla`, the store the engines read)."""
    from app.services.sell_out import alcance  # alcance reaches the sell in engines, which import this module

    ventas = set(ventas)
    refs = sorted({ref for canal, ref in ventas if canal == "ml"})
    mlas = (
        {
            int(r): m
            for r, m in db.query(MlSaleLine.item_row_id, MlSaleLine.mla).filter(MlSaleLine.item_row_id.in_(refs))
        }
        if refs
        else {}
    )
    stores = alcance.stores_por_mla(db, {m for m in mlas.values() if m})
    return {
        (canal, ref): target_key(canal, stores.get(mlas.get(ref)) if canal == "ml" else None) for canal, ref in ventas
    }


N = TypeVar("N", int, Decimal)


def maximo_usado(usados: Dict[TargetKey, N], cero: N) -> N:
    """What the most-used counter took: a per-store cap never goes below it."""
    return max(usados.values(), default=cero)


def restante(tope: N, usados: Dict[TargetKey, N], keys: Set[TargetKey], cero: N) -> N:
    """How much more a per-store cap can still credit: over every counter, what its cap has left, never below zero."""
    return sum((max(tope - usados.get(k, cero), cero) for k in keys | set(usados)), cero)
