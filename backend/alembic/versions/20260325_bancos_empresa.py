"""Create bancos_empresa table.

Revision ID: d5b1c3e4f820
Revises: c4a9e2f3b710
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

revision = "d5b1c3e4f820"
down_revision = "c4a9e2f3b710"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bancos_empresa",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("banco", sa.String(255), nullable=False),
        sa.Column("tipo_cuenta", sa.String(50), nullable=True),
        sa.Column("cbu", sa.String(30), nullable=True, unique=True),
        sa.Column("alias", sa.String(100), nullable=True),
        sa.Column("numero_cuenta", sa.String(50), nullable=True),
        sa.Column("sucursal", sa.String(100), nullable=True),
        sa.Column("moneda", sa.String(10), nullable=False, server_default="ARS"),
        sa.Column("titular", sa.String(255), nullable=True),
        sa.Column("cuit_titular", sa.String(20), nullable=True),
        sa.Column("saldo_inicial", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_bancos_empresa_id", "bancos_empresa", ["id"])


def downgrade() -> None:
    op.drop_index("ix_bancos_empresa_id", table_name="bancos_empresa")
    op.drop_table("bancos_empresa")
