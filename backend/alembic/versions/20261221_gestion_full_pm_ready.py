"""gestion_full_pm_ready — PM close / lock lines

Revision ID: 20261221_gestion_full_pm_ready
Revises: 20261220_gestion_full_unidades_caja
Create Date: 2026-10-31

Stores frozen qty_pm when a PM marks a (ERP, MLAU) line ready. Row presence
locks override edits until a gestor unlocks (deletes the row).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261221_gestion_full_pm_ready"
down_revision: Union[str, None] = "20261220_gestion_full_unidades_caja"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gestion_full_pm_ready",
        sa.Column("producto_item_id", sa.Integer(), nullable=False),
        sa.Column("user_product_id", sa.Text(), nullable=False),
        sa.Column("inventory_id", sa.Text(), nullable=False),
        sa.Column("qty_pm", sa.Integer(), nullable=False),
        sa.Column("ready_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "ready_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["producto_item_id"],
            ["productos_erp.item_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ready_by_id"],
            ["usuarios.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("producto_item_id", "user_product_id"),
        sa.CheckConstraint("qty_pm >= 0", name="ck_gestion_full_pm_ready_qty_ge_0"),
    )
    op.create_index(
        "ix_gestion_full_pm_ready_ready_by_id",
        "gestion_full_pm_ready",
        ["ready_by_id"],
    )
    op.create_index(
        "ix_gestion_full_pm_ready_inventory_id",
        "gestion_full_pm_ready",
        ["inventory_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gestion_full_pm_ready_inventory_id",
        table_name="gestion_full_pm_ready",
    )
    op.drop_index(
        "ix_gestion_full_pm_ready_ready_by_id",
        table_name="gestion_full_pm_ready",
    )
    op.drop_table("gestion_full_pm_ready")
