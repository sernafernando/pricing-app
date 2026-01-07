"""create envios_turbo_banlist table

Revision ID: 20250107_create_banlist
Revises: 20250106_add_tipo_generacion
Create Date: 2025-01-07 00:00:00

Crea tabla envios_turbo_banlist para excluir envíos problemáticos:
- Estados buggeados (stuck en not_delivered por meses)
- Inconsistencias con ML Webhook API
- Duplicados o errores de sincronización
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250107_create_banlist'
down_revision = '20250106_add_tipo_generacion'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear tabla envios_turbo_banlist
    op.create_table(
        'envios_turbo_banlist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mlshippingid', sa.String(length=50), nullable=False),
        sa.Column('motivo', sa.String(length=500), nullable=True),
        sa.Column('baneado_por', sa.Integer(), nullable=True),
        sa.Column(
            'baneado_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['baneado_por'],
            ['usuarios.id'],
            name='fk_envios_banlist_usuario'
        )
    )
    
    # Crear índices
    op.create_index(
        'idx_envios_banlist_mlshippingid',
        'envios_turbo_banlist',
        ['mlshippingid'],
        unique=True
    )
    
    op.create_index(
        'idx_envios_banlist_baneado_por',
        'envios_turbo_banlist',
        ['baneado_por'],
        unique=False
    )
    
    # Agregar comentarios
    op.execute(
        "COMMENT ON TABLE envios_turbo_banlist IS "
        "'Blacklist de envíos Turbo problemáticos o con estados inconsistentes'"
    )
    
    op.execute(
        "COMMENT ON COLUMN envios_turbo_banlist.mlshippingid IS "
        "'ID del envío ML a excluir del sistema de routing'"
    )
    
    op.execute(
        "COMMENT ON COLUMN envios_turbo_banlist.motivo IS "
        "'Razón del baneo: estado_buggeado, duplicado, inconsistencia_ml, etc.'"
    )


def downgrade() -> None:
    # Eliminar índices
    op.drop_index('idx_envios_banlist_baneado_por', table_name='envios_turbo_banlist')
    op.drop_index('idx_envios_banlist_mlshippingid', table_name='envios_turbo_banlist')
    
    # Eliminar tabla
    op.drop_table('envios_turbo_banlist')
