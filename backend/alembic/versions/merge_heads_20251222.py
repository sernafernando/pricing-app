"""merge heads

Revision ID: merge_heads_20251222
Revises: 20251218_pvp, add_permisos_clientes
Create Date: 2025-12-22 09:20:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'merge_heads_20251222'
down_revision = ('20251218_pvp', 'add_permisos_clientes')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No hay cambios en el schema, solo merge de ramas
    pass


def downgrade() -> None:
    # No hay cambios en el schema, solo merge de ramas
    pass
