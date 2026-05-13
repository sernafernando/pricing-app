"""Agregar columna item_expser a tb_item (flag ERP: el item exige N° de serie)

Revision ID: 20260513_add_item_expser
Revises: 20260513_permiso_prearmar_combos
Create Date: 2026-05-13

El flag viene del ERP (GBP): item_expser BIT en SQL Server → BOOLEAN local.
Se popula vía `sync_erp_master_tables_full.py` (scriptItem). NULL hasta el primer sync;
el endpoint de prearmado usa COALESCE(item_expser, TRUE) para default a "requiere serie".
"""

from alembic import op


revision = "20260513_add_item_expser"
down_revision = "20260513_permiso_prearmar_combos"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE tb_item
        ADD COLUMN IF NOT EXISTS item_expser BOOLEAN;
    """)
    # Cleanup: si algún dev corrió la migración 20260513_items_config_serializable
    # (que fue eliminada del repo en este mismo cambio), la tabla queda zombi.
    op.execute("DROP TABLE IF EXISTS items_config_serializable;")


def downgrade():
    op.execute("""
        ALTER TABLE tb_item
        DROP COLUMN IF EXISTS item_expser;
    """)
