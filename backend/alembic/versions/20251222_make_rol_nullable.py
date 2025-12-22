"""make rol column nullable (deprecated)

Revision ID: make_rol_nullable
Revises: add_username_usuarios
Create Date: 2025-12-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'make_rol_nullable'
down_revision = 'add_username_usuarios'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hacer la columna rol nullable (está deprecada, usamos rol_id ahora)
    op.alter_column('usuarios', 'rol', nullable=True)


def downgrade() -> None:
    # Revertir: hacer rol NOT NULL
    # NOTA: Esto puede fallar si hay NULL en la columna
    op.alter_column('usuarios', 'rol', nullable=False)
