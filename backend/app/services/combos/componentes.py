"""Read the app-owned combo bill of materials (combos-propios C2).

The ONE place readers ask "what is this combo made of" or "is this a combo",
over `combo_componentes` instead of the ERP mirror `tb_item_association`.

Same definition the readers had over the mirror: a component is a row with a
positive quantity (`combo_componentes` only stores those), and a pair the ERP
listed twice is stored once with the summed quantity. The table has no ERP
company: the sync refuses a snapshot from more than one company.

Read-only and lock-free: unlike `store`, nothing here takes the reconcile lock,
so a reader never waits for (or blocks) a sync.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.combo_componente import ComboComponente

_T = ComboComponente.__table__


def componentes_de(db: Session, combo_item_ids: Iterable[int]) -> dict[int, dict[int, Decimal]]:
    """`{combo: {component: quantity}}` for these combos, in one query.
    A combo with no stored components is absent from the result."""
    ids = sorted(set(combo_item_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(_T.c.combo_item_id, _T.c.componente_item_id, _T.c.cantidad).where(_T.c.combo_item_id.in_(ids))
    )
    out: dict[int, dict[int, Decimal]] = {}
    for combo, componente, cantidad in rows:
        out.setdefault(combo, {})[componente] = Decimal(cantidad)
    return out


def es_combo(db: Session, item_id: int) -> bool:
    """True when the item has at least one component."""
    return db.execute(select(_T.c.combo_item_id).where(_T.c.combo_item_id == item_id).limit(1)).first() is not None


def combos_que_contienen(db: Session, componente_item_ids: Iterable[int]) -> dict[int, set[int]]:
    """Reverse lookup: `{component: {combos containing it}}`, in one query."""
    ids = sorted(set(componente_item_ids))
    if not ids:
        return {}
    rows = db.execute(select(_T.c.componente_item_id, _T.c.combo_item_id).where(_T.c.componente_item_id.in_(ids)))
    out: dict[int, set[int]] = {}
    for componente, combo in rows:
        out.setdefault(componente, set()).add(combo)
    return out


def sql_no_es_combo(item_id_sql: str) -> str:
    """Raw-SQL predicate "this item is not a combo" for hand-written queries.
    `item_id_sql` is a trusted column reference (e.g. `pe.item_id`), never
    user input."""
    return f"NOT EXISTS (SELECT 1 FROM combo_componentes cc WHERE cc.combo_item_id = {item_id_sql})"
