"""add_tn_enriched_fields

Revision ID: 20251223_100905
Revises: 20251223_094242
Create Date: 2025-12-23 10:09:05

Agrega campos para almacenar datos enriquecidos desde TiendaNube API:
- tiendanube_number: Número de orden visible en TN (NRO-XXXXX)
- tiendanube_shipping_*: Datos de envío desde TN API
- tiendanube_recipient_name: Nombre del destinatario
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_100905'
down_revision = '20251223_094242'
branch_labels = None
depends_on = None


def upgrade():
    """Agrega campos de TiendaNube enriquecidos a tb_sale_order_header"""
    
    # Número de orden TN (NRO-0001234)
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_number', sa.String(50), nullable=True))
    
    # Datos de envío desde TN API
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_shipping_phone', sa.String(50), nullable=True))
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_shipping_address', sa.Text(), nullable=True))
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_shipping_city', sa.String(100), nullable=True))
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_shipping_province', sa.String(100), nullable=True))
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_shipping_zipcode', sa.String(20), nullable=True))
    op.add_column('tb_sale_order_header', 
        sa.Column('tiendanube_recipient_name', sa.String(200), nullable=True))
    
    # Índice para búsqueda por número de orden TN
    op.create_index('ix_soh_tiendanube_number', 'tb_sale_order_header', ['tiendanube_number'])


def downgrade():
    """Revierte los cambios"""
    op.drop_index('ix_soh_tiendanube_number', 'tb_sale_order_header')
    
    op.drop_column('tb_sale_order_header', 'tiendanube_recipient_name')
    op.drop_column('tb_sale_order_header', 'tiendanube_shipping_zipcode')
    op.drop_column('tb_sale_order_header', 'tiendanube_shipping_province')
    op.drop_column('tb_sale_order_header', 'tiendanube_shipping_city')
    op.drop_column('tb_sale_order_header', 'tiendanube_shipping_address')
    op.drop_column('tb_sale_order_header', 'tiendanube_shipping_phone')
    op.drop_column('tb_sale_order_header', 'tiendanube_number')
