"""compras 005 — ordenes_pago

Revision ID: compras_005_op
Revises: compras_004_evt
Create Date: 2026-04-17

Órdenes de pago a proveedor. Integración con módulo Cajas via
caja_movimiento_id + caja_documento_id (ON DELETE RESTRICT para
preservar trazabilidad bidireccional).

NOTA: el design §1.3 indica `caja_movimiento_id BIGINT` pero
`caja_movimientos.id` es INTEGER en el modelo existente — alineamos
ambos tipos a INTEGER para que la FK sea válida.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_005_op"
down_revision: Union[str, None] = "compras_004_evt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ordenes_pago",
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
        sa.Column("monto_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("modo_imputacion", sa.String(length=16), nullable=False),
        sa.Column(
            "estado",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column("caja_id", sa.Integer(), nullable=True),
        sa.Column("caja_movimiento_id", sa.Integer(), nullable=True),
        sa.Column("caja_documento_id", sa.Integer(), nullable=True),
        sa.Column("fecha_pago_estimada", sa.Date(), nullable=True),
        sa.Column("fecha_pago_real", sa.Date(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("creado_por_id", sa.Integer(), nullable=False),
        sa.Column("pagado_por_id", sa.Integer(), nullable=True),
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
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["empresas.id"],
            name="fk_ordenes_pago_empresa",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proveedor_id"],
            ["proveedores.id"],
            name="fk_ordenes_pago_proveedor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["caja_id"],
            ["cajas.id"],
            name="fk_ordenes_pago_caja",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["caja_movimiento_id"],
            ["caja_movimientos.id"],
            name="fk_ordenes_pago_caja_movimiento",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["caja_documento_id"],
            ["caja_documentos.id"],
            name="fk_ordenes_pago_caja_documento",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creado_por_id"],
            ["usuarios.id"],
            name="fk_ordenes_pago_creado_por",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pagado_por_id"],
            ["usuarios.id"],
            name="fk_ordenes_pago_pagado_por",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("numero", name="uq_ordenes_pago_numero"),
        sa.CheckConstraint("moneda IN ('ARS','USD')", name="ck_ordenes_pago_moneda"),
        sa.CheckConstraint("monto_total > 0", name="ck_ordenes_pago_monto_positivo"),
        sa.CheckConstraint(
            "modo_imputacion IN ('especifica','a_cuenta','mixta')",
            name="ck_ordenes_pago_modo_imputacion",
        ),
        sa.CheckConstraint(
            "estado IN ('pendiente','pagado','anulado')",
            name="ck_ordenes_pago_estado",
        ),
    )
    op.create_index(
        "ix_ordenes_pago_proveedor_estado",
        "ordenes_pago",
        ["proveedor_id", "estado"],
    )
    op.create_index(
        "ix_ordenes_pago_empresa_created",
        "ordenes_pago",
        ["empresa_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_ordenes_pago_caja_mov",
        "ordenes_pago",
        ["caja_movimiento_id"],
        postgresql_where=sa.text("caja_movimiento_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ordenes_pago_caja_mov", table_name="ordenes_pago")
    op.drop_index("ix_ordenes_pago_empresa_created", table_name="ordenes_pago")
    op.drop_index("ix_ordenes_pago_proveedor_estado", table_name="ordenes_pago")
    op.drop_table("ordenes_pago")
