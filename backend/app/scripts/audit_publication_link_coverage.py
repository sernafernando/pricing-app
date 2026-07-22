"""Coverage audit — cross-item_id `ml_item_relations` edges
(productos-catalog-family-tree, PR1b).

PR2's tree assembly JOINs `ml_item_relations` edges back onto EXISTING
mlas only (no net-new MLA ingestion is in scope for this feature). This
audit validates that "join-existing" assumption at scale: for every
persisted edge, it resolves both `mla` and `related_mla` to their ERP
`item_id` (via `publicaciones_ml`) and flags any edge whose two sides
disagree — a "vinculada" whose sibling belongs to a DIFFERENT product,
which is outside PR2's grouping model as currently designed.

SIGNAL-ONLY: this audit never fails the build (always exits 0). A
non-zero cross-item_id count is NOT a bug to silently absorb — it is a
scope signal that must be logged prominently (loud `logger.warning`) so
a human decides whether PR2's join-existing assumption needs revision
before it ships.

Run:
    python app/scripts/audit_publication_link_coverage.py
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from app.core.database import get_background_db  # noqa: E402
from app.models.ml_item_relation import MlItemRelation  # noqa: E402
from app.models.publicacion_ml import PublicacionML  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class CoverageAuditResult:
    """Counts produced by one audit pass."""

    total_edges: int
    cross_item_id_edges: int
    unresolvable_edges: int


@dataclass
class LinkAnomaly:
    """Per-edge detail for one anomalous `ml_item_relations` edge.

    Surfaced to the anomaly-review tab so a human can correct the
    underlying mispublication (see productos-catalog-family-tree closing
    slice). Only anomalous edges (cross_item | unresolvable) are ever
    represented — same-item_id edges are the expected case and never
    produce a `LinkAnomaly`.
    """

    mla: str
    item_id: int
    related_mla: str
    related_item_id: int | None
    reason: str  # "cross_item" | "unresolvable"
    stock_relation: int | None


def audit_coverage(db) -> CoverageAuditResult:
    """Scans every `ml_item_relations` edge and classifies it.

    Args:
        db: Open SQLAlchemy session.

    Returns:
        `CoverageAuditResult` with total/cross-item_id/unresolvable counts.
        Never raises on a non-zero cross-item_id count — that is a signal
        to log, not a failure condition (see module docstring).
    """
    edges = db.query(MlItemRelation).all()
    total_edges = len(edges)
    cross_item_id_edges = 0
    unresolvable_edges = 0

    if total_edges == 0:
        return CoverageAuditResult(total_edges=0, cross_item_id_edges=0, unresolvable_edges=0)

    mlas = {edge.mla for edge in edges} | {edge.related_mla for edge in edges}
    item_id_by_mla = {row.mla: row.item_id for row in db.query(PublicacionML).filter(PublicacionML.mla.in_(mlas)).all()}

    for edge in edges:
        source_item_id = item_id_by_mla.get(edge.mla)
        related_item_id = item_id_by_mla.get(edge.related_mla)

        if source_item_id is None or related_item_id is None:
            unresolvable_edges += 1
            continue

        if source_item_id != related_item_id:
            cross_item_id_edges += 1

    if cross_item_id_edges > 0:
        logger.warning(
            "audit_publication_link_coverage: %s/%s ml_item_relations edges are CROSS-item_id "
            "(vinculada's sibling belongs to a different product) — this is a SCOPE SIGNAL for "
            "PR2's join-existing tree-assembly assumption, not an error; requires a human decision "
            "before PR2 ships if non-trivial.",
            cross_item_id_edges,
            total_edges,
        )

    if unresolvable_edges > 0:
        logger.warning(
            "audit_publication_link_coverage: %s/%s ml_item_relations edges reference an mla with "
            "no matching publicaciones_ml row (unresolvable) — check for stale/orphaned edges.",
            unresolvable_edges,
            total_edges,
        )

    logger.info(
        "audit_publication_link_coverage: total_edges=%s cross_item_id_edges=%s unresolvable_edges=%s",
        total_edges,
        cross_item_id_edges,
        unresolvable_edges,
    )

    return CoverageAuditResult(
        total_edges=total_edges,
        cross_item_id_edges=cross_item_id_edges,
        unresolvable_edges=unresolvable_edges,
    )


def list_anomalies(db) -> list[LinkAnomaly]:
    """Scans every `ml_item_relations` edge and returns the ANOMALOUS ones.

    Reuses the same `item_id_by_mla` resolution as `audit_coverage`, but
    returns per-edge detail instead of counts, for the anomaly-review tab
    (productos-catalog-family-tree closing slice). Same-item_id edges are
    the expected case and are never included.

    Args:
        db: Open SQLAlchemy session.

    Returns:
        List of `LinkAnomaly`, one per cross_item or unresolvable edge.
        Empty list when there are no edges or no anomalies.
    """
    edges = db.query(MlItemRelation).all()
    if not edges:
        return []

    mlas = {edge.mla for edge in edges} | {edge.related_mla for edge in edges}
    item_id_by_mla = {row.mla: row.item_id for row in db.query(PublicacionML).filter(PublicacionML.mla.in_(mlas)).all()}

    anomalies: list[LinkAnomaly] = []
    for edge in edges:
        source_item_id = item_id_by_mla.get(edge.mla)
        related_item_id = item_id_by_mla.get(edge.related_mla)

        if source_item_id is None or related_item_id is None:
            reason = "unresolvable"
        elif source_item_id != related_item_id:
            reason = "cross_item"
        else:
            continue

        anomalies.append(
            LinkAnomaly(
                mla=edge.mla,
                item_id=source_item_id,
                related_mla=edge.related_mla,
                related_item_id=related_item_id,
                reason=reason,
                stock_relation=edge.stock_relation,
            )
        )

    return anomalies


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with get_background_db() as db:
        audit_coverage(db)


if __name__ == "__main__":
    main()
