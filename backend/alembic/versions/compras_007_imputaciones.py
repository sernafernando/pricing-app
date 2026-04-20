"""compras 007 — imputaciones

Revision ID: compras_007_imp
Revises: compras_006_et
Create Date: 2026-04-17

Tabla polimórfica de imputaciones (append-only, D9).
origen_tipo / destino_tipo son VARCHAR abiertos; la whitelist v1 vive
en `imputaciones_service.COMBOS_VALIDOS_V1`. NO hay FKs físicas a
pedidos/OP porque son IDs polimórficos — intencional.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_007_imp"
down_revision: Union[str, None] = "compras_006_et"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "imputaciones",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("origen_tipo", sa.String(length=32), nullable=False),
        sa.Column("origen_id", sa.BigInteger(), nullable=False),
        sa.Column("destino_tipo", sa.String(length=32), nullable=False),
        sa.Column("destino_id", sa.BigInteger(), nullable=True),
        sa.Column("monto_imputado", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda_imputada", sa.String(length=3), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("proveedor_id", sa.Integer(), nullable=False),
        sa.Column(
            "es_reversal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reimputada_desde_id", sa.BigInteger(), nullable=True),
        sa.Column("creado_por_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["proveedor_id"],
            ["proveedores.id"],
            name="fk_imputaciones_proveedor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reimputada_desde_id"],
            ["imputaciones.id"],
            name="fk_imputaciones_reimputada_desde",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creado_por_id"],
            ["usuarios.id"],
            name="fk_imputaciones_creado_por",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("monto_imputado > 0", name="ck_imputaciones_monto_positivo"),
        sa.CheckConstraint("moneda_imputada IN ('ARS','USD')", name="ck_imputaciones_moneda"),
        sa.CheckConstraint(
            "(destino_tipo = 'saldo' AND destino_id IS NULL) OR (destino_tipo <> 'saldo' AND destino_id IS NOT NULL)",
            name="chk_imputacion_saldo_id",
        ),
    )
    op.create_index(
        "ix_imputaciones_proveedor_created",
        "imputaciones",
        ["proveedor_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_imputaciones_origen", "imputaciones", ["origen_tipo", "origen_id"])
    op.create_index(
        "ix_imputaciones_destino",
        "imputaciones",
        ["destino_tipo", "destino_id"],
        postgresql_where=sa.text("destino_id IS NOT NULL"),
    )
    op.create_index(
        "ix_imputaciones_reversal",
        "imputaciones",
        ["origen_id"],
        postgresql_where=sa.text("es_reversal = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_imputaciones_reversal", table_name="imputaciones")
    op.drop_index("ix_imputaciones_destino", table_name="imputaciones")
    op.drop_index("ix_imputaciones_origen", table_name="imputaciones")
    op.drop_index("ix_imputaciones_proveedor_created", table_name="imputaciones")
    op.drop_table("imputaciones")
