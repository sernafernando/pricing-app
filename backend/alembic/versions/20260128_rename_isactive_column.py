"""rename_ssos_isActive_to_ssos_is_active

Revision ID: 20260128_rename_isactive
Revises: 20260128_add_ssos_5
Create Date: 2026-01-28

Renombra columna ssos_isActive a ssos_is_active (snake_case)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260128_rename_isactive'
down_revision = '20260128_add_ssos_5'
branch_labels = None
depends_on = None


def upgrade():
    """Renombrar columna a snake_case"""
    op.alter_column(
        'tb_sale_order_status',
        'ssos_isActive',
        new_column_name='ssos_is_active'
    )


def downgrade():
    """Revertir renombre"""
    op.alter_column(
        'tb_sale_order_status',
        'ssos_is_active',
        new_column_name='ssos_isActive'
    )
