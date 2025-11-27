"""create notificaciones table

Revision ID: a1b2c3d4e5f6
Revises: f9a3b8c7d2e1
Create Date: 2025-01-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f9a3b8c7d2e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notificaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('id_operacion', sa.BigInteger(), nullable=True),
        sa.Column('codigo_producto', sa.String(length=100), nullable=True),
        sa.Column('descripcion_producto', sa.String(length=500), nullable=True),
        sa.Column('mensaje', sa.Text(), nullable=False),
        sa.Column('markup_real', sa.Numeric(10, 2), nullable=True),
        sa.Column('markup_objetivo', sa.Numeric(10, 2), nullable=True),
        sa.Column('monto_venta', sa.Numeric(12, 2), nullable=True),
        sa.Column('fecha_venta', sa.DateTime(timezone=True), nullable=True),
        sa.Column('leida', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('fecha_lectura', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notificaciones_id'), 'notificaciones', ['id'], unique=False)
    op.create_index(op.f('ix_notificaciones_tipo'), 'notificaciones', ['tipo'], unique=False)
    op.create_index(op.f('ix_notificaciones_leida'), 'notificaciones', ['leida'], unique=False)
    op.create_index(op.f('ix_notificaciones_item_id'), 'notificaciones', ['item_id'], unique=False)
    op.create_index(op.f('ix_notificaciones_fecha_creacion'), 'notificaciones', ['fecha_creacion'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_notificaciones_fecha_creacion'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_item_id'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_leida'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_tipo'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_id'), table_name='notificaciones')
    op.drop_table('notificaciones')
