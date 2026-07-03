"""
Batch-prefetch helpers for offset resumen/limit lookups.

Replaces the per-iteration `.filter(x == key).first()` N+1 pattern used
across the rentabilidad/offset dashboards with a single `.in_()` query per
resumen type, following the batch-prefetch idiom already used in
`productos_listing.py`.

Pure read helpers — no business logic. All three functions:
- collect keys before the caller's loop (caller responsibility),
- issue exactly one query per call (or zero when the id list is empty),
- return a `dict` keyed by the relevant id, with missing ids simply absent
  (never `None`).
"""

from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualResumen


def fetch_resumenes_grupo(db: Session, grupo_ids: Iterable[int]) -> dict[int, OffsetGrupoResumen]:
    """
    Batch-load OffsetGrupoResumen rows keyed by grupo_id.

    Replaces the per-group `OffsetGrupoResumen.filter(grupo_id == x).first()`
    lookups. `grupo_id` is UNIQUE per resumen row, so the dict is a safe 1:1
    mapping.

    Returns {} without querying when grupo_ids is empty.
    """
    ids = list({gid for gid in grupo_ids if gid is not None})
    if not ids:
        return {}
    rows = db.query(OffsetGrupoResumen).filter(OffsetGrupoResumen.grupo_id.in_(ids)).all()
    return {row.grupo_id: row for row in rows}


def fetch_resumenes_individuales(db: Session, offset_ids: Iterable[int]) -> dict[int, OffsetIndividualResumen]:
    """
    Batch-load OffsetIndividualResumen rows keyed by offset_id.

    Replaces the per-offset `OffsetIndividualResumen.filter(offset_id == x).first()`
    lookups. `offset_id` is UNIQUE per resumen row, so the dict is a safe 1:1
    mapping.

    Returns {} without querying when offset_ids is empty.
    """
    ids = list({oid for oid in offset_ids if oid is not None})
    if not ids:
        return {}
    rows = db.query(OffsetIndividualResumen).filter(OffsetIndividualResumen.offset_id.in_(ids)).all()
    return {row.offset_id: row for row in rows}


def fetch_offsets_limite_por_grupo(db: Session, grupo_ids: Iterable[int]) -> dict[int, OffsetGanancia]:
    """
    Batch-load the *limit-bearing* offset for each group — the deterministic
    replacement for the per-group `offset_con_limite` `.first()` tie-break.

    One query filters offsets in `grupo_ids` that carry a limit
    (max_unidades OR max_monto_usd not null), ordered by (grupo_id, id ASC),
    then groups in Python taking the FIRST (lowest id) offset per group.

    ORDER BY id ASC pins the previously non-deterministic `.first()` tie-break
    to "lowest id wins" (design.md §4 ADR — the legacy query had no ORDER BY,
    so there was no guaranteed behavior to preserve; this is a strict
    improvement making the output reproducible).

    Returns {} without querying when grupo_ids is empty.
    """
    ids = list({gid for gid in grupo_ids if gid is not None})
    if not ids:
        return {}
    rows = (
        db.query(OffsetGanancia)
        .filter(
            OffsetGanancia.grupo_id.in_(ids),
            or_(
                OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None),
            ),
        )
        .order_by(OffsetGanancia.grupo_id, OffsetGanancia.id.asc())
        .all()
    )
    result: dict[int, OffsetGanancia] = {}
    for row in rows:
        result.setdefault(row.grupo_id, row)  # ordered id ASC -> first seen = lowest id
    return result
