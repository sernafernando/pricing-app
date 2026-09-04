"""ml-ventas-desglose-costos corte 1: ML billing / cost-breakdown schema

Revision ID: 20260904_ml_billing_schema
Revises: 20260903_markup_masivo
Create Date: 2026-09-04

Additive-only migration. Creates four new tables sourced from the ML
billing API (via the ml-webhook proxy), independent of GBP. No existing
table is altered. Nothing writes to these tables yet -- no reader, writer,
mapper, or client exists in this cut, exactly like the ml_orders_ops
slice-1 precedent.

Tables:
- ml_billing_charges        one row per ML billing detail line, PK detail_id
- ml_billing_charge_orders  bridge table: one detail_id can link to several
                             order_id (e.g. a pack's shipping charge)
- ml_iibb_aliquots          IIBB aliquot with a fecha_desde/fecha_hasta
                             validity window (clones pricing_constants)
- ml_billing_period_stats   reconciliation totals per ML billing period
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260904_ml_billing_schema"
down_revision: Union[str, None] = "20260903_markup_masivo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_billing_charges",
        sa.Column("detail_id", sa.String(length=60), nullable=False),
        sa.Column("period_key", sa.String(length=10), nullable=True),
        sa.Column("detail_type", sa.String(length=60), nullable=True),
        sa.Column("detail_sub_type", sa.String(length=60), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("document_id", sa.String(length=60), nullable=True),
        sa.Column("raw_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("detail_id"),
    )
    op.create_index("ix_ml_billing_charges_period_key", "ml_billing_charges", ["period_key"])
    op.create_index("ix_ml_billing_charges_detail_type", "ml_billing_charges", ["detail_type"])

    op.create_table(
        "ml_billing_charge_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("detail_id", sa.String(length=60), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["detail_id"], ["ml_billing_charges.detail_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("detail_id", "order_id", name="uq_ml_billing_charge_orders_detail_order"),
    )
    op.create_index("ix_ml_billing_charge_orders_order_id", "ml_billing_charge_orders", ["order_id"])

    op.create_table(
        "ml_iibb_aliquots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("porcentaje", sa.Numeric(6, 4), nullable=False),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["creado_por"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="chk_ml_iibb_aliquots_fecha_hasta"
        ),
    )

    op.create_table(
        "ml_billing_period_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(length=10), nullable=False),
        sa.Column("reported_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("stored_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("documents_count_details", sa.Integer(), nullable=True),
        sa.Column("swept_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ml_billing_period_stats_period_key", "ml_billing_period_stats", ["period_key"])


def downgrade() -> None:
    op.drop_index("ix_ml_billing_period_stats_period_key", table_name="ml_billing_period_stats")
    op.drop_table("ml_billing_period_stats")

    op.drop_table("ml_iibb_aliquots")

    op.drop_index("ix_ml_billing_charge_orders_order_id", table_name="ml_billing_charge_orders")
    op.drop_table("ml_billing_charge_orders")

    op.drop_index("ix_ml_billing_charges_detail_type", table_name="ml_billing_charges")
    op.drop_index("ix_ml_billing_charges_period_key", table_name="ml_billing_charges")
    op.drop_table("ml_billing_charges")
