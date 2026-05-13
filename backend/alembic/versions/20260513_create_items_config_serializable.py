"""Crear tabla items_config_serializable para override local de items no-serializables

Revision ID: 20260513_items_config_serializable
Revises: 20260513_create_prearmados
Create Date: 2026-05-13

Override local de items que no requieren serie física (gabinete, descuento, servicios).
Arranca vacía: poblar via SQL conforme se descubran items. Default runtime: requiere_serie=true.
"""

from alembic import op


revision = "20260513_items_config_serializable"
down_revision = "20260513_create_prearmados"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE items_config_serializable (
            item_id INTEGER PRIMARY KEY,
            requiere_serie BOOLEAN NOT NULL DEFAULT true,
            motivo TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by_user_id INTEGER REFERENCES usuarios(id)
        );
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS items_config_serializable;")
