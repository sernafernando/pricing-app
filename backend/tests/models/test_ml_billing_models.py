"""Model tests for the ML billing/cost-breakdown schema (corte 1 of
ml-ventas-desglose-costos).

Corte 1 only proves the schema: table/column existence, types, and
constraints. No reader, writer, mapper, or client exists yet -- that is
intentional, exactly like the ml_orders_ops slice-1 precedent.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.models.ml_billing import (
    MlBillingCharge,
    MlBillingChargeOrder,
    MlBillingPeriodStat,
    MlIibbAliquot,
)


class TestMlBillingCharge:
    def test_table_name(self) -> None:
        assert MlBillingCharge.__tablename__ == "ml_billing_charges"

    def test_detail_id_is_primary_key(self) -> None:
        pk_columns = [c.name for c in MlBillingCharge.__table__.primary_key.columns]
        assert pk_columns == ["detail_id"]

    def test_detail_id_column_type(self) -> None:
        col = MlBillingCharge.__table__.columns["detail_id"]
        assert isinstance(col.type, sa.String)
        assert col.type.length == 60

    def test_amount_column_type(self) -> None:
        col = MlBillingCharge.__table__.columns["amount"]
        assert isinstance(col.type, sa.Numeric)
        assert col.type.precision == 14
        assert col.type.scale == 2

    def test_raw_detail_is_jsonb(self) -> None:
        from sqlalchemy.dialects.postgresql import JSONB

        col = MlBillingCharge.__table__.columns["raw_detail"]
        # Session-scoped `engine` fixture rewrites JSONB -> a SQLite-compatible
        # JSON type in-place for the whole test session (see conftest
        # `_patch_pg_types_for_sqlite`), so this column's runtime type depends
        # on collection order across the suite. Assert against the model
        # source of truth instead of live metadata.
        import inspect

        source = inspect.getsource(MlBillingCharge)
        assert "raw_detail = Column(JSONB" in source
        assert isinstance(col.type, JSONB) or col.type.__class__.__name__ == "JSON"

    def test_create_row_with_signed_amount(self, db) -> None:
        charge = MlBillingCharge(
            detail_id="ML123456789-shipping",
            period_key="2026-09",
            detail_type="shipping",
            detail_sub_type="forward",
            amount=-1234.56,
            document_id="DOC-1",
            raw_detail={"foo": "bar"},
        )
        db.add(charge)
        db.flush()

        assert charge.detail_id == "ML123456789-shipping"
        assert charge.amount == pytest.approx(-1234.56)


class TestMlBillingChargeOrder:
    def test_table_name(self) -> None:
        assert MlBillingChargeOrder.__tablename__ == "ml_billing_charge_orders"

    def test_unique_constraint_columns(self) -> None:
        uniques = [c for c in MlBillingChargeOrder.__table__.constraints if isinstance(c, sa.UniqueConstraint)]
        cols = {frozenset(col.name for col in uc.columns) for uc in uniques}
        assert frozenset({"detail_id", "order_id"}) in cols

    def test_order_id_has_index(self) -> None:
        indexes = MlBillingChargeOrder.__table__.indexes
        indexed_cols = {frozenset(col.name for col in idx.columns) for idx in indexes}
        assert frozenset({"order_id"}) in indexed_cols

    def test_one_detail_id_links_to_three_distinct_orders(self, db) -> None:
        """Support of a pack's shipping charge: a single billing detail_id
        can settle across multiple orders in the same pack."""
        db.add(
            MlBillingCharge(
                detail_id="ML-pack-shipping-1",
                period_key="2026-09",
                detail_type="shipping",
                amount=-900.00,
            )
        )
        db.flush()

        for order_id in (111, 222, 333):
            db.add(MlBillingChargeOrder(detail_id="ML-pack-shipping-1", order_id=order_id))
        db.flush()

        linked = db.query(MlBillingChargeOrder).filter(MlBillingChargeOrder.detail_id == "ML-pack-shipping-1").all()
        assert {row.order_id for row in linked} == {111, 222, 333}

    def test_duplicate_detail_order_violates_unique_constraint(self, db) -> None:
        db.add(
            MlBillingCharge(
                detail_id="ML-dup",
                period_key="2026-09",
                detail_type="shipping",
                amount=-100.00,
            )
        )
        db.flush()

        db.add(MlBillingChargeOrder(detail_id="ML-dup", order_id=1))
        db.flush()

        db.add(MlBillingChargeOrder(detail_id="ML-dup", order_id=1))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestMlIibbAliquot:
    def test_table_name(self) -> None:
        assert MlIibbAliquot.__tablename__ == "ml_iibb_aliquots"

    def test_porcentaje_column_type(self) -> None:
        col = MlIibbAliquot.__table__.columns["porcentaje"]
        assert isinstance(col.type, sa.Numeric)
        assert col.type.precision == 6
        assert col.type.scale == 4

    def test_fecha_desde_not_nullable(self) -> None:
        col = MlIibbAliquot.__table__.columns["fecha_desde"]
        assert col.nullable is False

    def test_fecha_hasta_nullable(self) -> None:
        col = MlIibbAliquot.__table__.columns["fecha_hasta"]
        assert col.nullable is True

    def test_creado_por_is_foreign_key_to_usuarios(self) -> None:
        col = MlIibbAliquot.__table__.columns["creado_por"]
        fks = list(col.foreign_keys)
        assert fks
        assert fks[0].target_fullname == "usuarios.id"

    def test_create_row(self, db) -> None:
        row = MlIibbAliquot(
            porcentaje=2.5,
            fecha_desde=date(2026, 1, 1),
        )
        db.add(row)
        db.flush()

        assert row.id is not None

    def test_fecha_hasta_before_fecha_desde_violates_check(self, db) -> None:
        row = MlIibbAliquot(
            porcentaje=2.5,
            fecha_desde=date(2026, 1, 10),
            fecha_hasta=date(2026, 1, 10) - timedelta(days=1),
        )
        db.add(row)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestMlBillingPeriodStat:
    def test_table_name(self) -> None:
        assert MlBillingPeriodStat.__tablename__ == "ml_billing_period_stats"

    def test_expected_columns_exist(self) -> None:
        columns = {c.name for c in MlBillingPeriodStat.__table__.columns}
        expected = {
            "period_key",
            "reported_total",
            "stored_total",
            "documents_count_details",
            "swept_at",
        }
        assert expected.issubset(columns)

    def test_create_row(self, db) -> None:
        row = MlBillingPeriodStat(
            period_key="2026-09",
            reported_total=1000.00,
            stored_total=998.50,
            documents_count_details=42,
        )
        db.add(row)
        db.flush()

        assert row.id is not None
