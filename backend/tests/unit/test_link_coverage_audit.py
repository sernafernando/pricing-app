"""
RED/GREEN — publication-link coverage audit
(productos-catalog-family-tree PR1b).

Design's flagged risk: PR2's tree assembly JOINs `ml_item_relations`
edges back onto EXISTING mlas (join-existing assumption — no net-new MLA
ingestion). This audit validates that assumption at scale: it scans every
persisted `ml_item_relations` edge, resolves both `mla` and `related_mla`
to their ERP `item_id` (via `publicaciones_ml`), and flags any edge where
the two item_ids differ (a "vinculada" whose sibling belongs to a
DIFFERENT product — outside PR2's grouping model as designed).

This is a SIGNAL-ONLY audit: it never fails the build (exit 0 always,
per design), but any non-zero cross-item_id count MUST be logged
prominently (not silently swallowed) since it changes PR2's scope.

Spec coverage:
  REQ-1 — counts total edges and cross-item_id edges correctly.
  REQ-2 — an edge where both sides map to the SAME item_id is NOT flagged.
  REQ-3 — an edge where either side has no matching `publicaciones_ml`
          row is a "unresolvable" edge (counted separately, not silently
          coerced into cross-item_id or same-item_id).
  REQ-4 — zero edges -> zero counts, no error.
"""

from __future__ import annotations

import pytest

from app.models.ml_item_relation import MlItemRelation
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.scripts import audit_publication_link_coverage as audit


def _seed_producto(db, item_id: int) -> None:
    if db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first() is None:
        db.add(ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion=f"Producto {item_id}"))
        db.flush()


class TestCoverageAudit:
    def test_zero_edges_zero_counts(self, db) -> None:
        result = audit.audit_coverage(db)

        assert result.total_edges == 0
        assert result.cross_item_id_edges == 0
        assert result.unresolvable_edges == 0

    def test_same_item_id_edge_not_flagged(self, db) -> None:
        _seed_producto(db, 100)
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(PublicacionML(mla="MLA_B", item_id=100))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_B", stock_relation=1))
        db.commit()

        result = audit.audit_coverage(db)

        assert result.total_edges == 1
        assert result.cross_item_id_edges == 0
        assert result.unresolvable_edges == 0

    def test_cross_item_id_edge_flagged(self, db) -> None:
        _seed_producto(db, 100)
        _seed_producto(db, 200)
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(PublicacionML(mla="MLA_C", item_id=200))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_C", stock_relation=1))
        db.commit()

        result = audit.audit_coverage(db)

        assert result.total_edges == 1
        assert result.cross_item_id_edges == 1
        assert result.unresolvable_edges == 0

    def test_unresolvable_edge_counted_separately(self, db) -> None:
        _seed_producto(db, 100)
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_UNKNOWN", stock_relation=1))
        db.commit()

        result = audit.audit_coverage(db)

        assert result.total_edges == 1
        assert result.cross_item_id_edges == 0
        assert result.unresolvable_edges == 1

    def test_non_zero_cross_item_id_logs_prominently(self, db, caplog: pytest.LogCaptureFixture) -> None:
        _seed_producto(db, 100)
        _seed_producto(db, 200)
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(PublicacionML(mla="MLA_C", item_id=200))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_C", stock_relation=1))
        db.commit()

        with caplog.at_level("WARNING"):
            audit.audit_coverage(db)

        assert any("cross" in record.message.lower() for record in caplog.records)


class TestListAnomalies:
    """RED/GREEN — `list_anomalies` surfaces per-edge detail for the anomaly-review tab.

    Spec coverage:
      REQ-1 — a same-item_id edge is NOT listed (only anomalies surface).
      REQ-2 — a cross-item edge is listed with reason="cross_item" and both
              item_ids populated.
      REQ-3 — an unresolvable edge (related_mla absent from publicaciones_ml)
              is listed with reason="unresolvable" and related item_id None.
      REQ-4 — zero edges -> empty list, no error.
    """

    def test_zero_edges_returns_empty_list(self, db) -> None:
        assert audit.list_anomalies(db) == []

    def test_same_item_id_edge_not_listed(self, db) -> None:
        _seed_producto(db, 100)
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(PublicacionML(mla="MLA_B", item_id=100))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_B", stock_relation=1))
        db.commit()

        assert audit.list_anomalies(db) == []

    def test_cross_item_edge_listed(self, db) -> None:
        _seed_producto(db, 2905)
        _seed_producto(db, 3271)
        db.add(PublicacionML(mla="MLA2068711536", item_id=2905))
        db.add(PublicacionML(mla="MLA1493337181", item_id=3271))
        db.add(MlItemRelation(mla="MLA2068711536", related_mla="MLA1493337181", stock_relation=1))
        db.commit()

        anomalies = audit.list_anomalies(db)

        assert len(anomalies) == 1
        anomaly = anomalies[0]
        assert anomaly.mla == "MLA2068711536"
        assert anomaly.item_id == 2905
        assert anomaly.related_mla == "MLA1493337181"
        assert anomaly.related_item_id == 3271
        assert anomaly.reason == "cross_item"
        assert anomaly.stock_relation == 1

    def test_unresolvable_edge_listed_with_related_item_id_none(self, db) -> None:
        _seed_producto(db, 100)
        db.add(PublicacionML(mla="MLA2374249178", item_id=100))
        db.add(MlItemRelation(mla="MLA2374249178", related_mla="MLA3100873948", stock_relation=1))
        db.commit()

        anomalies = audit.list_anomalies(db)

        assert len(anomalies) == 1
        anomaly = anomalies[0]
        assert anomaly.mla == "MLA2374249178"
        assert anomaly.item_id == 100
        assert anomaly.related_mla == "MLA3100873948"
        assert anomaly.related_item_id is None
        assert anomaly.reason == "unresolvable"

    def test_mixed_edges_only_anomalies_listed(self, db) -> None:
        _seed_producto(db, 100)
        _seed_producto(db, 200)
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(PublicacionML(mla="MLA_B", item_id=100))
        db.add(PublicacionML(mla="MLA_C", item_id=200))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_B", stock_relation=1))  # same item — not listed
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_C", stock_relation=1))  # cross item
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_UNKNOWN", stock_relation=None))  # unresolvable
        db.commit()

        anomalies = audit.list_anomalies(db)

        assert len(anomalies) == 2
        reasons = {a.reason for a in anomalies}
        assert reasons == {"cross_item", "unresolvable"}
