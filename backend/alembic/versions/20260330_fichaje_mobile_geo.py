"""Add mobile fichaje geo columns to rrhh_fichadas and create rrhh_ubicaciones_oficina

Adds 4 nullable columns to rrhh_fichadas for GPS metadata captured during
mobile clock-in/out (informative only, never blocks fichada):
- latitud, longitud: GPS coordinates
- accuracy_metros: GPS accuracy reported by device
- distancia_oficina_metros: haversine distance to nearest active office

Creates rrhh_ubicaciones_oficina table for office location reference points.

The origen column is VARCHAR(20) so the new "mobile" value needs no ALTER TYPE.

Revision ID: 20260330_fichaje_mobile
Revises: 20260327_seed_textos_pred
Create Date: 2026-03-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20260330_fichaje_mobile"
down_revision = "20260327_seed_textos_pred"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Add geo columns to rrhh_fichadas ---
    op.add_column(
        "rrhh_fichadas",
        sa.Column("latitud", sa.Numeric(precision=10, scale=8), nullable=True),
    )
    op.add_column(
        "rrhh_fichadas",
        sa.Column("longitud", sa.Numeric(precision=11, scale=8), nullable=True),
    )
    op.add_column(
        "rrhh_fichadas",
        sa.Column("accuracy_metros", sa.Float(), nullable=True),
    )
    op.add_column(
        "rrhh_fichadas",
        sa.Column("distancia_oficina_metros", sa.Float(), nullable=True),
    )

    # --- Create rrhh_ubicaciones_oficina table ---
    op.create_table(
        "rrhh_ubicaciones_oficina",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("latitud", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("longitud", sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column("radio_metros", sa.Float(), nullable=False, server_default="100.0"),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_rrhh_ubicaciones_oficina_id",
        "rrhh_ubicaciones_oficina",
        ["id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rrhh_ubicaciones_oficina_id",
        table_name="rrhh_ubicaciones_oficina",
    )
    op.drop_table("rrhh_ubicaciones_oficina")
    op.drop_column("rrhh_fichadas", "distancia_oficina_metros")
    op.drop_column("rrhh_fichadas", "accuracy_metros")
    op.drop_column("rrhh_fichadas", "longitud")
    op.drop_column("rrhh_fichadas", "latitud")
