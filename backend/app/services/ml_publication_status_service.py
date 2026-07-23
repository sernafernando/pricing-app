"""
Per-MLA publication status (`active`/`paused`/`closed`/`under_review`),
resolved from the ERP-mirrored `tb_mercadolibre_items_publicados` table.

Extracted VERBATIM from the flat `GET /productos/{item_id}/mercadolibre`
endpoint (`productos_detail.py`), which is the historical source of truth
for the per-publication status badge the old flat MLA panel rendered. The
recursive publication tree (`ml_publication_tree_service.py`) dropped that
badge on migration; both callers now share this single implementation so
the two views can never disagree.

The table lives in the MAIN application DB (the same `Session` every
caller already holds) — it is NOT the cross-DB ml-webhook mirror, so no
pool-safety dance (short-lived background session / proxy call) is
needed here, just one batched query on the caller's existing session.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

# ERP `optval`-style status ids as mirrored in
# `tb_mercadolibre_items_publicados.mlp_laststatusid`. An unknown id is
# NOT swallowed: `resolve_publication_status` surfaces it as
# `status_{id}` so a new ERP state shows up instead of silently reading
# as "no status".
ML_PUBLICATION_STATUS_MAP: Dict[int, str] = {
    153: "active",
    154: "paused",
    155: "closed",
    156: "under_review",
}


def resolve_publication_status(status_id: Optional[int], is_active: Optional[bool]) -> Optional[str]:
    """Resolves one publication's status string from its ERP columns.

    Business precedence (unchanged from the flat endpoint — do NOT
    reorder, the two branches disagree for paused-but-active rows):
      1. A truthy `mlp_laststatusid` wins: it is ML's own last reported
         state, the most specific signal available. Ids outside
         `ML_PUBLICATION_STATUS_MAP` degrade to `status_{status_id}`
         rather than to `None`.
      2. Otherwise, a non-null `mlp_active` boolean is the fallback:
         the ERP only tracks the coarse active/paused distinction here.
      3. Both absent -> `None` (genuinely unknown; callers render no
         badge rather than guessing).

    Args:
        status_id: `mlp_laststatusid` (may be `None`, or `0` which is
            treated as absent — falsy, same as the original code).
        is_active: `mlp_active` (may be `None`).

    Returns:
        The status string, or `None` when nothing is known.
    """
    if status_id:
        return ML_PUBLICATION_STATUS_MAP.get(status_id, f"status_{status_id}")
    if is_active is not None:
        return "active" if is_active else "paused"
    return None


def fetch_publication_status_by_mla(db: Session, mla_ids: List[str]) -> Dict[str, Optional[str]]:
    """Batch-resolves `publication_status` for `mla_ids` (ONE query).

    Only MLAs that actually have a `tb_mercadolibre_items_publicados`
    row are keyed in the result: an MLA missing from the ERP mirror is
    ABSENT from the dict, never keyed to `None`. Callers therefore keep
    the ability to distinguish "not tracked in the ERP" from "tracked
    but with no resolvable status" (the flat endpoint relies on this —
    it only ever emits the `publication_status` field for MLAs the table
    knows about).

    Args:
        db: Open SQLAlchemy session on the MAIN app DB. Read-only.
        mla_ids: MLA ids to resolve. An empty list short-circuits and
            issues NO query at all.

    Returns:
        `{mla: status_or_None}` for the MLAs present in the table.
    """
    if not mla_ids:
        return {}

    rows = (
        db.query(
            MercadoLibreItemPublicado.mlp_publicationID,
            MercadoLibreItemPublicado.mlp_lastStatusID,
            MercadoLibreItemPublicado.mlp_Active,
        )
        .filter(MercadoLibreItemPublicado.mlp_publicationID.in_(mla_ids))
        .all()
    )
    return {mla: resolve_publication_status(status_id, is_active) for mla, status_id, is_active in rows}
