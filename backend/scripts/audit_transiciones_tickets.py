"""Read-only pre-merge production transition audit (PR fix/tickets-workflow-enforcement).

Before `TICKETS_WORKFLOW_ENFORCE` starts rejecting invalid transitions in
production, this script replays every `tickets_historial` row with
`accion='estado_changed'`, groups them by `(estado_anterior_id,
estado_nuevo_id)`, and reports which of those pairs have NO matching
`tickets_transiciones` edge configured. Each nonzero pair found here would
start being rejected with a 409 the moment enforcement goes live, unless it
either represents a legitimate transition missing from the graph (add it via
a data migration) or unwanted historical noise (leave it alone).

This script performs ZERO writes: `find_unconfigured_transitions` only
issues SELECTs, and `main()` never calls `db.add`/`db.commit`.

Usage:
    cd backend && DATABASE_URL=<prod-or-staging-url> ./venv/bin/python -m scripts.audit_transiciones_tickets

Per design §5 / task 1.9 (PR 1's BLOCKING PROCESS GATE): run this against
PRODUCTION and paste the full output into the PR body before merging.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.workflow import EstadoTicket, TransicionEstado

# Several ticket models declare relationships by STRING (e.g.
# `relationship("Usuario")` in adjunto_ticket.py, asignacion_ticket.py,
# comentario_ticket.py, historial_ticket.py, sector_usuario.py). SQLAlchemy
# resolves those names against a global mapper registry that is only
# populated for classes that were actually imported somewhere in the
# process. Inside FastAPI, `app/main.py` imports every model, so the
# registry is always complete; run as a standalone script, it is not,
# and `configure_mappers()` fails with `InvalidRequestError: ... failed to
# locate a name ('Usuario')`. `alembic/env.py:6` hits the exact same issue
# and fixes it the exact same way — do NOT "clean up" these as unused
# imports; removing them breaks standalone execution.
from app.models import *  # noqa: F401,F403
from app.tickets.models import *  # noqa: F401,F403


def find_unconfigured_transitions(db: Session) -> list[dict[str, Any]]:
    """Group `estado_changed` historial rows by `(estado_anterior_id,
    estado_nuevo_id)` and return the pairs that have no matching
    `tickets_transiciones` edge.

    Read-only: issues SELECTs only, never writes.

    Returns a list of dicts, one per unconfigured pair, each with:
        estado_anterior_id, estado_anterior_nombre,
        estado_nuevo_id, estado_nuevo_nombre,
        count, last_seen
    """
    rows = (
        db.query(
            HistorialTicket.estado_anterior_id,
            HistorialTicket.estado_nuevo_id,
            func.count(HistorialTicket.id).label("count"),
            func.max(HistorialTicket.fecha).label("last_seen"),
        )
        .filter(
            HistorialTicket.accion == "estado_changed",
            HistorialTicket.estado_anterior_id.isnot(None),
            HistorialTicket.estado_nuevo_id.isnot(None),
        )
        .group_by(HistorialTicket.estado_anterior_id, HistorialTicket.estado_nuevo_id)
        .all()
    )

    unconfigured: list[dict[str, Any]] = []
    for estado_anterior_id, estado_nuevo_id, count, last_seen in rows:
        edge = (
            db.query(TransicionEstado)
            .filter(
                TransicionEstado.estado_origen_id == estado_anterior_id,
                TransicionEstado.estado_destino_id == estado_nuevo_id,
            )
            .first()
        )
        if edge is not None:
            continue

        estado_anterior = db.query(EstadoTicket).filter(EstadoTicket.id == estado_anterior_id).first()
        estado_nuevo = db.query(EstadoTicket).filter(EstadoTicket.id == estado_nuevo_id).first()

        unconfigured.append(
            {
                "estado_anterior_id": estado_anterior_id,
                "estado_anterior_nombre": estado_anterior.nombre if estado_anterior else "?",
                "estado_nuevo_id": estado_nuevo_id,
                "estado_nuevo_nombre": estado_nuevo.nombre if estado_nuevo else "?",
                "count": count,
                "last_seen": last_seen,
            }
        )

    return unconfigured


def _format_last_seen(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "?"


def main() -> None:
    db = SessionLocal()
    try:
        unconfigured = find_unconfigured_transitions(db)

        print("Ticket workflow transition audit — READ-ONLY (nothing was written)")
        if not unconfigured:
            print("  No unconfigured transition pairs found. Safe to enable TICKETS_WORKFLOW_ENFORCE.")
            return

        print(f"  {len(unconfigured)} unconfigured pair(s) found:")
        for pair in sorted(unconfigured, key=lambda p: p["count"], reverse=True):
            print(
                f"    '{pair['estado_anterior_nombre']}' (#{pair['estado_anterior_id']}) -> "
                f"'{pair['estado_nuevo_nombre']}' (#{pair['estado_nuevo_id']}): "
                f"count={pair['count']}, last_seen={_format_last_seen(pair['last_seen'])}"
            )
    finally:
        db.rollback()  # read-only, but never trust it implicitly (see pxq_permissions_dry_run.py)
        db.close()


if __name__ == "__main__":
    main()
