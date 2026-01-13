"""add item_lastUpdate_byProcess to tb_item

Revision ID: 20250113_add_byprocess
Revises: 20250107_create_banlist
Create Date: 2025-01-13 00:00:00

Agrega columna item_lastUpdate_byProcess a tb_item.
Este timestamp se actualiza cuando cambia el item O sus relaciones (taxes, associations).
Permite sync incremental más preciso que item_LastUpdate.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250113_add_byprocess'
down_revision = '20250107_create_banlist'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna item_lastUpdate_byProcess
    op.add_column(
        'tb_item',
        sa.Column('item_lastUpdate_byProcess', sa.DateTime(), nullable=True)
    )
    
    # Crear índice para mejorar queries de sync incremental
    op.create_index(
        'idx_tb_item_lastupdate_byprocess',
        'tb_item',
        ['item_lastUpdate_byProcess'],
        unique=False
    )
    
    # Agregar comentario (usar comillas dobles para nombres con mayúsculas)
    op.execute(
        'COMMENT ON COLUMN tb_item."item_lastUpdate_byProcess" IS '
        "'Timestamp actualizado por trigger cuando cambia item o sus relaciones (taxes, associations)'"
    )


def downgrade() -> None:
    # Eliminar índice
    op.drop_index('idx_tb_item_lastupdate_byprocess', table_name='tb_item')
    
    # Eliminar columna
    op.drop_column('tb_item', 'item_lastUpdate_byProcess')
