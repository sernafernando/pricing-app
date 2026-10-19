"""Read the app-owned combo bill of materials (combos-propios C2).

The ONE place readers ask "what is this combo made of" or "is this a combo",
over `combo_componentes` instead of the ERP mirror `tb_item_association`.

Same definition the readers had over the mirror: a component is a row with a
positive quantity (`combo_componentes` only stores those), and a pair the ERP
listed twice is stored once with the summed quantity. The table has no ERP
company: the sync refuses a snapshot from more than one company.

Read-only and lock-free: unlike `store`, nothing here takes the reconcile lock,
so a reader never waits for (or blocks) a sync.

Fail closed on an empty table: no rows at all means the sync has not filled it
yet (or it was wiped), never "there are no combos" -- answering would call
every real combo a plain item. A reader that decides "is this a combo" checks
`combos_disponibles` first and refuses instead (HTTP readers answer 503 with
`DETALLE_COMBOS_NO_SINCRONIZADOS`, the repo's error envelope).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.combo_componente import ComboComponente

_T = ComboComponente.__table__

MENSAJE_COMBOS_NO_SINCRONIZADOS = (
    "El catálogo de combos todavía no está sincronizado. Intente de nuevo en unos minutos."
)
DETALLE_COMBOS_NO_SINCRONIZADOS = {"code": "COMBOS_NOT_SYNCED", "message": MENSAJE_COMBOS_NO_SINCRONIZADOS}


class CombosNoSincronizados(RuntimeError):
    """`combo_componentes` is empty: combos cannot be told from plain items."""

    def __init__(self) -> None:
        super().__init__(MENSAJE_COMBOS_NO_SINCRONIZADOS)


def combos_disponibles(db: Session) -> bool:
    """True when the bill of materials has been filled (any row at all)."""
    return bool(db.execute(select(exists().select_from(_T))).scalar())


def exigir_combos_disponibles(db: Session) -> None:
    """Raise `CombosNoSincronizados` while the table is empty."""
    if not combos_disponibles(db):
        raise CombosNoSincronizados()


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
