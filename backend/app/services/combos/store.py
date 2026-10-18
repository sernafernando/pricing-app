"""Read and write `combo_componentes` for the reconcile (combos-propios C1).

The caller owns the transaction: nothing here commits.

Concurrency: a reconcile is load -> plan -> apply, and a plan computed from
rows another writer changed in between would write stale data. Every function
here takes the transaction-scoped advisory lock `LOCK_KEY` first, so two
reconciles in different transactions run one after the other: the lock is held
from the load until the caller's commit or rollback. Postgres only.

`apply` returns the rows it actually changed, not the plan lengths: a pair
already inserted is skipped (ON CONFLICT DO NOTHING), an update that finds the
quantity already right or the pair gone counts 0, and so does a delete of a
pair already gone. A writer that bypasses the lock can therefore make the
counts smaller than the plan, never wrong, and never make the apply raise.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.combo_componente import ComboComponente
from app.services.combos.reconcile import Bom, Componentes, Plan

_T = ComboComponente.__table__

# Key of the single-key advisory lock that serializes reconciles. A stable
# constant: if it changed between deploys, two versions running at once would no
# longer exclude each other. Next free key of the project's 84_217_xxx series
# (see `SYNC_PROVEEDORES_LOCK_KEY` in `proveedores_service`).
LOCK_KEY = 84_217_005

_INSERT = text(
    "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) "
    "SELECT * FROM unnest(CAST(:c AS integer[]), CAST(:k AS integer[]), CAST(:q AS numeric[])) "
    "ON CONFLICT (combo_item_id, componente_item_id) DO NOTHING"
)
_UPDATE = text(
    "UPDATE combo_componentes AS t SET cantidad = v.q, updated_at = now() "
    "FROM unnest(CAST(:c AS integer[]), CAST(:k AS integer[]), CAST(:q AS numeric[])) AS v(c, k, q) "
    "WHERE t.combo_item_id = v.c AND t.componente_item_id = v.k AND t.cantidad <> v.q"
)
_DELETE = text(
    "DELETE FROM combo_componentes AS t "
    "USING unnest(CAST(:c AS integer[]), CAST(:k AS integer[])) AS v(c, k) "
    "WHERE t.combo_item_id = v.c AND t.componente_item_id = v.k"
)


def lock(db: Session) -> None:
    """Take the reconcile lock until the current transaction ends (re-entrant)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})


def load_current(db: Session) -> Bom:
    """Every stored row as `{combo: {component: quantity}}`. Takes the lock."""
    lock(db)
    bom: Bom = {}
    rows = db.execute(select(_T.c.combo_item_id, _T.c.componente_item_id, _T.c.cantidad))
    for combo, componente, cantidad in rows:
        bom.setdefault(combo, {})[componente] = cantidad
    return bom


def load_combo(db: Session, combo_item_id: int) -> Componentes:
    """The stored components of one combo. Takes the lock."""
    lock(db)
    rows = db.execute(select(_T.c.componente_item_id, _T.c.cantidad).where(_T.c.combo_item_id == combo_item_id))
    return {componente: cantidad for componente, cantidad in rows}


def apply(db: Session, plan: Plan) -> dict[str, int]:
    """Write the plan. Returns the rows actually inserted, updated and deleted."""
    lock(db)
    counts = {"inserted": 0, "updated": 0, "deleted": 0}
    if plan.inserts:
        c, k, q = zip(*plan.inserts)
        counts["inserted"] = db.execute(_INSERT, {"c": list(c), "k": list(k), "q": list(q)}).rowcount
    if plan.updates:
        c, k, q = zip(*plan.updates)
        counts["updated"] = db.execute(_UPDATE, {"c": list(c), "k": list(k), "q": list(q)}).rowcount
    if plan.deletes:
        c, k = zip(*plan.deletes)
        counts["deleted"] = db.execute(_DELETE, {"c": list(c), "k": list(k)}).rowcount
    return counts
