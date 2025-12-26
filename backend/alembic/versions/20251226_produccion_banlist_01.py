"""add produccion banlist and prearmado tables

Revision ID: 20251226_produccion_01
Revises: 20251226_cuotas_01
Create Date: 2025-12-26 18:00:00

Agrega tablas para gestionar banlist y pre-armado en Producción - Preparación:
- produccion_banlist: Items que no deben aparecer en la vista de producción
- produccion_prearmado: Items que están siendo pre-armados (se auto-limpia)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251226_produccion_01'
down_revision = '20251226_cuotas_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear tabla produccion_banlist
    op.create_table(
        'produccion_banlist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('motivo', sa.Text(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id')
    )
    op.create_index('idx_produccion_banlist_item_id', 'produccion_banlist', ['item_id'], unique=False)
    op.create_index('idx_produccion_banlist_usuario_id', 'produccion_banlist', ['usuario_id'], unique=False)

    # Crear tabla produccion_prearmado
    op.create_table(
        'produccion_prearmado',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id')
    )
    op.create_index('idx_produccion_prearmado_item_id', 'produccion_prearmado', ['item_id'], unique=False)
    op.create_index('idx_produccion_prearmado_usuario_id', 'produccion_prearmado', ['usuario_id'], unique=False)

    # Agregar comentarios
    op.execute("COMMENT ON TABLE produccion_banlist IS 'Items que no deben aparecer en la vista de Producción - Preparación'")
    op.execute("COMMENT ON TABLE produccion_prearmado IS 'Items que están siendo pre-armados. Se auto-limpia cuando el producto desaparece del ERP'")


def downgrade() -> None:
    op.drop_index('idx_produccion_prearmado_usuario_id', table_name='produccion_prearmado')
    op.drop_index('idx_produccion_prearmado_item_id', table_name='produccion_prearmado')
    op.drop_table('produccion_prearmado')
    
    op.drop_index('idx_produccion_banlist_usuario_id', table_name='produccion_banlist')
    op.drop_index('idx_produccion_banlist_item_id', table_name='produccion_banlist')
    op.drop_table('produccion_banlist')
