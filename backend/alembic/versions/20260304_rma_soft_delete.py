"""Add soft delete columns to rma_casos: activo, eliminado_por_id, eliminado_at, eliminado_motivo

Revision ID: 20260304_rma_soft_delete
Revises: 20260304_rma_claims_ml
Create Date: 2026-03-04

"""

from alembic import op
import sqlalchemy as sa

revision = "20260304_rma_soft_delete"
down_revision = "20260304_rma_claims_ml"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rma_casos",
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index("ix_rma_casos_activo", "rma_casos", ["activo"])

    op.add_column(
        "rma_casos",
        sa.Column("eliminado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
    )
    op.add_column(
        "rma_casos",
        sa.Column("eliminado_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rma_casos",
        sa.Column("eliminado_motivo", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rma_casos", "eliminado_motivo")
    op.drop_column("rma_casos", "eliminado_at")
    op.drop_column("rma_casos", "eliminado_por_id")
    op.drop_index("ix_rma_casos_activo", table_name="rma_casos")
    op.drop_column("rma_casos", "activo")
