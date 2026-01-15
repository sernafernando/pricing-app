"""add prli_id to ml orders header

Revision ID: 20260115132009
Revises: 20250113_add_cust_guid
Create Date: 2026-01-15 13:20:09.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260115132009'
down_revision = '20250113_add_cust_guid'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columna prli_id a tb_mercadolibre_orders_header
    op.add_column(
        'tb_mercadolibre_orders_header',
        sa.Column('prli_id', sa.Integer(), nullable=True)
    )
    
    # Crear índice para mejorar performance en joins
    op.create_index(
        'ix_tb_mercadolibre_orders_header_prli_id',
        'tb_mercadolibre_orders_header',
        ['prli_id'],
        unique=False
    )


def downgrade():
    # Remover índice
    op.drop_index('ix_tb_mercadolibre_orders_header_prli_id', table_name='tb_mercadolibre_orders_header')
    
    # Remover columna
    op.drop_column('tb_mercadolibre_orders_header', 'prli_id')
