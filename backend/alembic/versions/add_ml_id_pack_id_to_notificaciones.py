"""add ml_id and pack_id to notificaciones

Revision ID: add_ml_pack_id_notif
Revises: add_user_id_notif
Create Date: 2025-11-27

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_ml_pack_id_notif'
down_revision = 'add_user_id_notif'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columnas ml_id y pack_id
    op.add_column('notificaciones',
        sa.Column('ml_id', sa.String(50), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('pack_id', sa.BigInteger(), nullable=True)
    )

    # Crear índices
    op.create_index('ix_notificaciones_ml_id', 'notificaciones', ['ml_id'])
    op.create_index('ix_notificaciones_pack_id', 'notificaciones', ['pack_id'])


def downgrade():
    op.drop_index('ix_notificaciones_pack_id', table_name='notificaciones')
    op.drop_index('ix_notificaciones_ml_id', table_name='notificaciones')
    op.drop_column('notificaciones', 'pack_id')
    op.drop_column('notificaciones', 'ml_id')
