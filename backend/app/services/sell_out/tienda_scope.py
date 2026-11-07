"""Official-store / channel scope for sell-out campaigns that belong to a tactical.

A campaign without `tactical_id` stays global (pre-scope behaviour). With a tactical:
`todas_tiendas` credits every ML sale that has an official store; `fuera` / `tienda_nube`
only when those synthetic rows are listed. `tope_compartido` is independent: False means
each target gets its own run of `tope.asignar` with the same cap numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional, Tuple

# tactical_tiendas.tipo for synthetic channels ↔ sell_out canal
_CANAL_A_TIPO = {"fuera": "fuera", "tn": "tienda_nube"}

TargetKey = Tuple[str, Optional[int]]  # ('oficial', store_id) | ('fuera'|'tienda_nube', None)


@dataclass(frozen=True)
class Scope:
    todas_tiendas: bool
    tope_compartido: bool
    oficiales: FrozenSet[int]
    canales: FrozenSet[str]  # 'fuera' | 'tienda_nube'


def scope_desde_tactical(tactical) -> Scope:
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
        if store_id is None:
            return False  # sin_tienda is not an official store and not a synthetic channel
        if scope.todas_tiendas:
            return True
        return store_id in scope.oficiales
    tipo = _CANAL_A_TIPO.get(canal)
    if tipo is None:
        return False
    return tipo in scope.canales


def target_key(canal: str, store_id: Optional[int]) -> Optional[TargetKey]:
    """Counter bucket for per-target caps; None when the line has no countable target."""
    if canal == "ml":
        if store_id is None:
            return None
        return ("oficial", int(store_id))
    tipo = _CANAL_A_TIPO.get(canal)
    return (tipo, None) if tipo else None


def orden_targets(keys: Iterable[TargetKey]) -> list[TargetKey]:
    return sorted(keys, key=lambda k: (k[0], k[1] is None, k[1] or 0))
