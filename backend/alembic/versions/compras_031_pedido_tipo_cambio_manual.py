"""add pedidos_compra.tipo_cambio_manual (F5 manual TC override)

Revision ID: compras_031_tc_manual
Revises: merge_heads_20260520
Create Date: 2026-05-20

F5 — adds a nullable column `tipo_cambio_manual` to `pedidos_compra`.
NULL = no manual override in effect (weighted Caso-A or tipo_cambio_original wins).
non-NULL = authoritative manual TC override (AD-2, AD-3).

No backfill — existing pedidos start with NULL (no override).
"""

from alembic import op
import sqlalchemy as sa

revision = "compras_031_tc_manual"
down_revision = "merge_heads_20260520"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column("tipo_cambio_manual", sa.Numeric(18, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pedidos_compra", "tipo_cambio_manual")
