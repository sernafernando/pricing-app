"""add override shipping fields to sale_order_header

Revision ID: 20251223_130000
Revises: 20251223_115500
Create Date: 2025-12-23 13:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_130000'
down_revision = '20251223_115500'
branch_labels = None
depends_on = None


def upgrade():
    """
    Agrega campos de override de dirección de envío a tb_sale_order_header.
    Estos campos tienen prioridad para visualización, pero las etiquetas ZPL
    deben usar los datos reales de TN/ERP.
    """
    op.add_column('tb_sale_order_header', sa.Column('override_shipping_address', sa.Text(), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_shipping_city', sa.String(255), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_shipping_province', sa.String(255), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_shipping_zipcode', sa.String(20), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_shipping_phone', sa.String(100), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_shipping_recipient', sa.String(255), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_notes', sa.Text(), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_modified_by', sa.Integer(), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_modified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    """
    Elimina los campos de override.
    """
    op.drop_column('tb_sale_order_header', 'override_modified_at')
    op.drop_column('tb_sale_order_header', 'override_modified_by')
    op.drop_column('tb_sale_order_header', 'override_notes')
    op.drop_column('tb_sale_order_header', 'override_shipping_recipient')
    op.drop_column('tb_sale_order_header', 'override_shipping_phone')
    op.drop_column('tb_sale_order_header', 'override_shipping_zipcode')
    op.drop_column('tb_sale_order_header', 'override_shipping_province')
    op.drop_column('tb_sale_order_header', 'override_shipping_city')
    op.drop_column('tb_sale_order_header', 'override_shipping_address')
