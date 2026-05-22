"""compras_035: tabla dinero_a_cuenta — tracking de overpay dentro del CC

Revision ID: compras_035_dinero_a_cuenta
Revises: compras_034_wipe_permiso
Create Date: 2026-05-22

Dinero a cuenta es el componente real-money del saldo a favor del CC.
No es un ledger divorciado: el dinero real vive en cc_proveedor_movimientos.
Esta tabla es un índice navegable con lifecycle (disponible → consumido).
El saldo consumible se deriva de las imputaciones (append-only, AD-3).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "compras_035_dinero_a_cuenta"
down_revision = "compras_034_wipe_permiso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crea la tabla dinero_a_cuenta con todos los CHECK e índices."""
    op.create_table(
        "dinero_a_cuenta",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "empresa_id",
            sa.Integer(),
            sa.ForeignKey("empresas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "monto",
            sa.Numeric(18, 2),
            nullable=False,
            comment="Monto original creado. Inmutable.",
        ),
        sa.Column(
            "moneda",
            sa.String(3),
            nullable=False,
            comment="Per-moneda — ARS o USD. No cross-moneda.",
        ),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default="disponible",
            comment="Cache derivado (AD-3): disponible | consumido_parcial | consumido.",
        ),
        sa.Column(
            "origen_op_id",
            sa.BigInteger(),
            sa.ForeignKey("ordenes_pago.id", ondelete="RESTRICT"),
            nullable=False,
            comment="OP que lo originó (el pago_a_cuenta).",
        ),
        sa.Column(
            "creado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # Primary key
        sa.PrimaryKeyConstraint("id"),
        # CHECK constraints
        sa.CheckConstraint("monto > 0", name="ck_dac_monto_positivo"),
        sa.CheckConstraint("moneda IN ('ARS','USD')", name="ck_dac_moneda"),
        sa.CheckConstraint(
            "estado IN ('disponible','consumido_parcial','consumido')",
            name="ck_dac_estado",
        ),
    )

    # Indexes
    op.create_index(
        "ix_dinero_a_cuenta_proveedor_estado",
        "dinero_a_cuenta",
        ["proveedor_id", "estado"],
    )
    op.create_index(
        "ix_dinero_a_cuenta_proveedor_moneda",
        "dinero_a_cuenta",
        ["proveedor_id", "moneda"],
    )
    op.create_index(
        "ix_dinero_a_cuenta_origen_op",
        "dinero_a_cuenta",
        ["origen_op_id"],
    )


def downgrade() -> None:
    """Elimina la tabla dinero_a_cuenta y sus índices."""
    op.drop_index("ix_dinero_a_cuenta_origen_op", table_name="dinero_a_cuenta")
    op.drop_index("ix_dinero_a_cuenta_proveedor_moneda", table_name="dinero_a_cuenta")
    op.drop_index("ix_dinero_a_cuenta_proveedor_estado", table_name="dinero_a_cuenta")
    op.drop_table("dinero_a_cuenta")
