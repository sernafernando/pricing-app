"""
Per-MLA publication status, read from the ML publications store (`ml_items`).

Owner decision: `ml_items` is the source of truth for a publication's
status everywhere. The status chip used to come from the ERP mirror
(`tb_mercadolibre_items_publicados`, synced by the ERP and often months
stale) while the promotions panel's "Publicación pausada" banner came from
`ml_items`, so the same MLA could show "Activa" and the paused banner at
once (prod, MLA1391137819). Every caller now resolves status here:

- the recursive publication tree (`ml_publication_tree_service.py`);
- the flat `GET /productos/{item_id}/mercadolibre` endpoint
  (`productos_detail.py`);
- the promotions banner (`ml_promotions.motivo_sin_consulta_ml`).

`ml_items` lives in the MAIN application DB (the same `Session` every
caller already holds), so this is one batched query on that session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.ml_publications import MlItem
from app.services.ml_publications import queue
from app.services.ml_publications.resources import CORE_RESOURCE

logger = logging.getLogger(__name__)

# ERP `optval`-style status ids as mirrored in
# `tb_mercadolibre_items_publicados.mlp_laststatusid`. NOT used for the
# status chip any more (that reads `ml_items`); kept because the Métricas ML
# board (`ml_daily_metrics/board.py`) still filters the ERP mirror by them.
ML_PUBLICATION_STATUS_MAP: Dict[int, str] = {
    153: "active",
    154: "paused",
    155: "closed",
    156: "under_review",
}

# Statuses this module adds on top of ML's own (`active`, `paused`,
# `under_review`, `inactive`, `closed`, ...), each winning over the row's
# last known status in this order.
NEVER_EXISTED = "never_existed"  # ML answered that the item does not exist
GONE = "gone"  # the item vanished from ML (`gone_at` set)
NO_ML_DATA = "no_ml_data"  # no `ml_items` row, or the row was never fetched

# The queue write of `_queue_unseen`, a seam the test suite pins to a no-op (it opens its own session on the
# app's real database, never the test one).
_enqueue = queue.enqueue


@dataclass(frozen=True)
class MlPublicationStatus:
    """One publication's status as the ML publications store knows it.

    `status` is ML's own value (or one of the module's sentinels above);
    `sub_status` is ML's reason list verbatim (e.g. `["paused_by_seller"]`),
    `None` when the store has none."""

    status: str
    sub_status: Optional[List[str]] = None


def _classify(status: Optional[str], sub_status, gone_at, never_existed: Optional[bool]) -> MlPublicationStatus:
    if never_existed:
        return MlPublicationStatus(NEVER_EXISTED)
    if gone_at is not None:
        return MlPublicationStatus(GONE)
    if not status:
        return MlPublicationStatus(NO_ML_DATA)
    return MlPublicationStatus(status, list(sub_status) if sub_status is not None else None)


def fetch_publication_status_by_mla(db: Session, mla_ids: List[str]) -> Dict[str, MlPublicationStatus]:
    """Batch-resolves every MLA's status from `ml_items` (ONE query).

    When the read succeeds, EVERY requested MLA is keyed: one without an
    `ml_items` row is `NO_ML_DATA` ("Sin datos de ML"), never "active", and
    is queued for a direct fetch (`_queue_unseen`).

    FAIL-OPEN: a failing read is logged and returns `{}` — callers render
    no status at all rather than break (the chip is decoration, and the
    banner must not disable the refresh button when the store is down). An
    absent key therefore means "unknown", distinct from `NO_ML_DATA`.

    Args:
        db: Open SQLAlchemy session on the MAIN app DB. Read-only.
        mla_ids: MLA ids to resolve. An empty list issues NO query.
    """
    if not mla_ids:
        return {}

    # The read runs on the CALLER's session, inside its own SAVEPOINT: a failure
    # rolls back only that savepoint, so the caller's pending objects, loaded
    # (non-expired) objects and transaction all survive — on Postgres a failed
    # statement would otherwise leave the whole transaction aborted.
    savepoint = None
    try:
        savepoint = db.begin_nested()
        rows = (
            db.query(MlItem.item_id, MlItem.status, MlItem.sub_status, MlItem.gone_at, MlItem.never_existed)
            .filter(MlItem.item_id.in_(mla_ids))
            .all()
        )
        savepoint.commit()
        found = {item_id: _classify(status, sub, gone_at, never) for item_id, status, sub, gone_at, never in rows}
    except Exception as exc:  # noqa: BLE001 -- fail-open, see docstring
        logger.warning("ml_items status unavailable for %d MLAs; degrading without status: %s", len(mla_ids), exc)
        if savepoint is not None and savepoint.is_active:
            try:
                savepoint.rollback()
            except Exception:  # noqa: BLE001
                pass
        return {}

    _queue_unseen([mla for mla in dict.fromkeys(mla_ids) if mla not in found])
    return {mla: found.get(mla, MlPublicationStatus(NO_ML_DATA)) for mla in mla_ids}


def _queue_unseen(mla_ids: List[str]) -> None:
    """Queues the MLAs the store has no row for, for a direct fetch of the item in the manual lane.

    The store discovers items by scanning the seller's listing, and ML's scan never returns a deleted item:
    one deleted before the store existed never gets a row, so it read "Sin datos de ML" forever (owner,
    MLA1816578183: inactive, `[forbidden, deleted]`). A direct fetch records ML's real status (or a 404).
    Manual lane: someone is looking at the publication, so it does not wait behind the reconcile backlog (an
    entry already queued in a lower lane moves up). The queue dedupes, so asking again is harmless. Its own
    short transaction, never the caller's; FAIL-OPEN like the read: a failure only leaves the MLA for the next reader."""
    if not mla_ids:
        return
    entries = [
        queue.EnqueueEntry(kind="item", entity_id=mla, lane=queue.LANE_MANUAL, resources=(CORE_RESOURCE,))
        for mla in mla_ids
    ]
    try:
        _enqueue(entries)
    except Exception as exc:  # noqa: BLE001 -- fail-open, see docstring
        logger.warning("could not queue %d MLAs without an ml_items row: %s", len(mla_ids), exc)
