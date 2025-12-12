"""Add aplica_tienda_nube to offsets_ganancia

Revision ID: add_aplica_tienda_nube
Revises: create_offset_indiv_consumo
Create Date: 2025-12-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_aplica_tienda_nube'
down_revision = 'offset_indiv_consumo'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('offsets_ganancia', sa.Column('aplica_tienda_nube', sa.Boolean(), nullable=True, server_default='true'))


def downgrade():
    op.drop_column('offsets_ganancia', 'aplica_tienda_nube')
