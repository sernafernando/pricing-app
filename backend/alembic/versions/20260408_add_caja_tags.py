"""Add caja_tags and caja_movimiento_tags tables + updated_at on caja_movimientos.

Revision ID: 20260408_caja_tags
Revises: 20260408_caja_seed
"""

import sqlalchemy as sa
from alembic import op

revision = "20260408_caja_tags"
down_revision = "20260408_caja_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- caja_tags --
    op.create_table(
        "caja_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("nombre", name="uq_caja_tag_nombre"),
    )

    # -- caja_movimiento_tags (junction N:M) --
    op.create_table(
        "caja_movimiento_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "movimiento_id",
            sa.Integer(),
            sa.ForeignKey("caja_movimientos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("caja_tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("movimiento_id", "tag_id", name="uq_caja_mov_tag"),
    )
    op.create_index("ix_caja_mov_tag_movimiento", "caja_movimiento_tags", ["movimiento_id"])
    op.create_index("ix_caja_mov_tag_tag", "caja_movimiento_tags", ["tag_id"])

    # -- updated_at on caja_movimientos --
    op.add_column("caja_movimientos", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("caja_movimientos", "updated_at")
    op.drop_index("ix_caja_mov_tag_tag", table_name="caja_movimiento_tags")
    op.drop_index("ix_caja_mov_tag_movimiento", table_name="caja_movimiento_tags")
    op.drop_table("caja_movimiento_tags")
    op.drop_table("caja_tags")
