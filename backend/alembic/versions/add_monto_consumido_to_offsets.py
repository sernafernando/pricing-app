"""Add monto_consumido column to offsets_ganancia

Revision ID: add_monto_consumido_to_offsets
Revises: fix_tipo_offset_null
Create Date: 2025-12-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_monto_consumido_to_offsets'
down_revision = 'fix_tipo_offset_null'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('offsets_ganancia', sa.Column('monto_consumido', sa.Float(), nullable=True, server_default='0'))


def downgrade():
    op.drop_column('offsets_ganancia', 'monto_consumido')
