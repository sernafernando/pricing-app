"""Merge heads

Revision ID: merge_heads
Revises: add_monto_consumido_to_offsets, create_permisos_system
Create Date: 2025-12-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'merge_heads'
down_revision = ('add_monto_consumido_to_offsets', 'create_permisos_system')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
