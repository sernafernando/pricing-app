"""compras 024 — agregar estado 'cancelado' a ordenes_pago

Revision ID: compras_024_op_estado_cancelado
Revises: compras_023_extend_adjuntos_nc
Create Date: 2026-04-24

Extiende el CHECK constraint `ck_ordenes_pago_estado` para incluir
`cancelado` como nuevo estado terminal. Semántica:

  - `pendiente`  → OP creada pero aún no ejecutada; NO tocó caja ni CC.
  - `pagado`     → OP ejecutada; movimiento de caja + imputaciones creadas.
  - `anulado`    → OP que estuvo pagada y fue revertida (reverso completo).
  - `cancelado`  → OP pendiente descartada (nunca pagó, nunca tocó imputaciones).
                   Transición segura porque NO hay nada que revertir — los
                   items viven sólo en `compras_eventos` como payload.

Append-only sagrado: la transición a `cancelado` genera evento
`op_cancelada_pendiente` con motivo. No se UPDATE/DELETE imputaciones ni
cc_proveedor_movimientos porque no existen todavía en estado `pendiente`.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "compras_024_op_estado_cancelado"
down_revision: Union[str, None] = "20260423_rma_control_deposito"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ordenes_pago") as batch_op:
        batch_op.drop_constraint("ck_ordenes_pago_estado", type_="check")
        batch_op.create_check_constraint(
            "ck_ordenes_pago_estado",
            "estado IN ('pendiente','pagado','anulado','cancelado')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ordenes_pago") as batch_op:
        batch_op.drop_constraint("ck_ordenes_pago_estado", type_="check")
        batch_op.create_check_constraint(
            "ck_ordenes_pago_estado",
            "estado IN ('pendiente','pagado','anulado')",
        )
