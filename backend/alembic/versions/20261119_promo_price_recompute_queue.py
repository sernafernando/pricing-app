"""promo_price_recompute_queue: items ml-webhook asks to recompute right away

Revision ID: 20261119_promo_price_recompute_queue
Revises: 20261118_ventas_fuera_pdf_operaciones
Create Date: 2026-11-16

promo-ml-precio-inmediato T1. `POST /api/promociones/recompute-precios` upserts one row per item;
the `promo_price.recompute` ML worker handler drains it with `recompute_item`. New empty table, no
data touched; the downgrade drops it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_promo_price_recompute_queue"
down_revision: Union[str, None] = "20261118_ventas_fuera_pdf_operaciones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_price_recompute_queue",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("promo_price_recompute_queue")
