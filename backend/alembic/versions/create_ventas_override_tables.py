"""Create ventas override tables for manual corrections

Revision ID: create_ventas_override_tables
Revises: create_offset_grupo_filtros
Create Date: 2025-12-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_ventas_override_tables'
down_revision = 'create_offset_grupo_filtros'
branch_labels = None
depends_on = None


def upgrade():
    # Tabla para overrides de ventas Tienda Nube
    op.create_table(
        'ventas_tienda_nube_override',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('it_transaction', sa.BigInteger(), nullable=False, unique=True, index=True),

        # Campos que se pueden corregir manualmente
        sa.Column('marca', sa.String(255), nullable=True),
        sa.Column('categoria', sa.String(255), nullable=True),
        sa.Column('subcategoria', sa.String(255), nullable=True),

        # Auditoría
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    )

    # Tabla para overrides de ventas fuera de ML
    op.create_table(
        'ventas_fuera_ml_override',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('it_transaction', sa.BigInteger(), nullable=False, unique=True, index=True),

        # Campos que se pueden corregir manualmente
        sa.Column('marca', sa.String(255), nullable=True),
        sa.Column('categoria', sa.String(255), nullable=True),
        sa.Column('subcategoria', sa.String(255), nullable=True),

        # Auditoría
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    )


def downgrade():
    op.drop_table('ventas_fuera_ml_override')
    op.drop_table('ventas_tienda_nube_override')
