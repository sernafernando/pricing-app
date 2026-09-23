"""order_metrics enqueue functions + per-order row triggers (ventas-ml-rediseno PR4)

Revision ID: 20260923_ml_order_metrics_triggers_orders
Revises: 20260922_ix_producto_item_id
Create Date: 2026-09-23

Design D3, D7, D8. Postgres-only: two PL/pgSQL enqueue helpers
(`order_metrics_enqueue` for input writes, `order_metrics_enqueue_system`
for reconcile/divergence) plus row-level triggers on the six per-order
input tables (`ml_orders_ops`, `ml_order_items_ops`, `ml_order_item_costos`,
`ml_payments_ops`, `ml_payment_charges`, `ml_shipments_ops`).

DDL is shared with `app/services/order_metrics/triggers.py` -- the SAME
`create_triggers`/`drop_triggers` this migration calls are what that
module's `after_create`/`before_drop` listener also applies for
`@pytest.mark.postgres` test fixtures (design D8), so there is exactly ONE
copy of this DDL, never a second one drifting in the migration file.

This is the ONLY writer that starts producing dirty rows in production: the
worker (PR2/PR3) and its `order_metrics.drain` handler are already deployed
and idle. The moment this migration lands, real enqueues start flowing.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from app.services.order_metrics.triggers import create_triggers, drop_triggers

# revision identifiers, used by Alembic.
revision: str = "20260923_ml_order_metrics_triggers_orders"
down_revision: Union[str, None] = "20260922_ix_producto_item_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    create_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    drop_triggers(bind)
