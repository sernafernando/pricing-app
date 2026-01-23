"""add markup_adicional_cuotas_pvp_custom to productos_pricing

Revision ID: 20260123_markup_pvp
Revises: 20260115132009
Create Date: 2026-01-23 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260123_markup_pvp'
down_revision = '20260115132009'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columna markup_adicional_cuotas_pvp_custom a productos_pricing
    op.add_column(
        'productos_pricing',
        sa.Column('markup_adicional_cuotas_pvp_custom', sa.Numeric(5, 2), nullable=True)
    )


def downgrade():
    # Eliminar columna
    op.drop_column('productos_pricing', 'markup_adicional_cuotas_pvp_custom')
