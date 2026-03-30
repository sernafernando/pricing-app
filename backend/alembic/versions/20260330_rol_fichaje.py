"""Seed rol FICHAJE for mobile clock-in only users.

Revision ID: 20260330_rol_fichaje
Revises: 20260330_fichaje_mobile
Create Date: 2026-03-30
"""

from alembic import op

revision = "20260330_rol_fichaje"
down_revision = "20260330_fichaje_mobile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO roles (codigo, nombre, descripcion, es_sistema, orden, activo)
        VALUES ('FICHAJE', 'Fichaje', 'Acceso exclusivo a fichaje mobile. Sin permisos en el sistema.', false, 10, true)
        ON CONFLICT (codigo) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM roles WHERE codigo = 'FICHAJE'")
