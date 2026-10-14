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
    `ml_items` row is `NO_ML_DATA` ("Sin datos de ML"), never "active".

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

    try:
        rows = (
            db.query(MlItem.item_id, MlItem.status, MlItem.sub_status, MlItem.gone_at, MlItem.never_existed)
            .filter(MlItem.item_id.in_(mla_ids))
            .all()
        )
        found = {item_id: _classify(status, sub, gone_at, never) for item_id, status, sub, gone_at, never in rows}
    except Exception as exc:  # noqa: BLE001 -- fail-open, see docstring
        logger.warning("ml_items status unavailable for %d MLAs; degrading without status: %s", len(mla_ids), exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}

    return {mla: found.get(mla, MlPublicationStatus(NO_ML_DATA)) for mla in mla_ids}
