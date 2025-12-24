"""create logistica tables

Revision ID: 20251224_180000
Revises: 20251223_170000
Create Date: 2025-12-24 18:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251224_180000'
down_revision = '20251223_170000'
branch_labels = None
depends_on = None


def upgrade():
    # Tabla de operarios logística
    op.create_table(
        'tb_operarios_logistica',
        sa.Column('operario_id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('operario_pin', sa.String(20), nullable=False, unique=True),
        sa.Column('operario_nombre', sa.String(100), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('timeout_minutos', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('ultima_actividad', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('operario_id'),
        sa.UniqueConstraint('operario_pin', name='uq_operario_pin')
    )
    
    op.create_index('idx_operario_pin', 'tb_operarios_logistica', ['operario_pin'])
    
    # Tabla de trazabilidad de paquetes
    op.create_table(
        'tb_paquete_trazabilidad',
        sa.Column('traz_id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('codigo_paquete', sa.String(100), nullable=False),
        sa.Column('soh_id', sa.Integer(), nullable=True),
        sa.Column('origen', sa.String(20), nullable=True),  # "TN", "ML", "GAUSS"
        sa.Column('operario_pin', sa.String(20), nullable=True),
        sa.Column('operario_nombre', sa.String(100), nullable=True),
        sa.Column('ubicacion', sa.String(50), nullable=True),  # "CAJA1", "SUELTO", etc
        sa.Column('accion', sa.String(50), nullable=False),  # "ASIGNAR", "DESPACHAR", etc
        sa.Column('fecha_hora', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('traz_id')
    )
    
    op.create_index('idx_traz_codigo_paquete', 'tb_paquete_trazabilidad', ['codigo_paquete'])
    op.create_index('idx_traz_soh_id', 'tb_paquete_trazabilidad', ['soh_id'])
    op.create_index('idx_traz_fecha', 'tb_paquete_trazabilidad', ['fecha_hora'], postgresql_using='btree')


def downgrade():
    op.drop_index('idx_traz_fecha', table_name='tb_paquete_trazabilidad')
    op.drop_index('idx_traz_soh_id', table_name='tb_paquete_trazabilidad')
    op.drop_index('idx_traz_codigo_paquete', table_name='tb_paquete_trazabilidad')
    op.drop_table('tb_paquete_trazabilidad')
    
    op.drop_index('idx_operario_pin', table_name='tb_operarios_logistica')
    op.drop_table('tb_operarios_logistica')
