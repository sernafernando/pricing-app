"""Create offset_grupo_filtros table

Revision ID: create_offset_grupo_filtros
Revises: add_comision_tn_tarjeta
Create Date: 2025-12-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_offset_grupo_filtros'
down_revision = 'add_comision_tn_tarjeta'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('offset_grupo_filtros',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('grupo_id', sa.Integer(), nullable=False),
        sa.Column('marca', sa.String(255), nullable=True),
        sa.Column('categoria', sa.String(255), nullable=True),
        sa.Column('subcategoria_id', sa.Integer(), nullable=True),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['grupo_id'], ['offset_grupos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['productos_erp.item_id'], )
    )

    # Crear índices
    op.create_index('ix_offset_grupo_filtros_grupo_id', 'offset_grupo_filtros', ['grupo_id'])
    op.create_index('ix_offset_grupo_filtros_marca', 'offset_grupo_filtros', ['marca'])
    op.create_index('ix_offset_grupo_filtros_categoria', 'offset_grupo_filtros', ['categoria'])
    op.create_index('ix_offset_grupo_filtros_subcategoria_id', 'offset_grupo_filtros', ['subcategoria_id'])
    op.create_index('ix_offset_grupo_filtros_item_id', 'offset_grupo_filtros', ['item_id'])


def downgrade():
    op.drop_index('ix_offset_grupo_filtros_item_id', table_name='offset_grupo_filtros')
    op.drop_index('ix_offset_grupo_filtros_subcategoria_id', table_name='offset_grupo_filtros')
    op.drop_index('ix_offset_grupo_filtros_categoria', table_name='offset_grupo_filtros')
    op.drop_index('ix_offset_grupo_filtros_marca', table_name='offset_grupo_filtros')
    op.drop_index('ix_offset_grupo_filtros_grupo_id', table_name='offset_grupo_filtros')
    op.drop_table('offset_grupo_filtros')
