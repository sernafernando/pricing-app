"""add pvp pricing columns

Revision ID: 20251218_pvp
Revises: 20251217_precio_gremio_override
Create Date: 2025-12-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251218_pvp'
down_revision = '20251217_precio_gremio_override'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columnas de precios PVP con cuotas
    op.add_column('productos_pricing', sa.Column('precio_pvp', sa.Numeric(precision=15, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('precio_pvp_3_cuotas', sa.Numeric(precision=15, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('precio_pvp_6_cuotas', sa.Numeric(precision=15, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('precio_pvp_9_cuotas', sa.Numeric(precision=15, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('precio_pvp_12_cuotas', sa.Numeric(precision=15, scale=2), nullable=True))
    
    # Agregar columnas de markup PVP
    op.add_column('productos_pricing', sa.Column('markup_pvp', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('markup_pvp_3_cuotas', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('markup_pvp_6_cuotas', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('markup_pvp_9_cuotas', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('productos_pricing', sa.Column('markup_pvp_12_cuotas', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    # Eliminar columnas de markup PVP
    op.drop_column('productos_pricing', 'markup_pvp_12_cuotas')
    op.drop_column('productos_pricing', 'markup_pvp_9_cuotas')
    op.drop_column('productos_pricing', 'markup_pvp_6_cuotas')
    op.drop_column('productos_pricing', 'markup_pvp_3_cuotas')
    op.drop_column('productos_pricing', 'markup_pvp')
    
    # Eliminar columnas de precios PVP
    op.drop_column('productos_pricing', 'precio_pvp_12_cuotas')
    op.drop_column('productos_pricing', 'precio_pvp_9_cuotas')
    op.drop_column('productos_pricing', 'precio_pvp_6_cuotas')
    op.drop_column('productos_pricing', 'precio_pvp_3_cuotas')
    op.drop_column('productos_pricing', 'precio_pvp')
