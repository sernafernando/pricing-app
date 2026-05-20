"""compras 028 — actualizar_tc_pedido en ordenes_pago

Revision ID: compras_028_op_actualizar_tc_pedido
Revises: compras_027a_widen_version
Create Date: 2026-05-20

Feature F1 — TC Re-valuation via OP Checkbox "Actualizar TC del pedido":

Agrega el campo booleano `actualizar_tc_pedido` a `ordenes_pago`.

  * TRUE  → Caso A: el pago aporta al promedio ponderado del TC del pedido.
  * FALSE → Caso B: el pago se registra normalmente sin modificar el TC efectivo.

El valor es inmutable después de que la OP pasa a estado 'pagado'. Se setea
al momento de la creación de la OP y no se modifica durante `ejecutar_pago`.

`server_default='false'` garantiza que filas históricas lean como Caso B
(comportamiento previo: sin actualización de TC), lo cual es semánticamente
correcto — las OPs anteriores al feature no participan del promedio.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "compras_028_op_actualizar_tc_pedido"
down_revision = "compras_027a_widen_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ordenes_pago",
        sa.Column(
            "actualizar_tc_pedido",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("ordenes_pago", "actualizar_tc_pedido")
