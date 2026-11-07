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
from typing import Any, Dict, FrozenSet, Iterable, Optional, Protocol, Set, Tuple, TypeVar

from sqlalchemy import and_, func, select
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


def necesita_tiendas(scopes: Iterable[Optional[Scope]]) -> bool:
    """Whether any scope reads a sale's official store: one narrowed to some stores, or with a cap per store. With
    every store and a shared cap (or no tactical) an ML sale is in whatever its store, so its lookup is skipped."""
    return any(s is not None and (not s.todas_tiendas or not s.tope_compartido) for s in scopes)


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


def alcanza_alguno(scope: Optional[Scope], contextos: Iterable[Tuple[str, Optional[int]]]) -> bool:
    """Union: the tactical reaches the operator's selection if any (canal, store_id) matches."""
    if scope is None:
        return True
    return any(alcanza(scope, canal, store_id) for canal, store_id in contextos)


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


def usado_por_contador(
    db: Session, filas: Tuple[Any, Any, Any, Any, Any], ids: Iterable[int]
) -> Dict[int, Tuple[Dict[TargetKey, int], Dict[TargetKey, Decimal]]]:
    """What each owner among `ids` credited per counter, `({key: units}, {key: amount})`, added up in SQL. `filas` are
    the credited rows' columns `(owner, canal, venta_ref, unidades, monto)`. An ML sale counts under its
    publication's current official store (`alcance.ultima_tienda`, the store the engines read)."""
    from app.services.sell_out import alcance  # alcance reaches the sell in engines, which import this module

    owner, canal, ref, unidades, monto = filas
    ids = sorted(set(ids))
    salida: Dict[int, Tuple[Dict[TargetKey, int], Dict[TargetKey, Decimal]]] = {i: ({}, {}) for i in ids}
    if not ids:
        return salida
    venta_ml = and_(canal == "ml", MlSaleLine.item_row_id == ref)
    refs_ml = select(ref).where(owner.in_(ids), canal == "ml")
    tienda = alcance.ultima_tienda(select(MlSaleLine.mla).where(MlSaleLine.item_row_id.in_(refs_ml)))
    rows = (
        db.query(owner, canal, tienda.c.store_id, func.sum(unidades), func.sum(monto))
        .outerjoin(MlSaleLine, venta_ml)
        .outerjoin(tienda, tienda.c.mla == MlSaleLine.mla)
        .filter(owner.in_(ids))
        .group_by(owner, canal, tienda.c.store_id)
    )
    for oid, c, store, u, m in rows:
        key = target_key(c, store if c == "ml" else None)
        if key is not None:
            por_unidades, por_monto = salida[oid]
            por_unidades[key] = por_unidades.get(key, 0) + int(u or 0)
            por_monto[key] = por_monto.get(key, Decimal(0)) + Decimal(m or 0)
    return salida


N = TypeVar("N", int, Decimal)


def maximo_usado(usados: Dict[TargetKey, N], cero: N) -> N:
    """What the most-used counter took: a per-store cap never goes below it."""
    return max(usados.values(), default=cero)


def restante(tope: N, usados: Dict[TargetKey, N], keys: Set[TargetKey], cero: N) -> N:
    """How much more a per-store cap can still credit: over every counter, what its cap has left, never below zero."""
    return sum((max(tope - usados.get(k, cero), cero) for k in keys | set(usados)), cero)
