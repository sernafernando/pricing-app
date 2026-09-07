"""ml-ventas-desglose-costos corte 5, post-review fix: payments_synced_at
retry gate on ml_orders_ops

Revision ID: 20260907_ml_orders_ops_payments_synced_at
Revises: 20260907_ml_payments_ops
Create Date: 2026-09-07

The sweep's original trigger for fetching `order.payments[]` was
`UpsertOutcome.OK`, a one-shot event: a payment fetch that failed on the
same pass the order itself upserted successfully was never retried, since
the next pass finds the order no longer stale and never asks for its
payments again. Adds `payments_synced_at`, the same retry-gate pattern as
`ml_shipments_ops.costs_synced_at` (corte 1/4): NULL until every one of
that order's payments has been fetched and persisted at least once,
independent of the order's own staleness.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_ml_orders_ops_payments_synced_at"
down_revision: Union[str, None] = "20260907_ml_payments_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_orders_ops", sa.Column("payments_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_orders_ops", "payments_synced_at")
