"""add bultos and tipo domicilio to override

Revision ID: $(openssl rand -hex 6)
Revises: 
Create Date: $(date +%Y-%m-%d %H:%M:%S)

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '$(openssl rand -hex 6)'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tb_sale_order_header', sa.Column('override_num_bultos', sa.Integer(), nullable=True))
    op.add_column('tb_sale_order_header', sa.Column('override_tipo_domicilio', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('tb_sale_order_header', 'override_tipo_domicilio')
    op.drop_column('tb_sale_order_header', 'override_num_bultos')
