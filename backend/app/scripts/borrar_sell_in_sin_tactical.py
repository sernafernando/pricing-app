"""Deletes the voided sell-in purchases and bonuses that belong to no tactical (owner, 2026-11-05).

Owner: "trae todo a tacticals, los dos sell in que quedaron anulados los podemos borrar incluso eran de test". The
Tacticals tab shows only rows with a tactical, so the voided legacy ones would be left out of every view.

Only rows with `tactical_id IS NULL AND estado = 'anulada'` go, in ONE transaction, all or nothing:

1. `sell_in_compras` (their lines, order links and the consumptions of those lines go by CASCADE);
2. `sell_in_bonos_marca` (their items, queue rows and consumptions go by CASCADE).

Active rows, rows of a tactical and the audit trail are never touched. A row something else still points to
(`sell_in_modos_producto.compra_id`, or an active purchase of a voided bonus: both RESTRICT) stops the run with
exit 1, deleting nothing.

Dry run is the DEFAULT: it prints what it would delete and deletes nothing. `--apply` deletes. Prints one JSON line
(`dry_run`, `compras`, `bonos`: the ids). Run from `backend/` with `-m`:
    venv/bin/python -m app.scripts.borrar_sell_in_sin_tactical
    venv/bin/python -m app.scripts.borrar_sell_in_sin_tactical --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_FILTRO = "tactical_id IS NULL AND estado = 'anulada'"
TABLAS = ("sell_in_compras", "sell_in_bonos_marca")  # deleted in this order: a purchase may point to its bonus
REFERENCIADA = "Algo todavía apunta a una de esas filas (un modo de costo o una compra activa). No se borró nada."


class BorradoRechazado(Exception):
    """The run cannot go on; the message (Spanish) is what the operator reads. Nothing was deleted."""


def ejecutar(db: Session, *, apply: bool) -> dict[str, list[int]]:
    """The ids per table matching `_FILTRO`; under `apply` it deletes them. It never commits."""
    ids = {t: [i for (i,) in db.execute(text(f"SELECT id FROM {t} WHERE {_FILTRO} ORDER BY id"))] for t in TABLAS}
    if apply:
        try:
            for tabla in TABLAS:
                db.execute(text(f"DELETE FROM {tabla} WHERE {_FILTRO}"))
                db.flush()
        except IntegrityError as exc:
            raise BorradoRechazado(REFERENCIADA) from exc
    return ids


def run(session_factory: Callable[[], Session], *, apply: bool) -> dict:
    with session_factory() as db:
        try:
            ids = ejecutar(db, apply=apply)
            if apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
    return {"dry_run": not apply, "compras": ids["sell_in_compras"], "bonos": ids["sell_in_bonos_marca"]}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete the voided sell-in purchases and bonuses without a tactical (dry run by default)."
    )
    parser.add_argument("--apply", action="store_true", help="Delete the rows; without it nothing is deleted.")
    args = parser.parse_args(argv)
    from app.core import database  # resolved at call time, so tests can point it elsewhere

    try:
        summary = run(database.SessionLocal, apply=args.apply)
    except BorradoRechazado as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
