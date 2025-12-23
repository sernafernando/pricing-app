"""add product fields to pedidos_export

Revision ID: 20251223_121500
Revises: 20251223_120000
Create Date: 2025-12-23 12:15:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_121500'
down_revision = '20251223_120000'
branch_labels = None
depends_on = None


def upgrade():
    """Agrega campos de producto a tb_pedidos_export"""
    op.add_column('tb_pedidos_export', sa.Column('item_code', sa.Text(), nullable=True, comment='EAN del producto'))
    op.add_column('tb_pedidos_export', sa.Column('item_desc', sa.Text(), nullable=True, comment='Descripción del producto'))


def downgrade():
    """Remueve campos de producto"""
    op.drop_column('tb_pedidos_export', 'item_desc')
    op.drop_column('tb_pedidos_export', 'item_code')
