"""mejorar notificaciones con severidad y estado

Revision ID: 20251226_notif_01
Revises: 20251226_merge_01
Create Date: 2025-12-26 12:42:48.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251226_notif_01'
down_revision = '20251226_merge_01'
branch_labels = None
depends_on = None


def upgrade():
    # Crear enums
    severidad_enum = postgresql.ENUM('info', 'warning', 'critical', 'urgent', name='severidadnotificacion')
    severidad_enum.create(op.get_bind())
    
    estado_enum = postgresql.ENUM('pendiente', 'revisada', 'descartada', 'en_gestion', 'resuelta', name='estadonotificacion')
    estado_enum.create(op.get_bind())
    
    # Agregar columnas de severidad y estado
    op.add_column('notificaciones', sa.Column('severidad', severidad_enum, nullable=False, server_default='info'))
    op.add_column('notificaciones', sa.Column('estado', estado_enum, nullable=False, server_default='pendiente'))
    
    # Agregar fechas de gestión
    op.add_column('notificaciones', sa.Column('fecha_revision', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notificaciones', sa.Column('fecha_descarte', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notificaciones', sa.Column('fecha_resolucion', sa.DateTime(timezone=True), nullable=True))
    
    # Agregar notas de revisión
    op.add_column('notificaciones', sa.Column('notas_revision', sa.Text(), nullable=True))
    
    # Crear índices para mejorar performance
    op.create_index('ix_notificaciones_severidad', 'notificaciones', ['severidad'])
    op.create_index('ix_notificaciones_estado', 'notificaciones', ['estado'])
    op.create_index('ix_notificaciones_user_estado', 'notificaciones', ['user_id', 'estado'])
    op.create_index('ix_notificaciones_user_severidad', 'notificaciones', ['user_id', 'severidad'])
    
    # Actualizar notificaciones existentes con severidad basada en markup
    # Si markup_real difiere más del 15% del objetivo, marcar como critical
    op.execute("""
        UPDATE notificaciones
        SET severidad = 'critical'
        WHERE markup_real IS NOT NULL 
          AND markup_objetivo IS NOT NULL
          AND markup_objetivo != 0
          AND ABS((markup_real - markup_objetivo) / markup_objetivo * 100) > 15
    """)
    
    # Si markup difiere entre 10-15%, marcar como warning
    op.execute("""
        UPDATE notificaciones
        SET severidad = 'warning'
        WHERE markup_real IS NOT NULL 
          AND markup_objetivo IS NOT NULL
          AND markup_objetivo != 0
          AND ABS((markup_real - markup_objetivo) / markup_objetivo * 100) BETWEEN 10 AND 15
          AND severidad = 'info'
    """)


def downgrade():
    # Eliminar índices
    op.drop_index('ix_notificaciones_user_severidad', 'notificaciones')
    op.drop_index('ix_notificaciones_user_estado', 'notificaciones')
    op.drop_index('ix_notificaciones_estado', 'notificaciones')
    op.drop_index('ix_notificaciones_severidad', 'notificaciones')
    
    # Eliminar columnas
    op.drop_column('notificaciones', 'notas_revision')
    op.drop_column('notificaciones', 'fecha_resolucion')
    op.drop_column('notificaciones', 'fecha_descarte')
    op.drop_column('notificaciones', 'fecha_revision')
    op.drop_column('notificaciones', 'estado')
    op.drop_column('notificaciones', 'severidad')
    
    # Eliminar enums
    estado_enum = postgresql.ENUM('pendiente', 'revisada', 'descartada', 'en_gestion', 'resuelta', name='estadonotificacion')
    estado_enum.drop(op.get_bind())
    
    severidad_enum = postgresql.ENUM('info', 'warning', 'critical', 'urgent', name='severidadnotificacion')
    severidad_enum.drop(op.get_bind())
