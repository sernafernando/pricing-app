"""Backfill EAN on rma_caso_items from tb_item.item_code

Items created via agregarItemDesdeTraza had ean=null because the
frontend wasn't mapping articulo.codigo to ean. This backfills
existing items that have item_id but no ean.

Revision ID: 20260305_rma_fill_ean
Revises: 20260305_rma_item_ship
Create Date: 2026-03-05

"""

from alembic import op
import sqlalchemy as sa  # noqa: F401

revision = "20260305_rma_fill_ean"
down_revision = "20260305_rma_item_ship"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE rma_caso_items rci
        SET ean = i.item_code
        FROM tb_item i
        WHERE i.comp_id = 1
          AND i.item_id = rci.item_id
          AND rci.ean IS NULL
          AND rci.item_id IS NOT NULL
    """)


def downgrade() -> None:
    pass
