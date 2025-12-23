"""add bultos and tipo domicilio to override

Revision ID: add_bultos_tipo_dom
Revises: 
Create Date: 2025-12-23 16:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_bultos_tipo_dom'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tb_sale_order_header', sa.Column('override_num_bultos', sa.Integer(), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_tipo_domicilio', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('tb_sale_order_header', 'override_tipo_domicilio')
    op.drop_column('tb_sale_order_header', 'override_num_bultos')
