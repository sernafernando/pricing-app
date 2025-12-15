"""add color_marcado_tienda to productos_pricing

Revision ID: 20251215_color_tienda
Revises: 20251215_101438
Create Date: 2025-12-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251215_color_tienda'
down_revision = '20251215_101438'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('productos_pricing', sa.Column('color_marcado_tienda', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('productos_pricing', 'color_marcado_tienda')
