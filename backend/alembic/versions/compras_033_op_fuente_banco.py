"""add banco columns to ordenes_pago (F7 banco como fuente de fondos — schema only)

Revision ID: compras_033_op_banco
Revises: compras_032_banco_mov
Create Date: 2026-05-21

F7/PR#2a — adds banco_id and banco_movimiento_id columns to ordenes_pago
plus the CHECK constraint that ensures only one fund source (caja XOR banco).
These columns are added now (schema-only) so PR#2b can use them for the
payment-flow refactor without a migration of its own.

Historical OPs (caja_id set, banco_id NULL) and pending OPs (both NULL)
both satisfy the constraint.
"""

import sqlalchemy as sa
from alembic import op

revision = "compras_033_op_banco"
down_revision = "compras_032_banco_mov"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add banco_id — NULLABLE FK to bancos_empresa
    op.add_column(
        "ordenes_pago",
        sa.Column(
            "banco_id",
            sa.Integer,
            sa.ForeignKey("bancos_empresa.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    # Add banco_movimiento_id — NULLABLE FK to banco_movimientos
    op.add_column(
        "ordenes_pago",
        sa.Column(
            "banco_movimiento_id",
            sa.Integer,
            sa.ForeignKey("banco_movimientos.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    # CHECK: at most one fund source (caja XOR banco; both NULL = pending OP is OK)
    op.create_check_constraint(
        "ck_ordenes_pago_fuente_unica",
        "ordenes_pago",
        "NOT (caja_id IS NOT NULL AND banco_id IS NOT NULL)",
    )

    # Partial index: fast lookup when banco_movimiento_id is set
    op.create_index(
        "ix_ordenes_pago_banco_mov",
        "ordenes_pago",
        ["banco_movimiento_id"],
        postgresql_where=sa.text("banco_movimiento_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ordenes_pago_banco_mov", table_name="ordenes_pago")
    op.drop_constraint("ck_ordenes_pago_fuente_unica", "ordenes_pago", type_="check")
    op.drop_column("ordenes_pago", "banco_movimiento_id")
    op.drop_column("ordenes_pago", "banco_id")
