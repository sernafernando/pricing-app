"""create producto_banlist table

Revision ID: e8f3c4d5a6b2
Revises: c559fbb7edc8
Create Date: 2025-01-26 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e8f3c4d5a6b2'
down_revision = 'c559fbb7edc8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'producto_banlist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('ean', sa.String(length=50), nullable=True),
        sa.Column('motivo', sa.String(length=500), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('fecha_modificacion', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_producto_banlist_id'), 'producto_banlist', ['id'], unique=False)
    op.create_index(op.f('ix_producto_banlist_item_id'), 'producto_banlist', ['item_id'], unique=True)
    op.create_index(op.f('ix_producto_banlist_ean'), 'producto_banlist', ['ean'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_producto_banlist_ean'), table_name='producto_banlist')
    op.drop_index(op.f('ix_producto_banlist_item_id'), table_name='producto_banlist')
    op.drop_index(op.f('ix_producto_banlist_id'), table_name='producto_banlist')
    op.drop_table('producto_banlist')
