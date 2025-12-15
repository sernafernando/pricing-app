"""create markups_tienda_producto table

Revision ID: 20251215_101438
Revises:
Create Date: 2025-12-15 10:14:38

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251215_101438'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'markups_tienda_producto',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(100), nullable=True),
        sa.Column('descripcion', sa.String(500), nullable=True),
        sa.Column('marca', sa.String(255), nullable=True),
        sa.Column('markup_porcentaje', sa.Float(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['usuarios.id'], ),
        sa.ForeignKeyConstraint(['updated_by_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_markups_tienda_producto_id'), 'markups_tienda_producto', ['id'], unique=False)
    op.create_index(op.f('ix_markups_tienda_producto_item_id'), 'markups_tienda_producto', ['item_id'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_markups_tienda_producto_item_id'), table_name='markups_tienda_producto')
    op.drop_index(op.f('ix_markups_tienda_producto_id'), table_name='markups_tienda_producto')
    op.drop_table('markups_tienda_producto')
