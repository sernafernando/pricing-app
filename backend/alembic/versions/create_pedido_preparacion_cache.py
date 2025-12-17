"""create pedido_preparacion_cache table

Revision ID: create_pedido_prep_cache
Revises: add_ordenes_preparacion
Create Date: 2025-01-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_pedido_prep_cache'
down_revision = 'add_ordenes_preparacion'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pedido_preparacion_cache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('item_code', sa.String(100), nullable=True),
        sa.Column('item_desc', sa.String(500), nullable=True),
        sa.Column('cantidad', sa.Numeric(18, 2), nullable=True, default=0),
        sa.Column('ml_logistic_type', sa.String(50), nullable=True),
        sa.Column('prepara_paquete', sa.Integer(), nullable=True, default=0),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pedido_preparacion_cache_item_id', 'pedido_preparacion_cache', ['item_id'])


def downgrade() -> None:
    op.drop_index('ix_pedido_preparacion_cache_item_id', table_name='pedido_preparacion_cache')
    op.drop_table('pedido_preparacion_cache')
