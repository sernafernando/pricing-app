"""`tplink.solo`: the TP-only data lock.

A user with this permission only sees the sales of the TP-Link store group
(the `tplink` clave in `ml_tiendas_oficiales`), costed at the TP cost, and
never the Gauss figures. It wins over every other permission: holding it
together with one that would normally show Gauss figures still hides them.
It is opt-in (`OPT_IN_PERMISSION_CODES`), so SUPERADMIN has it only by grant.
"""

from __future__ import annotations

from typing import Any, Tuple

from sqlalchemy.orm import Session

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.tiendas_oficiales import TPLINK_CLAVE, require_store_ids_for_clave

TPLINK_SOLO = "tplink.solo"

# A store id no publication carries: the `stores` filter value that matches
# nothing. An EMPTY store filter means "every store", so a request that falls
# entirely outside the TP group must narrow to this, never to `()`.
NO_STORE_MATCH = "-1"


def es_tplink_solo(db: Session, usuario: Usuario) -> bool:
    return PermisosService(db).tiene_permiso(usuario, TPLINK_SOLO)


def lock_stores(db: Session, requested: Tuple[str, ...]) -> Tuple[str, ...]:
    """The `stores` filter a TP-only user actually gets: the requested stores
    intersected with the TP group (the whole group when none is requested).
    Never wider than the group; `NO_STORE_MATCH` when nothing is left. Raises
    `StoreClaveNotConfigured` when no store carries the clave (fail closed)."""
    tp_ids = tuple(str(store_id) for store_id in require_store_ids_for_clave(db, TPLINK_CLAVE))
    if not requested:
        return tp_ids
    kept = tuple(store for store in requested if store in tp_ids)
    return kept or (NO_STORE_MATCH,)


def tp_order_condition(db: Session) -> Any:
    """An `EXISTS` correlated to `MlOrdersOps`: true when the order has an item
    whose MLA is published in a TP-group store (the publication's store, never
    the snapshot column). Per ORDER, so a pack's non-TP members drop out.
    Raises `StoreClaveNotConfigured` like `lock_stores`."""
    tp_ids = [int(store_id) for store_id in lock_stores(db, ())]
    return (
        db.query(MlOrderItemOps.id)
        .join(MercadoLibreItemPublicado, MercadoLibreItemPublicado.mlp_publicationID == MlOrderItemOps.item_id)
        .filter(
            MlOrderItemOps.order_id == MlOrdersOps.order_id,
            MercadoLibreItemPublicado.mlp_official_store_id.in_(tp_ids),
        )
        .exists()
    )
