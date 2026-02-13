"""Crear tabla cp_cordones para mapeo de código postal a cordón de envío

Revision ID: 20260213_cp_cordones
Revises: 20260211_offset_flex_metricas
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "20260213_cp_cordones"
down_revision = "20260211_offset_flex_metricas"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cp_cordones",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("codigo_postal", sa.String(10), nullable=False),
        sa.Column("localidad", sa.String(255), nullable=True),
        sa.Column("cordon", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cp_cordones_id", "cp_cordones", ["id"])
    op.create_index("ix_cp_cordones_codigo_postal", "cp_cordones", ["codigo_postal"], unique=True)
    op.create_index("idx_cp_cordones_cordon", "cp_cordones", ["cordon"])


def downgrade():
    op.drop_index("idx_cp_cordones_cordon", table_name="cp_cordones")
    op.drop_index("ix_cp_cordones_codigo_postal", table_name="cp_cordones")
    op.drop_index("ix_cp_cordones_id", table_name="cp_cordones")
    op.drop_table("cp_cordones")
