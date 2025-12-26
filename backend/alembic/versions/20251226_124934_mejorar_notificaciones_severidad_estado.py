"""mejorar notificaciones con severidad y estado

Revision ID: 20251226_notif_02
Revises: 20251226_merge_01
Create Date: 2025-12-26 12:49:34.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251226_notif_02'
down_revision = '20251226_merge_01'
branch_labels = None
depends_on = None


def upgrade():
    # Eliminar ENUMs viejos si existen
    op.execute("DROP TYPE IF EXISTS severidadnotificacion CASCADE")
    op.execute("DROP TYPE IF EXISTS estadonotificacion CASCADE")
    
    # Crear enums con valores UPPERCASE
    severidad_enum = postgresql.ENUM('INFO', 'WARNING', 'CRITICAL', 'URGENT', name='severidadnotificacion')
    severidad_enum.create(op.get_bind())
    
    estado_enum = postgresql.ENUM('PENDIENTE', 'REVISADA', 'DESCARTADA', 'EN_GESTION', 'RESUELTA', name='estadonotificacion')
    estado_enum.create(op.get_bind())
    
    # Agregar columnas de severidad y estado
    op.add_column('notificaciones', sa.Column('severidad', severidad_enum, nullable=False, server_default='INFO'))
    op.add_column('notificaciones', sa.Column('estado', estado_enum, nullable=False, server_default='PENDIENTE'))
    
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
    # Si markup_real difiere más del 15% del objetivo, marcar como CRITICAL
    op.execute("""
        UPDATE notificaciones
        SET severidad = 'CRITICAL'
        WHERE markup_real IS NOT NULL 
          AND markup_objetivo IS NOT NULL
          AND markup_objetivo != 0
          AND ABS((markup_real - markup_objetivo) / markup_objetivo * 100) > 15
    """)
    
    # Si markup difiere entre 10-15%, marcar como WARNING
    op.execute("""
        UPDATE notificaciones
        SET severidad = 'WARNING'
        WHERE markup_real IS NOT NULL 
          AND markup_objetivo IS NOT NULL
          AND markup_objetivo != 0
          AND ABS((markup_real - markup_objetivo) / markup_objetivo * 100) BETWEEN 10 AND 15
          AND severidad = 'INFO'
    """)
    
    # Si markup difiere más del 25%, marcar como URGENT
    op.execute("""
        UPDATE notificaciones
        SET severidad = 'URGENT'
        WHERE markup_real IS NOT NULL 
          AND markup_objetivo IS NOT NULL
          AND markup_objetivo != 0
          AND ABS((markup_real - markup_objetivo) / markup_objetivo * 100) > 25
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
    op.execute("DROP TYPE IF EXISTS estadonotificacion")
    op.execute("DROP TYPE IF EXISTS severidadnotificacion")
