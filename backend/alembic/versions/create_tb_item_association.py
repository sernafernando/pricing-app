"""Create tb_item_association table

Revision ID: create_tb_item_association
Revises: create_offset_grupo_filtros
Create Date: 2025-12-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_item_association'
down_revision = 'create_offset_grupo_filtros'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_item_association',
        # Primary Keys
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('itema_id', sa.Integer(), nullable=False),

        # Foreign keys a items
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('item_id_1', sa.Integer(), nullable=True),

        # Datos de la asociación
        sa.Column('iasso_qty', sa.Numeric(18, 4), nullable=True),
        sa.Column('itema_canDeleteInSO', sa.Boolean(), nullable=True),
        sa.Column('itema_discountPercentage4PriceListSUM', sa.Numeric(18, 4), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('comp_id', 'itema_id')
    )

    op.create_index('ix_tb_item_association_itema_id', 'tb_item_association', ['itema_id'], unique=False)
    op.create_index('ix_tb_item_association_item_id', 'tb_item_association', ['item_id'], unique=False)
    op.create_index('ix_tb_item_association_item_id_1', 'tb_item_association', ['item_id_1'], unique=False)


def downgrade():
    op.drop_index('ix_tb_item_association_item_id_1', table_name='tb_item_association')
    op.drop_index('ix_tb_item_association_item_id', table_name='tb_item_association')
    op.drop_index('ix_tb_item_association_itema_id', table_name='tb_item_association')
    op.drop_table('tb_item_association')
