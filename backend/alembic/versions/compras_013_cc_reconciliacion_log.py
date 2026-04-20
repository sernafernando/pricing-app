"""compras 013 — cc_reconciliacion_log

Revision ID: compras_013_cc_recon
Revises: compras_012_seed_config
Create Date: 2026-04-17

Log de corridas diarias del cron de reconciliación CC (design §1.8, §8.2).
Compara saldo libro mayor propio (cc_proveedor_movimientos) vs snapshot
sincronizado desde el ERP (cuentas_corrientes_proveedores). Una fila por
(fecha_corrida, proveedor_id, moneda). `alerta_id` / `notificacion_id`
nullables apuntan a las tablas `alertas` / `notificaciones` existentes
para trazabilidad del banner agregado + feed individual (D6).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_013_cc_recon"
down_revision: Union[str, None] = "compras_012_seed_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cc_reconciliacion_log",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("fecha_corrida", sa.Date(), nullable=False),
        sa.Column("proveedor_id", sa.Integer(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("saldo_libro_mayor", sa.Numeric(18, 2), nullable=False),
        sa.Column("saldo_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("diferencia", sa.Numeric(18, 2), nullable=False),
        sa.Column("tolerancia_aplicada", sa.Numeric(18, 2), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("nota", sa.String(length=500), nullable=True),
        sa.Column("alerta_id", sa.Integer(), nullable=True),
        sa.Column("notificacion_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["proveedor_id"],
            ["proveedores.id"],
            name="fk_cc_recon_proveedor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["alerta_id"],
            ["alertas.id"],
            name="fk_cc_recon_alerta",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["notificacion_id"],
            ["notificaciones.id"],
            name="fk_cc_recon_notificacion",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("moneda IN ('ARS','USD')", name="ck_cc_recon_moneda"),
        sa.CheckConstraint("estado IN ('ok','divergencia')", name="ck_cc_recon_estado"),
        sa.UniqueConstraint(
            "fecha_corrida",
            "proveedor_id",
            "moneda",
            name="uq_reconciliacion_corrida",
        ),
    )
    op.create_index(
        "ix_reconciliacion_estado_fecha",
        "cc_reconciliacion_log",
        ["estado", sa.text("fecha_corrida DESC")],
    )
    op.create_index(
        "ix_reconciliacion_proveedor",
        "cc_reconciliacion_log",
        ["proveedor_id", sa.text("fecha_corrida DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliacion_proveedor", table_name="cc_reconciliacion_log")
    op.drop_index("ix_reconciliacion_estado_fecha", table_name="cc_reconciliacion_log")
    op.drop_table("cc_reconciliacion_log")
