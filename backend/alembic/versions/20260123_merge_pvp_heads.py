"""merge pvp heads

Revision ID: 20260123_merge_pvp
Revises: 20260123_pvp_masivo, 20260123_markup_pvp
Create Date: 2026-01-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260123_merge_pvp'
down_revision = ('20260123_pvp_masivo', '20260123_markup_pvp')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No hay cambios en el schema, solo merge de ramas
    pass


def downgrade() -> None:
    # No hay cambios en el schema, solo merge de ramas
    pass
