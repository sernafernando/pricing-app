"""Model tests for the ML operations source-of-truth tables (slice 1).

Slice 1 only proves the schema: table/column existence, tz-aware
`DateTime(timezone=True)` columns, and the unique constraints. No reader or
writer exists yet — that is intentional, exactly like the tn_image_normalizer
precedent (slice 3 of that change).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.models.ml_orders_ops import (
    MlOperationLink,
    MlOrderItemOps,
    MlOrdersOps,
    MlOpsDivergence,
    MlOpsSyncCursor,
    MlShipmentOps,
)


def _tz_aware_columns(model) -> set[str]:
    return {
        col.name for col in model.__table__.columns if isinstance(col.type, sa.DateTime) and col.type.timezone is True
    }


class TestMlOrdersOps:
    def test_table_name(self) -> None:
        assert MlOrdersOps.__tablename__ == "ml_orders_ops"

    def test_order_id_is_primary_key(self) -> None:
        pk_columns = [c.name for c in MlOrdersOps.__table__.primary_key.columns]
        assert pk_columns == ["order_id"]

    def test_expected_columns_exist(self) -> None:
        columns = {c.name for c in MlOrdersOps.__table__.columns}
        expected = {
            "order_id",
            "pack_id",
            "status",
            "status_detail",
            "date_created",
            "date_closed",
            "ml_last_updated",
            "buyer_id",
            "buyer_nickname",
            "seller_id",
            "total_amount",
            "paid_amount",
            "currency_id",
            "shipping_id",
            "tags",
            "raw_order",
            "ingest_error",
            "first_seen_at",
            "last_synced_at",
        }
        assert expected.issubset(columns)

    def test_timestamp_columns_are_timezone_aware(self) -> None:
        tz_cols = _tz_aware_columns(MlOrdersOps)
        for col in (
            "date_created",
            "date_closed",
            "ml_last_updated",
            "first_seen_at",
            "last_synced_at",
        ):
            assert col in tz_cols, f"{col} must be DateTime(timezone=True)"

    def test_create_row(self, db) -> None:
        row = MlOrdersOps(
            order_id=1234567890,
            status="paid",
            ml_last_updated=datetime(2026, 8, 1, tzinfo=timezone.utc),
            seller_id=2645,
        )
        db.add(row)
        db.flush()

        assert row.order_id == 1234567890

    def test_seller_id_is_not_nullable(self, db) -> None:
        row = MlOrdersOps(
            order_id=1234567891,
            status="paid",
            ml_last_updated=datetime(2026, 8, 1, tzinfo=timezone.utc),
            seller_id=None,
        )
        db.add(row)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestMlOrderItemOps:
    def test_table_name(self) -> None:
        assert MlOrderItemOps.__tablename__ == "ml_order_items_ops"

    def test_no_cost_columns(self) -> None:
        """Design invariant: this table carries ZERO cost columns."""
        columns = {c.name for c in MlOrderItemOps.__table__.columns}
        forbidden = {"cost", "costo", "prli_id", "cust_id", "margin", "markup"}
        assert not (columns & forbidden)

    def test_unique_constraint_columns(self) -> None:
        uniques = [c for c in MlOrderItemOps.__table__.constraints if isinstance(c, sa.UniqueConstraint)]
        assert uniques, "expected a UniqueConstraint on (order_id, item_id, variation_id)"
        cols = {frozenset(col.name for col in uc.columns) for uc in uniques}
        assert frozenset({"order_id", "item_id", "variation_id"}) in cols

    def test_create_row(self, db) -> None:
        item = MlOrderItemOps(
            order_id=1234567890,
            item_id="MLA123456789",
            quantity=1,
            unit_price=1000,
        )
        db.add(item)
        db.flush()

        assert item.id is not None

    def test_duplicate_order_item_variation_violates_unique_constraint(self, db) -> None:
        db.add(
            MlOrderItemOps(
                order_id=1,
                item_id="MLA1",
                variation_id=10,
                quantity=1,
                unit_price=100,
            )
        )
        db.flush()

        db.add(
            MlOrderItemOps(
                order_id=1,
                item_id="MLA1",
                variation_id=10,
                quantity=2,
                unit_price=100,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestMlShipmentOps:
    def test_table_name(self) -> None:
        assert MlShipmentOps.__tablename__ == "ml_shipments_ops"

    def test_shipment_id_is_primary_key(self) -> None:
        pk_columns = [c.name for c in MlShipmentOps.__table__.primary_key.columns]
        assert pk_columns == ["shipment_id"]

    def test_timestamp_columns_are_timezone_aware(self) -> None:
        tz_cols = _tz_aware_columns(MlShipmentOps)
        for col in ("date_created", "last_updated", "last_synced_at"):
            assert col in tz_cols

    def test_create_row(self, db) -> None:
        shipment = MlShipmentOps(shipment_id=555, order_id=1, status="shipped")
        db.add(shipment)
        db.flush()

        assert shipment.shipment_id == 555


class TestMlOperationLink:
    def test_table_name(self) -> None:
        assert MlOperationLink.__tablename__ == "ml_operation_links"

    def test_unique_constraint_columns(self) -> None:
        uniques = [c for c in MlOperationLink.__table__.constraints if isinstance(c, sa.UniqueConstraint)]
        cols = {frozenset(col.name for col in uc.columns) for uc in uniques}
        assert frozenset({"entity_type", "entity_id", "order_id"}) in cols

    def test_create_row(self, db) -> None:
        link = MlOperationLink(
            order_id=1,
            entity_type="claim",
            entity_id=999,
            link_source="claim_resource_id",
            link_confidence="exact",
        )
        db.add(link)
        db.flush()

        assert link.id is not None

    def test_duplicate_link_violates_unique_constraint(self, db) -> None:
        db.add(
            MlOperationLink(
                order_id=1,
                entity_type="claim",
                entity_id=999,
                link_source="claim_resource_id",
                link_confidence="exact",
            )
        )
        db.flush()

        db.add(
            MlOperationLink(
                order_id=1,
                entity_type="claim",
                entity_id=999,
                link_source="manual",
                link_confidence="inferred",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestMlOpsSyncCursor:
    def test_table_name(self) -> None:
        assert MlOpsSyncCursor.__tablename__ == "ml_ops_sync_cursor"

    def test_name_is_primary_key(self) -> None:
        pk_columns = [c.name for c in MlOpsSyncCursor.__table__.primary_key.columns]
        assert pk_columns == ["name"]

    def test_create_row(self, db) -> None:
        cursor = MlOpsSyncCursor(name="sweep", state="idle")
        db.add(cursor)
        db.flush()

        assert cursor.name == "sweep"


class TestMlOpsDivergence:
    def test_table_name(self) -> None:
        assert MlOpsDivergence.__tablename__ == "ml_ops_divergence"

    def test_unique_constraint_columns(self) -> None:
        uniques = [c for c in MlOpsDivergence.__table__.constraints if isinstance(c, sa.UniqueConstraint)]
        cols = {frozenset(col.name for col in uc.columns) for uc in uniques}
        assert frozenset({"order_id", "kind", "field"}) in cols

    def test_state_defaults_to_open(self, db) -> None:
        row = MlOpsDivergence(order_id=1, kind="field_mismatch", field="status")
        db.add(row)
        db.flush()
        db.refresh(row)

        assert row.state == "open"

    def test_out_of_window_update_kind_is_representable(self, db) -> None:
        """Cross-slice contract (obs 1828): the out-of-window counter reuses
        this table with kind='out_of_window_update' — no dedicated table."""
        row = MlOpsDivergence(
            order_id=42,
            kind="out_of_window_update",
            field=None,
        )
        db.add(row)
        db.flush()

        assert row.id is not None

    def test_duplicate_order_kind_field_violates_unique_constraint(self, db) -> None:
        db.add(MlOpsDivergence(order_id=1, kind="field_mismatch", field="status"))
        db.flush()

        db.add(MlOpsDivergence(order_id=1, kind="field_mismatch", field="status"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_kind_check_constraint_exists(self) -> None:
        checks = [c for c in MlOpsDivergence.__table__.constraints if isinstance(c, sa.CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_ml_ops_divergence_kind" in names
        assert "ck_ml_ops_divergence_state" in names

    def test_invalid_kind_is_rejected(self, db) -> None:
        """Slice 3 is the first writer of `kind` (the out-of-window
        counter). A comment-only contract leaked 9 ways in slice 2 (obs
        #1843) -- this must be a real constraint, not documentation."""
        db.add(MlOpsDivergence(order_id=1, kind="not_a_real_kind"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_invalid_state_is_rejected(self, db) -> None:
        db.add(MlOpsDivergence(order_id=1, kind="field_mismatch", field="status", state="not_a_real_state"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
