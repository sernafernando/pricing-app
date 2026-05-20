"""compras 029 — tipo_cambio_original en pedidos_compra

Revision ID: compras_029_pedido_tipo_cambio_original
Revises: compras_028_op_actualizar_tc_pedido
Create Date: 2026-05-20

Feature F1 — TC Re-valuation:

Agrega `tipo_cambio_original` a `pedidos_compra`.

  * Captura el TC al momento de la aprobación del pedido (inmutable después).
  * NULL es válido para pedidos ARS (sin TC) o pedidos históricos aprobados
    antes de este feature si `tipo_cambio` también era NULL.
  * Backfill: `UPDATE pedidos_compra SET tipo_cambio_original = tipo_cambio`
    — todos los pedidos existentes heredan el TC actual como referencia original.

`tipo_cambio` sigue existiendo pero su semántica cambia: pasa a ser el
"TC efectivo cache" (materializado en cada `ejecutar_pago`), derivado por
`pedidos_service.resolver_tc_efectivo_pedido`. `tipo_cambio_original` es el
snapshot inmutable del TC al aprobar.

Este cambio NO altera el comportamiento de ningún endpoint existente: el TC
efectivo cache se actualiza solo cuando F1 está en juego (Caso A).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "compras_029_pedido_tipo_cambio_original"
down_revision = "compras_028_op_actualizar_tc_pedido"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column(
            "tipo_cambio_original",
            sa.Numeric(18, 6),
            nullable=True,
        ),
    )
    # Backfill: existing rows inherit the current tipo_cambio as the original reference.
    op.execute("UPDATE pedidos_compra SET tipo_cambio_original = tipo_cambio")


def downgrade() -> None:
    op.drop_column("pedidos_compra", "tipo_cambio_original")
