"""add tiendanube fields to productos_pricing

Revision ID: be7e944130f0
Revises: 9d2eecf696e7
Create Date: 2024-11-19 17:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'be7e944130f0'
down_revision = '9d2eecf696e7'
branch_labels = None
depends_on = None


def upgrade():
    # Add Tienda Nube fields to productos_pricing table
    op.add_column('productos_pricing', sa.Column('precio_tiendanube', sa.Numeric(precision=15, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('descuento_tiendanube', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('publicado_tiendanube', sa.Boolean(), nullable=True, server_default='false'))


def downgrade():
    # Remove Tienda Nube fields from productos_pricing table
    op.drop_column('productos_pricing', 'publicado_tiendanube')
    op.drop_column('productos_pricing', 'descuento_tiendanube')
    op.drop_column('productos_pricing', 'precio_tiendanube')
