"""What follows a costo SI recompute (owner L15: "se tienen que recalcular todos los costos posteriores"; plan
sell-in-costo-si-t3-paralelo.md Q3; interface handoffs/sell-in-costo-si-interfaz.md §3).

Each area that keeps a value computed from costo SI (ML sale costs, legacy metrics, ventas por fuera, stored markups)
adds ITS OWN module to this package and calls `registrar(nombre, fn)` at import. `queue.drenar` calls `despachar`
after a recompute that changed the product's history, inside the product's transaction and before its commit: the
new average and every follow-up commit together, or the product is rolled back and retried. So a callback must be
cheap and idempotent: it ENQUEUES its area's work (its own queue), it never re-freezes inline. It receives the product
whose average changed (a combo only when T4 marks a PC, L22: otherwise `lote.combos_con` gives the combos that
contain it) and the first date whose value changed.
"""

from __future__ import annotations

import importlib
import pkgutil
from datetime import date
from typing import Callable, Dict

from sqlalchemy.orm import Session

Callback = Callable[[Session, int, date], None]

_CALLBACKS: Dict[str, Callback] = {}
_cargados = False


def registrar(nombre: str, fn: Callback) -> None:
    """Register `fn` under `nombre` (registering a name again replaces it: a module imported twice counts once)."""
    _CALLBACKS[nombre] = fn


def _cargar() -> None:
    """Import every module of this package once, so each area's registration runs without a shared list to edit."""
    global _cargados
    if _cargados:
        return
    for modulo in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        importlib.import_module(f"{__name__}.{modulo.name}")
    _cargados = True


def despachar(db: Session, item_id: int, desde: date) -> None:
    """Call every registered callback, in name order, with `item_id` and the first date whose costo SI changed.
    Called only by `queue.drenar`; an exception propagates (the product's transaction rolls back)."""
    _cargar()
    for nombre in sorted(_CALLBACKS):
        _CALLBACKS[nombre](db, item_id, desde)
