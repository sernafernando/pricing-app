"""compras 003 — pedidos_compra

Revision ID: compras_003_ped
Revises: compras_002_sd
Create Date: 2026-04-17

Tabla cabecera de pedidos de compra.
`ct_transaction_id` es FK LÓGICA a tb_commercial_transactions.ct_transaction
sin constraint físico (D1): el ERP sincroniza esa tabla externamente y
una FK real bloquearía el sync.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_003_ped"
down_revision: Union[str, None] = "compras_002_sd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pedidos_compra",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("numero", sa.String(length=32), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("proveedor_id", sa.Integer(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("fecha_pago_texto", sa.String(length=200), nullable=True),
        sa.Column("fecha_pago_estimada", sa.Date(), nullable=True),
        sa.Column(
            "requiere_envio",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("numero_factura", sa.String(length=50), nullable=True),
        sa.Column("ct_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "estado",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'borrador'"),
        ),
        sa.Column("creado_por_id", sa.Integer(), nullable=False),
        sa.Column("aprobado_por_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["empresas.id"],
            name="fk_pedidos_compra_empresa",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proveedor_id"],
            ["proveedores.id"],
            name="fk_pedidos_compra_proveedor",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creado_por_id"],
            ["usuarios.id"],
            name="fk_pedidos_compra_creado_por",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["aprobado_por_id"],
            ["usuarios.id"],
            name="fk_pedidos_compra_aprobado_por",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("numero", name="uq_pedidos_compra_numero"),
        sa.CheckConstraint("moneda IN ('ARS','USD')", name="ck_pedidos_compra_moneda"),
        sa.CheckConstraint("monto > 0", name="ck_pedidos_compra_monto_positivo"),
        sa.CheckConstraint(
            "estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',"
            "'cancelado','pagado_parcial','pagado')",
            name="ck_pedidos_compra_estado",
        ),
    )
    op.create_index(
        "ix_pedidos_compra_empresa_estado",
        "pedidos_compra",
        ["empresa_id", "estado"],
    )
    op.create_index(
        "ix_pedidos_compra_proveedor_created",
        "pedidos_compra",
        ["proveedor_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_pedidos_compra_numero_factura",
        "pedidos_compra",
        ["proveedor_id", "numero_factura"],
        postgresql_where=sa.text("numero_factura IS NOT NULL"),
    )
    op.create_index(
        "ix_pedidos_compra_ct_transaction",
        "pedidos_compra",
        ["ct_transaction_id"],
        postgresql_where=sa.text("ct_transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pedidos_compra_ct_transaction", table_name="pedidos_compra")
    op.drop_index("ix_pedidos_compra_numero_factura", table_name="pedidos_compra")
    op.drop_index("ix_pedidos_compra_proveedor_created", table_name="pedidos_compra")
    op.drop_index("ix_pedidos_compra_empresa_estado", table_name="pedidos_compra")
    op.drop_table("pedidos_compra")
