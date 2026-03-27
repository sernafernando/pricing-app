"""Add rrhh_texto_predefinido_sancion table, seed from existing tipos, add FK on sanciones

Revision ID: 20260327_texto_pred_sancion
Revises: 20260327_sanciones_tipos
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260327_texto_pred_sancion"
down_revision = "20260327_sanciones_tipos"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Create new table
    op.create_table(
        "rrhh_texto_predefinido_sancion",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(200), unique=True, nullable=False),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("orden", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_texto_pred_sancion_activo_orden",
        "rrhh_texto_predefinido_sancion",
        ["activo", "orden"],
    )

    # 2) Seed from existing texto_predeterminado on rrhh_tipo_sancion
    op.execute("""
        INSERT INTO rrhh_texto_predefinido_sancion (nombre, texto, activo, orden)
        SELECT
            ts.nombre,
            ts.texto_predeterminado,
            true,
            ts.orden
        FROM rrhh_tipo_sancion ts
        WHERE ts.texto_predeterminado IS NOT NULL
          AND ts.texto_predeterminado != ''
        ON CONFLICT (nombre) DO NOTHING;
    """)

    # 3) Add FK column on rrhh_sanciones
    op.add_column(
        "rrhh_sanciones",
        sa.Column(
            "texto_predefinido_id",
            sa.Integer,
            sa.ForeignKey(
                "rrhh_texto_predefinido_sancion.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_sanciones_texto_predefinido",
        "rrhh_sanciones",
        ["texto_predefinido_id"],
    )


def downgrade():
    op.drop_index("idx_sanciones_texto_predefinido", table_name="rrhh_sanciones")
    op.drop_column("rrhh_sanciones", "texto_predefinido_id")
    op.drop_index(
        "idx_texto_pred_sancion_activo_orden",
        table_name="rrhh_texto_predefinido_sancion",
    )
    op.drop_table("rrhh_texto_predefinido_sancion")
