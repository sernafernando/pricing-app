"""add bultos and tipo domicilio to override

Revision ID: 20251223_160000
Revises: 20251223_130000
Create Date: 2025-12-23 16:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251223_160000'
down_revision = '20251223_130000'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tb_sale_order_header', sa.Column('override_num_bultos', sa.Integer(), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_tipo_domicilio', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('tb_sale_order_header', 'override_tipo_domicilio')
    op.drop_column('tb_sale_order_header', 'override_num_bultos')
