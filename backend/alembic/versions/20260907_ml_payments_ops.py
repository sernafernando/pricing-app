"""ml-ventas-desglose-costos corte 5: Mercado Pago payment ingestion

Revision ID: 20260907_ml_payments_ops
Revises: 20260907_ml_billing_period_stats_unique
Create Date: 2026-09-07

Adds `ml_payments_ops` (one row per MP payment) and `ml_payment_charges`
(one row per charge line inside a payment, stored verbatim and
unfiltered -- see `app/models/ml_payments.py` module docstring). No
existing table is touched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_ml_payments_ops"
down_revision: Union[str, None] = "20260907_ml_billing_period_stats_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_payments_ops",
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("transaction_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("shipping_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("coupon_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_paid_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_received_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("transaction_amount_refunded", sa.Numeric(14, 2), nullable=True),
        sa.Column("taxes_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_id", sa.String(length=10), nullable=True),
        sa.Column("date_approved", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("payment_id"),
    )
    op.create_index("ix_ml_payments_ops_order_id", "ml_payments_ops", ["order_id"])

    op.create_table(
        "ml_payment_charges",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("refunded", sa.Numeric(14, 2), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["payment_id"], ["ml_payments_ops.payment_id"]),
        sa.UniqueConstraint("payment_id", "name", "type", name="uq_ml_payment_charges_payment_name_type"),
    )
    op.create_index("ix_ml_payment_charges_payment_id", "ml_payment_charges", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_payment_charges_payment_id", table_name="ml_payment_charges")
    op.drop_table("ml_payment_charges")
    op.drop_index("ix_ml_payments_ops_order_id", table_name="ml_payments_ops")
    op.drop_table("ml_payments_ops")
