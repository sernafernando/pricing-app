"""CHECK constraints for `ml_operation_links` (slice 4 of ml-ventas-fuente-de-verdad).

`entity_type`, `link_source`, and `link_confidence` documented their valid
values in a comment only (slice 1, nothing wrote to them). Slice 4's link
resolver is the first writer, so per the change's own instructions (and the
slice-3 lesson, obs #1843/#1852) the contract must become a real CHECK
constraint in the same slice that starts writing, not stay a comment.
"""

import sqlalchemy as sa
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.ml_orders_ops import MlOperationLink


class TestEntityTypeConstraint:
    def test_check_constraint_exists(self) -> None:
        checks = [c for c in MlOperationLink.__table__.constraints if isinstance(c, sa.CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_ml_operation_links_entity_type" in names

    def test_valid_entity_types_are_accepted(self, db) -> None:
        for i, entity_type in enumerate(("claim", "question", "message")):
            db.add(
                MlOperationLink(
                    order_id=100 + i,
                    entity_type=entity_type,
                    entity_id=1,
                    link_source="manual",
                    link_confidence="exact",
                )
            )
        db.flush()

    def test_invalid_entity_type_is_rejected(self, db) -> None:
        db.add(
            MlOperationLink(
                order_id=1,
                entity_type="not_a_real_entity_type",
                entity_id=1,
                link_source="manual",
                link_confidence="exact",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestLinkSourceConstraint:
    def test_check_constraint_exists(self) -> None:
        checks = [c for c in MlOperationLink.__table__.constraints if isinstance(c, sa.CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_ml_operation_links_link_source" in names

    def test_valid_link_sources_are_accepted(self, db) -> None:
        for i, link_source in enumerate(("claim_resource_id", "pack_id", "item_id", "manual")):
            db.add(
                MlOperationLink(
                    order_id=200 + i,
                    entity_type="claim",
                    entity_id=1,
                    link_source=link_source,
                    link_confidence="exact",
                )
            )
        db.flush()

    def test_invalid_link_source_is_rejected(self, db) -> None:
        db.add(
            MlOperationLink(
                order_id=1,
                entity_type="claim",
                entity_id=1,
                link_source="not_a_real_source",
                link_confidence="exact",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestLinkConfidenceConstraint:
    def test_check_constraint_exists(self) -> None:
        checks = [c for c in MlOperationLink.__table__.constraints if isinstance(c, sa.CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_ml_operation_links_link_confidence" in names

    def test_valid_confidences_are_accepted(self, db) -> None:
        for i, confidence in enumerate(("exact", "inferred")):
            db.add(
                MlOperationLink(
                    order_id=300 + i,
                    entity_type="claim",
                    entity_id=1,
                    link_source="manual",
                    link_confidence=confidence,
                )
            )
        db.flush()

    def test_invalid_confidence_is_rejected(self, db) -> None:
        db.add(
            MlOperationLink(
                order_id=1,
                entity_type="claim",
                entity_id=1,
                link_source="manual",
                link_confidence="not_a_real_confidence",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
