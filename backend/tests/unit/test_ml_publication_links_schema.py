"""
Unit tests — `MlPublicationLink` / `MlItemRelation` ORM models
(productos-catalog-family-tree PR1a).

Verifies table names, column types/nullability, and the unique constraint on
`ml_item_relations(mla, related_mla)`. These tables are intentionally
separate from `tb_mercadolibre_items_publicados` (see model docstrings) so
the ERP incremental sync's `setattr` loop never clobbers them (no-clobber
behavior itself is covered in PR1b's `test_erp_sync_no_clobber.py`).
"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.exc import IntegrityError
import pytest

from app.models.ml_publication_link import MlPublicationLink
from app.models.ml_item_relation import MlItemRelation


class TestMlPublicationLinkModel:
    def test_tablename(self) -> None:
        assert MlPublicationLink.__tablename__ == "ml_publication_links"

    def test_columns_exist_with_expected_types(self) -> None:
        columns = MlPublicationLink.__table__.c

        assert isinstance(columns["mla"].type, String)
        assert columns["mla"].primary_key is True
        assert columns["mla"].nullable is False

        assert isinstance(columns["family_id"].type, String)
        assert columns["family_id"].nullable is True
        assert columns["family_id"].index is True

        assert isinstance(columns["user_product_id"].type, String)
        assert columns["user_product_id"].nullable is True

        assert isinstance(columns["inventory_id"].type, String)
        assert columns["inventory_id"].nullable is True

        assert isinstance(columns["catalog_listing"].type, Boolean)
        assert columns["catalog_listing"].nullable is True

        assert isinstance(columns["catalog_product_id"].type, String)
        assert columns["catalog_product_id"].nullable is True

        assert isinstance(columns["item_id"].type, Integer)
        assert columns["item_id"].index is True

        assert isinstance(columns["fetched_at"].type, DateTime)

    def test_insert_and_read_round_trip(self, db) -> None:
        row = MlPublicationLink(
            mla="MLA123456789",
            family_id="FAM1",
            catalog_listing=True,
            catalog_product_id="CATPROD1",
            item_id=42,
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlPublicationLink).filter_by(mla="MLA123456789").first()
        assert retrieved is not None
        assert retrieved.family_id == "FAM1"
        assert retrieved.catalog_listing is True

    def test_mla_is_unique_primary_key(self, db) -> None:
        db.add(MlPublicationLink(mla="MLA_DUP"))
        db.flush()
        db.add(MlPublicationLink(mla="MLA_DUP"))
        with pytest.raises(IntegrityError):
            db.flush()


class TestMlItemRelationModel:
    def test_tablename(self) -> None:
        assert MlItemRelation.__tablename__ == "ml_item_relations"

    def test_columns_exist_with_expected_types(self) -> None:
        columns = MlItemRelation.__table__.c

        assert columns["id"].primary_key is True
        assert isinstance(columns["mla"].type, String)
        assert columns["mla"].nullable is False
        assert columns["mla"].index is True

        assert isinstance(columns["related_mla"].type, String)
        assert columns["related_mla"].nullable is False
        assert columns["related_mla"].index is True

        assert isinstance(columns["stock_relation"].type, Integer)
        assert columns["stock_relation"].nullable is True

        assert isinstance(columns["variation_id"].type, String)
        assert columns["variation_id"].nullable is True

    def test_unique_constraint_on_mla_related_mla(self, db) -> None:
        db.add(MlItemRelation(mla="MLA1", related_mla="MLA2", stock_relation=1))
        db.flush()
        db.add(MlItemRelation(mla="MLA1", related_mla="MLA2", stock_relation=2))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_allows_multiple_relations_per_mla(self, db) -> None:
        db.add(MlItemRelation(mla="MLA1", related_mla="MLA2"))
        db.add(MlItemRelation(mla="MLA1", related_mla="MLA3"))
        db.flush()

        rows = db.query(MlItemRelation).filter_by(mla="MLA1").all()
        assert len(rows) == 2
