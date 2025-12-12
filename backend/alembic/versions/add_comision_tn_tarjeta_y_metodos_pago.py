"""Add comision_tienda_nube_tarjeta and metodos_pago_tienda_nube table

Revision ID: add_comision_tn_tarjeta
Revises: create_ventas_tn_metricas
Create Date: 2025-12-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_comision_tn_tarjeta'
down_revision = 'create_ventas_tn_metricas'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columna comision_tienda_nube_tarjeta a pricing_constants
    op.add_column('pricing_constants',
        sa.Column('comision_tienda_nube_tarjeta', sa.Numeric(5, 2), nullable=False, server_default='3.0')
    )

    # Crear tabla metodos_pago_tienda_nube
    op.create_table('metodos_pago_tienda_nube',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('it_transaction', sa.BigInteger(), nullable=False),
        sa.Column('metodo_pago', sa.String(20), nullable=False, server_default='efectivo'),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], )
    )

    # Crear índices
    op.create_index('ix_metodos_pago_tn_it_transaction', 'metodos_pago_tienda_nube', ['it_transaction'], unique=True)


def downgrade():
    op.drop_index('ix_metodos_pago_tn_it_transaction', table_name='metodos_pago_tienda_nube')
    op.drop_table('metodos_pago_tienda_nube')
    op.drop_column('pricing_constants', 'comision_tienda_nube_tarjeta')
