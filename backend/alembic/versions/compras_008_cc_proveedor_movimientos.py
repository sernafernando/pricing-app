"""compras 008 — cc_proveedor_movimientos

Revision ID: compras_008_cc
Revises: compras_007_imp
Create Date: 2026-04-17

Libro mayor de cuenta corriente de proveedor (append-only).
Saldo por moneda se deriva agregando movimientos; ajustes usan
`tipo='ajuste'` + `signo_ajuste` ∈ {+1, -1}.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_008_cc"
down_revision: Union[str, None] = "compras_007_imp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cc_proveedor_movimientos",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("proveedor_id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("fecha_movimiento", sa.Date(), nullable=False),
        sa.Column("tipo", sa.String(length=8), nullable=False),
        sa.Column("signo_ajuste", sa.SmallInteger(), nullable=True),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("tipo_cambio_a_ars", sa.Numeric(18, 6), nullable=True),
        sa.Column("origen_tipo", sa.String(length=32), nullable=False),
        sa.Column("origen_id", sa.BigInteger(), nullable=True),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("creado_por_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["proveedor_id"],
            ["proveedores.id"],
            name="fk_ccpm_proveedor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["empresas.id"],
            name="fk_ccpm_empresa",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creado_por_id"],
            ["usuarios.id"],
            name="fk_ccpm_creado_por",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("tipo IN ('debe','haber','ajuste')", name="ck_ccpm_tipo"),
        sa.CheckConstraint("signo_ajuste IN (1, -1)", name="ck_ccpm_signo_ajuste_valores"),
        sa.CheckConstraint("monto > 0", name="ck_ccpm_monto_positivo"),
        sa.CheckConstraint("moneda IN ('ARS','USD')", name="ck_ccpm_moneda"),
        sa.CheckConstraint(
            "(tipo = 'ajuste' AND signo_ajuste IS NOT NULL) OR (tipo <> 'ajuste' AND signo_ajuste IS NULL)",
            name="chk_cc_ajuste_signo",
        ),
    )
    op.create_index(
        "ix_ccpm_proveedor_fecha",
        "cc_proveedor_movimientos",
        ["proveedor_id", sa.text("fecha_movimiento DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_ccpm_origen",
        "cc_proveedor_movimientos",
        ["origen_tipo", "origen_id"],
    )
    op.create_index(
        "ix_ccpm_empresa_proveedor",
        "cc_proveedor_movimientos",
        ["empresa_id", "proveedor_id"],
    )
    op.create_index(
        "ix_ccpm_proveedor_moneda",
        "cc_proveedor_movimientos",
        ["proveedor_id", "moneda"],
    )


def downgrade() -> None:
    op.drop_index("ix_ccpm_proveedor_moneda", table_name="cc_proveedor_movimientos")
    op.drop_index("ix_ccpm_empresa_proveedor", table_name="cc_proveedor_movimientos")
    op.drop_index("ix_ccpm_origen", table_name="cc_proveedor_movimientos")
    op.drop_index("ix_ccpm_proveedor_fecha", table_name="cc_proveedor_movimientos")
    op.drop_table("cc_proveedor_movimientos")
