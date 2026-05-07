"""Crear tabla colectas y vincular etiquetas_colecta

Una colecta agrupa múltiples etiquetas que salen juntas en un mismo retiro.
Identificada por (fecha, numero), con estado pendiente|despachada.

Backfill: por cada fecha_carga distinta en etiquetas_colecta, crea una colecta
#1 con estado='despachada' y despachada_at=created_at máximo de ese día.
Las etiquetas existentes quedan vinculadas a esa colecta legacy.

Revision ID: 20260507_colectas
Revises: 20260430_rrhh_horas_extras
Create Date: 2026-05-07

"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_colectas"
down_revision = "20260430_rrhh_horas_extras"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "colectas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default="pendiente",
        ),
        sa.Column("despachada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("fecha", "numero", name="uq_colecta_fecha_numero"),
    )

    op.create_index("idx_colectas_fecha", "colectas", ["fecha"])
    op.create_index("idx_colectas_estado", "colectas", ["estado"])

    # ── colecta_id en etiquetas_colecta (nullable inicialmente) ─────
    op.add_column(
        "etiquetas_colecta",
        sa.Column("colecta_id", sa.Integer(), nullable=True),
    )

    # ── Backfill: una colecta legacy despachada por cada fecha_carga ──
    op.execute(
        """
        INSERT INTO colectas (fecha, numero, estado, despachada_at, observaciones, created_at, updated_at)
        SELECT
            fecha_carga,
            1 AS numero,
            'despachada' AS estado,
            COALESCE(MAX(updated_at), MAX(created_at), NOW()) AS despachada_at,
            'Colecta legacy creada en migración' AS observaciones,
            NOW(),
            NOW()
        FROM etiquetas_colecta
        GROUP BY fecha_carga
        """
    )

    # Vincular etiquetas existentes a su colecta legacy
    op.execute(
        """
        UPDATE etiquetas_colecta e
        SET colecta_id = c.id
        FROM colectas c
        WHERE c.fecha = e.fecha_carga AND c.numero = 1
        """
    )

    # Ahora sí: NOT NULL + FK + index
    op.alter_column("etiquetas_colecta", "colecta_id", nullable=False)
    op.create_foreign_key(
        "fk_etiquetas_colecta_colecta_id",
        "etiquetas_colecta",
        "colectas",
        ["colecta_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_etiquetas_colecta_colecta_id",
        "etiquetas_colecta",
        ["colecta_id"],
    )


def downgrade():
    op.drop_index("ix_etiquetas_colecta_colecta_id", table_name="etiquetas_colecta")
    op.drop_constraint(
        "fk_etiquetas_colecta_colecta_id",
        "etiquetas_colecta",
        type_="foreignkey",
    )
    op.drop_column("etiquetas_colecta", "colecta_id")

    op.drop_index("idx_colectas_estado", table_name="colectas")
    op.drop_index("idx_colectas_fecha", table_name="colectas")
    op.drop_table("colectas")
