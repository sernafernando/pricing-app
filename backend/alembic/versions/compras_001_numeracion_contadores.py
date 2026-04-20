"""compras 001 — numeracion_contadores

Revision ID: compras_001_num
Revises: 20260416_date_delivered
Create Date: 2026-04-17

Módulo de Compras v1 — Fase 1 foundations.
Crea la tabla base de contadores correlativos (tipo, empresa, año).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_001_num"
down_revision: Union[str, None] = "20260416_date_delivered"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "numeracion_contadores",
        sa.Column("tipo", sa.String(length=24), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column(
            "ultimo_numero",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["empresas.id"],
            name="fk_numeracion_contadores_empresa",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tipo", "empresa_id", "anio", name="pk_numeracion_contadores"),
        sa.CheckConstraint(
            "ultimo_numero >= 0",
            name="ck_numeracion_ultimo_numero_non_negative",
        ),
        sa.CheckConstraint("anio BETWEEN 2020 AND 2100", name="ck_numeracion_anio_range"),
    )


def downgrade() -> None:
    op.drop_table("numeracion_contadores")
