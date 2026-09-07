"""ml-ventas-desglose-costos corte 1: shipping cost columns on ml_shipments_ops

Revision ID: 20260904_ml_shipments_ops_costs
Revises: 20260904_ml_billing_schema
Create Date: 2026-09-04

Additive-only migration. Adds `sender_cost`, `receiver_cost`, and
`costs_synced_at` to the existing `ml_shipments_ops` table so a later cut
can persist the shipment-level cost split without another migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_ml_shipments_ops_costs"
down_revision: Union[str, None] = "20260904_ml_billing_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_shipments_ops", sa.Column("sender_cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("ml_shipments_ops", sa.Column("receiver_cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("ml_shipments_ops", sa.Column("costs_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_shipments_ops", "costs_synced_at")
    op.drop_column("ml_shipments_ops", "receiver_cost")
    op.drop_column("ml_shipments_ops", "sender_cost")
