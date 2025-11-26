"""add usuario_id to producto_banlist

Revision ID: f9a3b8c7d2e1
Revises: e8f3c4d5a6b2
Create Date: 2025-01-26 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9a3b8c7d2e1'
down_revision = 'e8f3c4d5a6b2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('producto_banlist', sa.Column('usuario_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_producto_banlist_usuario', 'producto_banlist', 'usuarios', ['usuario_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_producto_banlist_usuario', 'producto_banlist', type_='foreignkey')
    op.drop_column('producto_banlist', 'usuario_id')
