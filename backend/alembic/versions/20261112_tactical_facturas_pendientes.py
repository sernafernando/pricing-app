"""tactical_facturas_pendientes: a sell in invoice total saved before its invoice, applied when Compras links it

Revision ID: 20261112_tactical_facturas_pendientes
Revises: 20261112_pedido_compra_arribo_progreso
Create Date: 2026-11-12

Sell in factura pendiente, monto total (owner: "la carga con factura de sell in tiene que poder cargarse y aplicar
recién cuando se agregue una factura no al revés"; orchestrator: pending table, the worker applies it with the same
code as a total loaded with the invoice). New table `tactical_facturas_pendientes`
(`app.models.tactical.TacticalFacturaPendiente`): one row per invoice total line whose operation had no supplier
invoice when it was saved. `sell_in_bono_cubre_pedido` also gates in an operation with a waiting row, so linking its
invoice queues it for the `sell_in.bono` worker. No existing row is touched.

The module copy (`app.services.sell_in.bono_queue.UPGRADE_SQL`) must equal the frozen copy below. The downgrade
puts back 20261112_sell_in_bono_cubre_pedido's gate, then drops the table (a waiting line is lost with it).
"""

from typing import List, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_tactical_facturas_pendientes"
down_revision: Union[str, None] = "20261112_pedido_compra_arribo_progreso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "tactical_facturas_pendientes"

# Frozen copies. *_UP: what this revision installs (the module's statement); *_DOWN: what it replaced.
FUNCIONES_UP: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_pedido(p_fecha DATE, p_pedido BIGINT) RETURNS BOOLEAN AS $fn$
    SELECT sell_in_bono_cubre(p_fecha) OR (p_fecha IS NOT NULL AND (
        EXISTS (
            SELECT 1 FROM sell_in_bonos_marca AS b
            WHERE b.estado = 'activa' AND b.alcance = 'factura' AND b.pedido_id = p_pedido
        )
        OR EXISTS (
            SELECT 1 FROM tactical_facturas_pendientes AS t
            WHERE t.estado = 'pendiente' AND t.pedido_id = p_pedido
        )
    ))
$fn$ LANGUAGE sql STABLE
""",
]

FUNCIONES_DOWN: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_pedido(p_fecha DATE, p_pedido BIGINT) RETURNS BOOLEAN AS $fn$
    SELECT sell_in_bono_cubre(p_fecha) OR (p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND b.alcance = 'factura' AND b.pedido_id = p_pedido
    ))
$fn$ LANGUAGE sql STABLE
""",
]


def upgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.create_table(
        TABLA,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tactical_id", sa.BigInteger(), sa.ForeignKey("tacticals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tactical_linea", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.BigInteger(), sa.ForeignKey("pedidos_compra.id", ondelete="CASCADE"), nullable=False),
        sa.Column("valor", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(16), nullable=False, server_default=sa.text("'pendiente'")),
        sa.Column(
            "compra_id", sa.BigInteger(), sa.ForeignKey("sell_in_compras.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("aplicada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'aplicada', 'anulada')", name="ck_tactical_facturas_pendientes_estado"
        ),
        sa.CheckConstraint(
            "(estado = 'aplicada') = (compra_id IS NOT NULL)", name="ck_tactical_facturas_pendientes_compra"
        ),
        sa.CheckConstraint("tactical_linea >= 1", name="ck_tactical_facturas_pendientes_linea"),
        sa.CheckConstraint("valor > 0", name="ck_tactical_facturas_pendientes_valor"),
        sa.CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_tactical_facturas_pendientes_moneda"),
    )
    op.create_index("ix_tactical_facturas_pendientes_tactical_id", TABLA, ["tactical_id"])
    op.create_index(
        "ix_tactical_facturas_pendientes_pedido_pendiente",
        TABLA,
        ["pedido_id"],
        postgresql_where=sa.text("estado = 'pendiente'"),
    )
    op.create_index("ix_tactical_facturas_pendientes_compra_id", TABLA, ["compra_id"])
    op.create_index("ix_tactical_facturas_pendientes_usuario_id", TABLA, ["usuario_id"])
    for statement in FUNCIONES_UP:
        op.execute(statement)


def downgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    for statement in FUNCIONES_DOWN:
        op.execute(statement)
    op.drop_table(TABLA)
