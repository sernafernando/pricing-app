"""ml-ventas-modo-logistico PR1: modo_logistico + has_no_shipping_tag on
ml_orders_ops

Revision ID: 20260911_modo_logistico
Revises: 20260909_activity_cursor
Create Date: 2026-09-11

Adds the derived `has_no_shipping_tag` boolean, written at ingestion time
from `dto.tags` (design D1/design doc: a derived column, chosen over a
read-time Postgres JSONB containment query on `raw_order->tags`, because
SQLite tests cannot exercise that query -- a read-time rule would ship
proven by a test running a different query than production). `modo_logistico`
stores the resolved cascade (shipment `logistic_type` -> tag ->
"desconocido"), also written at ingestion. Both nullable adds, no backfill:
existing rows resolve lazily to `desconocido`/false until their next
re-ingest touches them.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_modo_logistico"
down_revision: Union[str, None] = "20260909_activity_cursor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_orders_ops", sa.Column("has_no_shipping_tag", sa.Boolean(), nullable=True))
    op.add_column("ml_orders_ops", sa.Column("modo_logistico", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_orders_ops", "modo_logistico")
    op.drop_column("ml_orders_ops", "has_no_shipping_tag")
