"""gestion_full_override: PM qty override per Full inventory_id

Revision ID: 20261218_gestion_full_override
Revises: 20261217_drop_sell_in_compras_pedido_compra_id
Create Date: 2026-10-30

Gestión Full (Reportes): one optional integer override per MercadoLibre
`inventory_id`. Viewers see all rows; only PM/sub-PM for the product's
(marca, categoria) or full-view roles may write. Clearing the override
deletes the row.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261218_gestion_full_override"
down_revision: Union[str, None] = "20261217_drop_sell_in_compras_pedido_compra_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gestion_full_override",
        sa.Column("inventory_id", sa.Text(), primary_key=True),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["usuarios.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_gestion_full_override_updated_by_id",
        "gestion_full_override",
        ["updated_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gestion_full_override_updated_by_id", table_name="gestion_full_override")
    op.drop_table("gestion_full_override")
