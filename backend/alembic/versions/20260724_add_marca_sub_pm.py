"""sub-pm-scope-marcas PR1: create marca_sub_pm table

Revision ID: 20260724_add_marca_sub_pm
Revises: 20260724_tn_category_embedding
Create Date: 2026-07-24

Delegated sub-PM scope: a (marca, categoria) pair keeps a single titular in
`marcas_pm` (unique on marca+categoria) but may now have multiple sub-PM
grants in `marca_sub_pm` (unique on marca+categoria+usuario_id — the same
pair can be delegated to several users). Effective scope for a user becomes
the UNION of both tables, resolved by `app.services.pm_scope`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_add_marca_sub_pm"
down_revision: Union[str, None] = "20260724_tn_category_embedding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marca_sub_pm",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("marca", sa.String(length=100), nullable=False),
        sa.Column("categoria", sa.String(length=100), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["creado_por"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("marca", "categoria", "usuario_id", name="marca_sub_pm_marca_categoria_usuario_key"),
    )

    op.create_index("ix_marca_sub_pm_usuario_id", "marca_sub_pm", ["usuario_id"])
    op.create_index("ix_marca_sub_pm_marca_categoria", "marca_sub_pm", ["marca", "categoria"])


def downgrade() -> None:
    op.drop_index("ix_marca_sub_pm_marca_categoria", table_name="marca_sub_pm")
    op.drop_index("ix_marca_sub_pm_usuario_id", table_name="marca_sub_pm")
    op.drop_table("marca_sub_pm")
