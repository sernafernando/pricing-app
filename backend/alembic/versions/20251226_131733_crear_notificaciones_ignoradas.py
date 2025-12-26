"""crear notificaciones ignoradas

Revision ID: 20251226_ignore_01
Revises: 20251226_notif_02
Create Date: 2025-12-26 13:17:33.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251226_ignore_01'
down_revision = '20251226_notif_02'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla de notificaciones ignoradas
    op.create_table(
        'notificaciones_ignoradas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('markup_real', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('codigo_producto', sa.String(length=100), nullable=True),
        sa.Column('descripcion_producto', sa.String(length=500), nullable=True),
        sa.Column('fecha_ignorado', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ignorado_por_notificacion_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'item_id', 'tipo', 'markup_real', name='uq_notificacion_ignorada')
    )
    
    # Crear índices
    op.create_index('ix_notificaciones_ignoradas_user_id', 'notificaciones_ignoradas', ['user_id'])
    op.create_index('ix_notificaciones_ignoradas_item_id', 'notificaciones_ignoradas', ['item_id'])
    op.create_index('ix_notificaciones_ignoradas_tipo', 'notificaciones_ignoradas', ['tipo'])
    
    # Índice compuesto para búsquedas rápidas
    op.create_index(
        'ix_notificaciones_ignoradas_lookup',
        'notificaciones_ignoradas',
        ['user_id', 'item_id', 'tipo'],
        unique=False
    )


def downgrade():
    op.drop_index('ix_notificaciones_ignoradas_lookup', 'notificaciones_ignoradas')
    op.drop_index('ix_notificaciones_ignoradas_tipo', 'notificaciones_ignoradas')
    op.drop_index('ix_notificaciones_ignoradas_item_id', 'notificaciones_ignoradas')
    op.drop_index('ix_notificaciones_ignoradas_user_id', 'notificaciones_ignoradas')
    op.drop_table('notificaciones_ignoradas')
