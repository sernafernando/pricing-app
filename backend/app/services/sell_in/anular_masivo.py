"""Bulk void of sell-in purchases or bonuses, all or nothing.

Each record goes through the SAME single-void step (`compras.anular_compra_sin_commit`, `bonos_crud.anular_bono_sin_commit`): same
guards, same audit rows, same release of units. Everything happens in one transaction: an already-voided record is
skipped and reported; any refused one (missing, or refused by its guard) rolls the whole set back, and the error
names each refused record and why. A deadlock with another writer (40P01) also rolls everything back, as a refusal
the caller can retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

REINTENTAR = "Reintentar en unos segundos."
DEADLOCK = "40P01"  # deadlock_detected: Postgres aborted the transaction to break a lock cycle with another writer


@dataclass(frozen=True)
class Rechazo:
    id: int
    motivo: str
    no_existe: bool = False


class AnulacionRechazada(Exception):
    """At least one record cannot be voided: nothing was voided. `reintentar` when a deadlock with another writer
    stopped it (`ocupada` is the record it was voiding, None while taking the locks up front): the caller can retry."""

    def __init__(self, rechazadas: list[Rechazo], *, reintentar: bool = False, ocupada: Optional[int] = None) -> None:
        super().__init__(f"{len(rechazadas)} rechazadas")
        self.rechazadas = rechazadas
        self.reintentar = reintentar
        self.ocupada = ocupada

    @property
    def solo_inexistentes(self) -> bool:
        """Every refusal is an id that does not exist (a 422), none a conflict."""
        return not self.reintentar and all(r.no_existe for r in self.rechazadas)


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
    any id is missing or refused. Every id is tried, so the error lists all the refused ones, not just the first; a
    deadlock (40P01) stops at once, as a retry naming the record it was voiding.
    """
    anuladas: list[int] = []
    ya_anuladas: list[int] = []
    rechazadas: list[Rechazo] = []
    actual: Optional[int] = None
    try:
        try:
            if preparar is not None:
                preparar()
            for id_ in dict.fromkeys(ids):
                actual = id_
                try:
                    if anular_uno(id_) is None:
                        rechazadas.append(Rechazo(id_, no_existe(id_), no_existe=True))
                    else:
                        anuladas.append(id_)
                except ya_anulada:
                    ya_anuladas.append(id_)
                except rechazos as exc:
                    rechazadas.append(Rechazo(id_, str(exc)))
        except DBAPIError as exc:
            if getattr(exc.orig, "pgcode", None) != DEADLOCK:
                raise
            ocupada = (
                [Rechazo(actual, f"Otra operación la está modificando. {REINTENTAR}")] if actual is not None else []
            )
            raise AnulacionRechazada([*ocupada, *rechazadas], reintentar=True, ocupada=actual) from exc
        if rechazadas:
            raise AnulacionRechazada(rechazadas)
        db.commit()
    except Exception:
        db.rollback()  # nothing is voided; never leave the session aborted
        raise
    return anuladas, ya_anuladas
