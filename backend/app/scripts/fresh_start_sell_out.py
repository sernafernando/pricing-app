"""Fresh start of sell out: deletes every legacy campaign, program, product group and offset (owner, 2026-11-05).

Owner: "empezar de 0 borra todas las campañas que existan hoy y grupos viejos, es literal, empezar de 0", "hay que
anular y borrar, no quiero historial de nada, porque se va a volver a cargar todo así queda con el sistema nuevo" and,
for the offsets without a group, "sí, borrá también los offsets sueltos".

In ONE transaction, all or nothing, in this order (each table's FKs are RESTRICT / NO ACTION towards the next):

1. `sell_out_campanas` (its links, own amounts, consumptions and queue rows go by CASCADE);
2. `sell_out_programas`;
3. the `auditoria` rows of those campaigns and programs (`TIPOS_AUDITORIA`; offsets and groups write none);
4. `offset_grupo_consumo`, `offset_grupo_resumen`, `offset_individual_consumo`, `offset_individual_resumen`;
5. `offsets_ganancia`, every row, with a group or without;
6. `offset_grupo_filtros` and `offset_grupos`, hidden ones included;
7. `offsets_migracion_pendientes`.

Sell in (purchases, bonuses, cost modes) is untouched: `sell_in_bonos_marca.offset_origen_id` has no FK and keeps
the id of the offset it came from. Sequences are kept (no RESTART IDENTITY). The campaigns are gone before their
groups' filters, so the filter triggers find no active campaign and queue nothing.

Refuses, deleting nothing (exit 1), when any tactical exists, any campaign belongs to one or any group is used by one:
the new system's data is never touched. Locks `tacticals` and `sell_out_campanas` against writes (SHARE) and takes
the drain's advisory lock of every campaign (`asignacion.LOCK_SQL`, the lock `asignacion.recalcular` takes), waiting
at most `LOCK_TIMEOUT` for each, so it cannot run while the drain rebuilds a campaign or someone is loading one or a
tactical; the session's `lock_timeout` is restored afterwards (`queue.lock_timeout`). A lock not taken in time or a
deadlock exits 1 with `OCUPADO`, deleting nothing.

Dry run is the DEFAULT: it prints the rows each table holds and deletes nothing. `--apply` deletes, and only with
`--confirm "BORRAR TODO"` (otherwise exit 2). Prints one JSON line (`dry_run`, `antes`, `despues`: rows per table);
messages go to stderr. No row content is printed or logged. Run from `backend/` with `-m`:
    venv/bin/python -m app.scripts.fresh_start_sell_out
    venv/bin/python -m app.scripts.fresh_start_sell_out --apply --confirm "BORRAR TODO"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.services.sell_out import asignacion, queue

CONFIRMACION = "BORRAR TODO"
LOCK_TIMEOUT = "5s"
DEADLOCK = "40P01"  # deadlock_detected
# A lock not taken in time or a deadlock: another process (the drain, a load) holds what the run needs.
OCUPADO = "Otro proceso está usando las campañas: pará el worker de sell out y volvé a correrlo. No se borró nada."
# The audit rows of the sell-out campaigns and programs (`services/sell_out/campanas.py`, `programas.py`).
TIPOS_AUDITORIA = (
    TipoAccion.SELL_OUT_CAMPANA_CREADA,
    TipoAccion.SELL_OUT_CAMPANA_EDITADA,
    TipoAccion.SELL_OUT_CAMPANA_ANULADA,
    TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO,
    TipoAccion.SELL_OUT_CAMPANA_PROGRAMA,
)
_AUDITORIA = "auditoria"
# Deleted in this order; the campaigns' CASCADE children are reported but go with them.
_BORRAR = (
    "sell_out_campanas",
    "sell_out_programas",
    _AUDITORIA,
    "offset_grupo_consumo",
    "offset_grupo_resumen",
    "offset_individual_consumo",
    "offset_individual_resumen",
    "offsets_ganancia",
    "offset_grupo_filtros",
    "offset_grupos",
    "offsets_migracion_pendientes",
)
_CASCADA = ("sell_out_campana_grupos", "sell_out_campana_items", "sell_out_consumos", "sell_out_dirty")
TABLAS = (_BORRAR[0], *_CASCADA, *_BORRAR[1:])

_TACTICALS_SQL = text(
    "SELECT (SELECT count(*) FROM tacticals), "
    "(SELECT count(*) FROM sell_out_campanas WHERE tactical_id IS NOT NULL), "
    "(SELECT count(DISTINCT g.grupo_id) FROM sell_out_campana_grupos AS g "
    " JOIN sell_out_campanas AS c ON c.id = g.campana_id WHERE c.tactical_id IS NOT NULL)"
)
_auditoria = Auditoria.tipo_accion.in_(TIPOS_AUDITORIA)


class FreshStartRechazado(Exception):
    """The run cannot go on; the message (Spanish) is what the operator reads. Nothing was deleted."""


def contar(db: Session) -> dict[str, int]:
    """Rows each table of `TABLAS` holds (for `auditoria`, the sell-out rows only)."""
    filas = {}
    for tabla in TABLAS:
        if tabla == _AUDITORIA:
            filas[tabla] = db.execute(select(func.count()).select_from(Auditoria).where(_auditoria)).scalar_one()
        else:
            filas[tabla] = db.execute(text(f"SELECT count(*) FROM {tabla}")).scalar_one()
    return filas


def _sin_tacticals(db: Session) -> None:
    tacticals, campanas, grupos = db.execute(_TACTICALS_SQL).one()
    if tacticals or campanas or grupos:
        raise FreshStartRechazado(
            f"Hay tacticals cargados ({tacticals}; {campanas} campaña(s) y {grupos} grupo(s) de tacticals): "
            "el fresh start borra solo lo viejo y no se ejecuta con datos del sistema nuevo. No se borró nada."
        )


def ejecutar(db: Session, *, apply: bool) -> tuple[dict[str, int], dict[str, int]]:
    """`(antes, despues)`: the rows per table before and after. Under `apply` it deletes them; it never commits.
    Raises `FreshStartRechazado` (tacticals, a lock not taken in time or a deadlock) with everything as it was."""
    try:
        with queue.lock_timeout(db, LOCK_TIMEOUT):
            # No tactical or campaign is written until this commits, and none is being written now: a campaign
            # still uncommitted elsewhere would miss the snapshot below and be left behind.
            db.execute(text("LOCK TABLE tacticals, sell_out_campanas IN SHARE MODE"))
            ids = [i for (i,) in db.execute(text("SELECT id FROM sell_out_campanas ORDER BY id"))]
            if ids:
                db.execute(asignacion.LOCK_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": ids})
            _sin_tacticals(db)
            antes = contar(db)
            if apply:
                for tabla in _BORRAR:
                    if tabla == _AUDITORIA:
                        db.execute(delete(Auditoria).where(_auditoria))
                    else:
                        db.execute(text(f"DELETE FROM {tabla}"))
            despues = contar(db)
    except DBAPIError as exc:
        if getattr(exc.orig, "pgcode", None) not in (queue.LOCK_NOT_AVAILABLE, DEADLOCK):
            raise
        raise FreshStartRechazado(OCUPADO) from exc
    return antes, despues


def run(session_factory: Callable[[], Session], *, apply: bool) -> dict:
    with session_factory() as db:
        try:
            antes, despues = ejecutar(db, apply=apply)
            if apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
    return {"dry_run": not apply, "antes": antes, "despues": despues}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete every legacy sell-out campaign, program, product group and offset (dry run by default)."
    )
    parser.add_argument("--apply", action="store_true", help="Delete the rows; without it nothing is deleted.")
    parser.add_argument("--confirm", default=None, help=f'Required with --apply: exactly "{CONFIRMACION}".')
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.apply and args.confirm != CONFIRMACION:
        print(f'Para borrar hay que confirmar con --confirm "{CONFIRMACION}". No se borró nada.', file=sys.stderr)
        return 2
    from app.core import database  # resolved at call time, so tests can point it elsewhere

    try:
        summary = run(database.SessionLocal, apply=args.apply)
    except FreshStartRechazado as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
