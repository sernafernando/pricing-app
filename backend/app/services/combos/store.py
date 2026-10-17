"""Read and write `combo_componentes` for the reconcile (combos-propios C1).

The caller owns the transaction: nothing here commits.
"""

from __future__ import annotations

from typing import Dict

from sqlalchemy import bindparam, delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.models.combo_componente import ComboComponente
from app.services.combos.reconcile import Bom, Componentes, Plan

_T = ComboComponente.__table__


def load_current(db: Session) -> Bom:
    """Every stored row as `{combo: {component: quantity}}`."""
    bom: Bom = {}
    rows = db.execute(select(_T.c.combo_item_id, _T.c.componente_item_id, _T.c.cantidad))
    for combo, componente, cantidad in rows:
        bom.setdefault(combo, {})[componente] = cantidad
    return bom


def load_combo(db: Session, combo_item_id: int) -> Componentes:
    """The stored components of one combo."""
    rows = db.execute(select(_T.c.componente_item_id, _T.c.cantidad).where(_T.c.combo_item_id == combo_item_id))
    return {componente: cantidad for componente, cantidad in rows}


def apply(db: Session, plan: Plan) -> Dict[str, int]:
    """Write the plan. Returns the row counts."""
    if plan.inserts:
        db.execute(
            insert(_T),
            [{"combo_item_id": c, "componente_item_id": k, "cantidad": q} for c, k, q in plan.inserts],
        )
    if plan.updates:
        db.execute(
            update(_T)
            .where(_T.c.combo_item_id == bindparam("b_combo"), _T.c.componente_item_id == bindparam("b_componente"))
            .values(cantidad=bindparam("b_cantidad"), updated_at=func.now()),
            [{"b_combo": c, "b_componente": k, "b_cantidad": q} for c, k, q in plan.updates],
        )
    if plan.deletes:
        db.execute(
            delete(_T).where(
                _T.c.combo_item_id == bindparam("b_combo"), _T.c.componente_item_id == bindparam("b_componente")
            ),
            [{"b_combo": c, "b_componente": k} for c, k in plan.deletes],
        )
    return {"inserted": len(plan.inserts), "updated": len(plan.updates), "deleted": len(plan.deletes)}
