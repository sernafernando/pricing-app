"""payments_recheck_at column on ml_orders_ops (repreguntar-pagos-diferido)

Revision ID: 20260918_payments_recheck_at
Revises: 20260916_total_gauss_provisorio
Create Date: 2026-09-18

Explicit deferred re-ask for `order.payments[]` (product owner's design,
verbatim: "entra la venta, hacemos la consulta del pago y hacemos un
check para que a los x minutos se consulten de nuevo"). Closes a
production gap: ML can finish processing a refund reversal (e.g. a Flex
shipping-fee charge) AFTER an order's own `ml_last_updated` stops moving,
so the sweep's two existing payment gates (staleness,
`payments_synced_at IS NULL`) never fire again for that order. This
column is set to `now + RECHECK_AFTER` the first time payments are
sealed, is a THIRD independent sweep gate, and is cleared back to NULL
once the recheck runs so it fires exactly once per order.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260918_payments_recheck_at"
down_revision: Union[str, None] = "20260916_total_gauss_provisorio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_orders_ops",
        sa.Column("payments_recheck_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ml_orders_ops_payments_recheck_at",
        "ml_orders_ops",
        ["payments_recheck_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ml_orders_ops_payments_recheck_at", table_name="ml_orders_ops")
    op.drop_column("ml_orders_ops", "payments_recheck_at")
