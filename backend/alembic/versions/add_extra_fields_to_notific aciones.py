"""add extra fields to notificaciones

Revision ID: add_extra_fields_notif
Revises: add_ml_pack_id_notif
Create Date: 2025-11-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_extra_fields_notif'
down_revision = 'add_ml_pack_id_notif'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campos adicionales para notificaciones
    op.add_column('notificaciones',
        sa.Column('pm', sa.Numeric(10, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('costo_operacion', sa.Numeric(12, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('costo_actual', sa.Numeric(12, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('precio_venta_unitario', sa.Numeric(12, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('precio_publicacion', sa.Numeric(12, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('tipo_publicacion', sa.String(50), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('comision_ml', sa.Numeric(12, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('iva_porcentaje', sa.Numeric(5, 2), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('cantidad', sa.Integer(), nullable=True)
    )
    op.add_column('notificaciones',
        sa.Column('costo_envio', sa.Numeric(12, 2), nullable=True)
    )


def downgrade():
    op.drop_column('notificaciones', 'costo_envio')
    op.drop_column('notificaciones', 'cantidad')
    op.drop_column('notificaciones', 'iva_porcentaje')
    op.drop_column('notificaciones', 'comision_ml')
    op.drop_column('notificaciones', 'tipo_publicacion')
    op.drop_column('notificaciones', 'precio_publicacion')
    op.drop_column('notificaciones', 'precio_venta_unitario')
    op.drop_column('notificaciones', 'costo_actual')
    op.drop_column('notificaciones', 'costo_operacion')
    op.drop_column('notificaciones', 'pm')
