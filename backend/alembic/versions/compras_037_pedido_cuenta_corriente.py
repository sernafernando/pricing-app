"""compras_037: pedido en_cuenta_corriente + pagado_en + op_cuenta_corriente_id

Revision ID: compras_037_pedido_cuenta_corriente
Revises: 20260722_anomalias_vinc
Create Date: 2026-07-22

Slice 1 of `compras-cuenta-corriente`: decouples the OP payment axis from
the pedido recepción/logistics axis via a new estado `en_cuenta_corriente`.

- Adds `en_cuenta_corriente` to the `pedidos_compra.estado` CheckConstraint.
- Adds `pagado_en` (nullable timestamp) — the canonical "fully settled"
  accounting signal, orthogonal to `estado`.
- Adds `op_cuenta_corriente_id` (nullable FK -> ordenes_pago.id) — links the
  single pendiente OP created at mark-time for O(1) reversal lookup.

Uses `batch_alter_table` so the CheckConstraint recreate is safe on both
SQLite (CI/tests) and Postgres (prod).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "compras_037_pedido_cuenta_corriente"
down_revision = "20260722_anomalias_vinc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pedidos_compra") as batch_op:
        batch_op.drop_constraint("ck_pedidos_compra_estado", type_="check")
        batch_op.create_check_constraint(
            "ck_pedidos_compra_estado",
            "estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',"
            "'cancelado','pagado_parcial','pagado','recibido','con_faltantes',"
            "'controlado','en_cuenta_corriente')",
        )
        batch_op.add_column(sa.Column("pagado_en", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("op_cuenta_corriente_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_pedidos_compra_op_cuenta_corriente",
            "ordenes_pago",
            ["op_cuenta_corriente_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_pedidos_compra_op_cuenta_corriente",
            ["op_cuenta_corriente_id"],
        )


def downgrade() -> None:
    # Guard: refuse to downgrade if any row currently uses the new estado —
    # the restored CheckConstraint would reject them and corrupt the column.
    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT COUNT(*) FROM pedidos_compra WHERE estado = 'en_cuenta_corriente'")).scalar()
    if count:
        raise RuntimeError(
            f"No se puede downgradear: {count} pedidos_compra en estado "
            "'en_cuenta_corriente'. Revertir esos pedidos primero."
        )

    with op.batch_alter_table("pedidos_compra") as batch_op:
        batch_op.drop_index("ix_pedidos_compra_op_cuenta_corriente")
        batch_op.drop_constraint("fk_pedidos_compra_op_cuenta_corriente", type_="foreignkey")
        batch_op.drop_column("op_cuenta_corriente_id")
        batch_op.drop_column("pagado_en")
        batch_op.drop_constraint("ck_pedidos_compra_estado", type_="check")
        batch_op.create_check_constraint(
            "ck_pedidos_compra_estado",
            "estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',"
            "'cancelado','pagado_parcial','pagado','recibido','con_faltantes','controlado')",
        )
