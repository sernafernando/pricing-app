"""ml_fulfillment_last_inbound: last Full inbound qty per inventory_id

Revision ID: 20261219_ml_fulfillment_last_inbound
Revises: 20261218_gestion_full_override
Create Date: 2026-10-30

Gestión Full Target: snapshot of the newest INBOUND_RECEPTION from
GET /stock/fulfillment/operations/search. History of operations can land later
in a separate table; this row is only the latest per inventory_id.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261219_ml_fulfillment_last_inbound"
down_revision: Union[str, None] = "20261218_gestion_full_override"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_fulfillment_last_inbound",
        sa.Column("inventory_id", sa.Text(), primary_key=True),
        sa.Column("cantidad", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operation_id", sa.BigInteger(), nullable=True),
        sa.Column("inbound_id", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ml_fulfillment_last_inbound_occurred_at",
        "ml_fulfillment_last_inbound",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ml_fulfillment_last_inbound_occurred_at",
        table_name="ml_fulfillment_last_inbound",
    )
    op.drop_table("ml_fulfillment_last_inbound")
