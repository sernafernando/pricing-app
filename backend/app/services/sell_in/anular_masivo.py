"""Bulk void of sell-in purchases or bonuses, all or nothing.

Each record goes through the SAME single-void step (`compras._anular_compra`, `bonos_crud._anular_bono`): same
guards, same audit rows, same release of units. Everything happens in one transaction: an already-voided record is
skipped and reported; any refused one (missing, or refused by its guard) rolls the whole set back, and the error
names each refused record and why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Rechazo:
    id: int
    motivo: str


class AnulacionRechazada(Exception):
    """At least one record cannot be voided: nothing was voided."""

    def __init__(self, rechazadas: list[Rechazo]) -> None:
        super().__init__(f"{len(rechazadas)} rechazadas")
        self.rechazadas = rechazadas


def anular_varios(
    db: Session,
    ids: Iterable[int],
    anular_uno: Callable[[int], Optional[object]],
    *,
    ya_anulada: type[Exception],
    rechazos: tuple[type[Exception], ...],
    no_existe: Callable[[int], str],
    preparar: Optional[Callable[[], None]] = None,
) -> tuple[list[int], list[int]]:
    """Void every id with `anular_uno` (the single void without its commit) and commit once. `preparar` runs first,
    in the same transaction (the purchases take their products' locks there, in order).

    Returns (voided ids, already-voided ids) in the order sent; raises `AnulacionRechazada` after rolling back when
    any id is missing or refused. Every id is tried, so the error lists all the refused ones, not just the first.
    """
    anuladas: list[int] = []
    ya_anuladas: list[int] = []
    rechazadas: list[Rechazo] = []
    try:
        if preparar is not None:
            preparar()
        for id_ in dict.fromkeys(ids):
            try:
                if anular_uno(id_) is None:
                    rechazadas.append(Rechazo(id_, no_existe(id_)))
                else:
                    anuladas.append(id_)
            except ya_anulada:
                ya_anuladas.append(id_)
            except rechazos as exc:
                rechazadas.append(Rechazo(id_, str(exc)))
        if rechazadas:
            raise AnulacionRechazada(rechazadas)
        db.commit()
    except Exception:
        db.rollback()  # nothing is voided; never leave the session aborted
        raise
    return anuladas, ya_anuladas
