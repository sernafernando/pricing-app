"""add banco_movimientos table and update bancos_empresa (F7 banco como entidad)

Revision ID: compras_032_banco_mov
Revises: compras_031_tc_manual
Create Date: 2026-05-21

F7/PR#2a — makes bank accounts first-class fund-tracking entities:
- Creates banco_movimientos table (append-only ledger, mirrors caja_movimientos)
- Adds bancos_empresa.saldo_actual NOT NULL (backfill = saldo_inicial)
- Adds bancos_empresa.empresa_id NULLABLE (no backfill per AD-13)
"""

import sqlalchemy as sa
from alembic import op

revision = "compras_032_banco_mov"
down_revision = "compras_031_tc_manual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create banco_movimientos table
    op.create_table(
        "banco_movimientos",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "banco_id",
            sa.Integer,
            sa.ForeignKey("bancos_empresa.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("detalle", sa.String(500), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("saldo_posterior", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "origen",
            sa.String(50),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column(
            "registrado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("monto > 0", name="ck_banco_mov_monto_positivo"),
        sa.CheckConstraint("tipo IN ('ingreso', 'egreso')", name="ck_banco_mov_tipo"),
    )
    op.create_index("ix_banco_mov_banco_fecha", "banco_movimientos", ["banco_id", "fecha"])
    op.create_index("ix_banco_mov_banco_tipo", "banco_movimientos", ["banco_id", "tipo"])

    # 2. Add saldo_actual to bancos_empresa (NOT NULL, server_default 0)
    op.add_column(
        "bancos_empresa",
        sa.Column("saldo_actual", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    # Backfill: existing rows get saldo_actual = saldo_inicial
    op.execute("UPDATE bancos_empresa SET saldo_actual = saldo_inicial")

    # 3. Add empresa_id to bancos_empresa (NULLABLE — no backfill per AD-13)
    op.add_column(
        "bancos_empresa",
        sa.Column(
            "empresa_id",
            sa.Integer,
            sa.ForeignKey("empresas.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_bancos_empresa_empresa", "bancos_empresa", ["empresa_id"])


def downgrade() -> None:
    # Reverse order
    op.drop_index("ix_bancos_empresa_empresa", table_name="bancos_empresa")
    op.drop_column("bancos_empresa", "empresa_id")
    op.drop_column("bancos_empresa", "saldo_actual")

    op.drop_index("ix_banco_mov_banco_tipo", table_name="banco_movimientos")
    op.drop_index("ix_banco_mov_banco_fecha", table_name="banco_movimientos")
    op.drop_table("banco_movimientos")
