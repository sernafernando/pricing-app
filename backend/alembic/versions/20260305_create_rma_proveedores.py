"""Create rma_proveedores table and seed from tb_supplier

Stores extended supplier data for RMA module (address, contact, config).
Seeded from existing tb_supplier rows so every ERP supplier has a record.

Revision ID: 20260305_rma_proveedores
Revises: 20260305_rma_deposito_fk_falla
Create Date: 2026-03-05

"""

import sqlalchemy as sa
from alembic import op

revision = "20260305_rma_proveedores"
down_revision = "20260305_rma_deposito_fk_falla"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create table
    op.create_table(
        "rma_proveedores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supp_id", sa.BigInteger(), index=True),
        sa.Column("comp_id", sa.Integer(), server_default="1"),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("cuit", sa.String(20), nullable=True),
        sa.Column("direccion", sa.String(500), nullable=True),
        sa.Column("cp", sa.String(20), nullable=True),
        sa.Column("ciudad", sa.String(255), nullable=True),
        sa.Column("provincia", sa.String(255), nullable=True),
        sa.Column("telefono", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("representante", sa.String(255), nullable=True),
        sa.Column("horario", sa.String(255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("unidades_minimas_rma", sa.Integer(), nullable=True),
        sa.Column(
            "activo",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Seed from existing tb_supplier data
    op.execute(
        sa.text("""
        INSERT INTO rma_proveedores (supp_id, comp_id, nombre, cuit)
        SELECT s.supp_id, s.comp_id, s.supp_name, s.supp_tax_number
        FROM tb_supplier s
        ORDER BY s.supp_id
    """)
    )


def downgrade():
    op.drop_table("rma_proveedores")
