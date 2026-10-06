"""Resolve official-store ids by `clave` instead of hardcoding them.

Code that needs "the TP-Link store" asks for the ids carrying the `tplink`
clave in `ml_tiendas_oficiales`. When ML changes a store's id, the admin adds
the new id under the same clave and everything follows, with no deploy.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models.ml_tienda_oficial import MlTiendaOficial

TPLINK_CLAVE = "tplink"


class StoreClaveNotConfigured(RuntimeError):
    """No store carries the requested clave: callers must stop, not widen to all stores."""

    def __init__(self, clave: str) -> None:
        self.clave = clave
        super().__init__(f"No hay tiendas configuradas con la clave {clave}")


def store_ids_for_clave(db: Session, clave: str) -> List[int]:
    """Every store id with `clave`, sorted. Inactive rows are INCLUDED on purpose:
    sales made under a retired id must keep counting for the store."""
    rows = db.query(MlTiendaOficial.store_id).filter(MlTiendaOficial.clave == clave).order_by(MlTiendaOficial.store_id)
    return [store_id for (store_id,) in rows.all()]


def require_store_ids_for_clave(db: Session, clave: str) -> List[int]:
    """Like `store_ids_for_clave` but raises `StoreClaveNotConfigured` when empty (fail closed)."""
    ids = store_ids_for_clave(db, clave)
    if not ids:
        raise StoreClaveNotConfigured(clave)
    return ids
