"""para_ganar: per-MLA criteria table

Revision ID: 20261201_para_ganar_criterios_mla
Revises: 20261204_ml_cost_sync_give_up_column
Create Date: 2026-12-01

Stores PARA GANAR advisor criteria keyed by MLA (unit of work). Product/PM
defaults come later; this table is the MLA override layer.

Chained after upstream/main head so the PR merge does not fork alembic
(was briefly parented on 20261130_tb_item_full_row while main moved ahead).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261201_para_ganar_criterios_mla"
down_revision: Union[str, None] = "20261204_ml_cost_sync_give_up_column"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "para_ganar_criterios_mla",
        sa.Column("mla", sa.String(length=32), primary_key=True),
        sa.Column("markup_min", sa.Numeric(8, 2), nullable=True),
        sa.Column("markup_max", sa.Numeric(8, 2), nullable=True),
        sa.Column("top_sellers", sa.Integer(), nullable=True),
        sa.Column("precio_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("precio_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("ganar_catalogo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ignorar_internacionales", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("descartar_stock_residual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("descartar_reputacion_baja", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("techo_monopolio", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_para_ganar_criterios_mla_updated_by_id",
        "para_ganar_criterios_mla",
        ["updated_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_para_ganar_criterios_mla_updated_by_id",
        table_name="para_ganar_criterios_mla",
    )
    op.drop_table("para_ganar_criterios_mla")
