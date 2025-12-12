"""add user_id to notificaciones

Revision ID: add_user_id_notif
Revises:
Create Date: 2025-11-27

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_user_id_notif'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columna user_id
    op.add_column('notificaciones',
        sa.Column('user_id', sa.Integer(), nullable=True)
    )

    # Crear foreign key a usuarios
    op.create_foreign_key(
        'fk_notificaciones_user_id',
        'notificaciones', 'usuarios',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )

    # Crear índice en user_id
    op.create_index('ix_notificaciones_user_id', 'notificaciones', ['user_id'])


def downgrade():
    op.drop_index('ix_notificaciones_user_id', table_name='notificaciones')
    op.drop_constraint('fk_notificaciones_user_id', 'notificaciones', type_='foreignkey')
    op.drop_column('notificaciones', 'user_id')
