"""index on ml_order_item_costos.producto_item_id

Revision ID: 20260922_ix_producto_item_id
Revises: 20260922_ml_order_metrics
Create Date: 2026-09-22

ventas-ml-rediseno / PR8b (spec PFILT R43). The Ventas ML product facets
(marca, subcategoría, PM) all reach the product through
`ml_order_item_costos.producto_item_id`, which had no index. Index-only
migration, shipped and deployed BEFORE the PR that adds those joins.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260922_ix_producto_item_id"
down_revision: Union[str, None] = "20260922_ml_order_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ix_ml_order_item_costos_producto_item_id"


def upgrade() -> None:
    # `if_not_exists`: the ORM model declares it too, so a schema built by
    # `create_all` (the test fixtures) already has it.
    op.create_index(_INDEX, "ml_order_item_costos", ["producto_item_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="ml_order_item_costos", if_exists=True)
