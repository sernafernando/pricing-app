"""ml_sale_lines: the persisted per-sold-line base of the Métricas ML board

The board computed `sales.sale_lines` (groups x orders x items x frozen costs x
metrics, with two window functions) and `sales.last_sales` (the same join over
ALL history) on every request: about 530 ms of a 1.0 s request at production
volume. The lines are now stored, one row per sold item line, by the
`order_metrics.drain` transaction that stores the order's metrics (see
`app.models.ml_sale_line`). Reading them back costs about 100 ms.

The table is created empty (a catalog change, no lock beyond the CREATE). The
backfill is `order_metrics.reconcile`: this release bumps
`CURRENT_FORMULA_VERSION`, so every order is re-enqueued at the low "reconcile"
priority and the drain writes its lines along with its metrics.

Revision ID: 20261018_ml_sale_lines
Revises: 20261017_ml_items_installments_campaign
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261018_ml_sale_lines"
down_revision: Union[str, None] = "20261017_ml_items_installments_campaign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_sale_lines",
        sa.Column("item_row_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("group_key", sa.String(length=32), nullable=False),
        sa.Column("product", sa.Integer(), nullable=False),
        sa.Column("mla", sa.String(length=20), nullable=False),
        sa.Column("group_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("gross", sa.Numeric(), nullable=False),
        sa.Column("tg", sa.Numeric(), nullable=False),
        sa.Column("mtg", sa.Numeric(), nullable=False),
        sa.Column("mcosto", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["item_row_id"], ["ml_order_items_ops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_row_id"),
    )
    op.create_index("ix_ml_sale_lines_group_date", "ml_sale_lines", ["group_date"])
    op.create_index("ix_ml_sale_lines_group_key", "ml_sale_lines", ["group_key"])
    op.create_index("ix_ml_sale_lines_order_id", "ml_sale_lines", ["order_id"])
    op.create_index("ix_ml_sale_lines_product_group_date", "ml_sale_lines", ["product", "group_date"])


def downgrade() -> None:
    op.drop_table("ml_sale_lines")
