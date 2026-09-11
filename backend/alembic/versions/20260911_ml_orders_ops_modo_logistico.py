"""ml-ventas-modo-logistico PR1: has_no_shipping_tag on ml_orders_ops

Revision ID: 20260911_modo_logistico
Revises: 20260909_activity_cursor
Create Date: 2026-09-11

Adds the derived `has_no_shipping_tag` boolean, written at ingestion time
from `dto.tags` (design D1/design doc: a derived column, chosen over a
read-time Postgres JSONB containment query on `raw_order->tags`, because
SQLite tests cannot exercise that query -- a read-time rule would ship
proven by a test running a different query than production).

The resolved mode itself gets NO column: the API recomputes the cascade
live from the joined shipment row, so nothing reads a stored copy. A
nullable add with no backfill -- existing rows read as false until their
next re-ingest touches them, which matches "no tag observed yet".
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


def downgrade() -> None:
    op.drop_column("ml_orders_ops", "has_no_shipping_tag")
