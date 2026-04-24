"""compras 027 — corregido_desde_id + corregido_a_id en pedidos_compra

Revision ID: compras_027_pedido_corregido
Revises: compras_026_pedido_observaciones
Create Date: 2026-04-24

Feature D — "Corregir pedido": clonación append-only bidireccional de un
pedido aprobado/pagado_parcial/pagado hacia uno nuevo que lo reemplaza.

Dos FKs self-referencing en `pedidos_compra`:

  * `corregido_desde_id` — en el clon, apunta al original que se corrigió.
  * `corregido_a_id`     — en el original, apunta al clon resultante.

Ambas son NULL por default; solo se setean cuando se ejecuta una
corrección vía `POST /pedidos/{id}/corregir`. `ON DELETE SET NULL` para
permitir hard-delete del par sin violar la FK (el histórico queda en
`compras_eventos`).

Índices parciales (solo filas no-NULL) para lookups O(log n) de la cadena
de correcciones:
  * `ix_pedidos_compra_corregido_desde_id` — "dame todos los clones que
    apuntan al original X" (casi siempre 1 resultado, pero permitido).
  * `ix_pedidos_compra_corregido_a_id` — simétrico.

No cambia el CheckConstraint de estados: un clon puede nacer en
`pendiente_aprobacion` (si cambió monto/TC) o `aprobado` (si solo
cosméticos); el original queda en `cancelado`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_027_pedido_corregido"
down_revision: Union[str, None] = "compras_026_pedido_observaciones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column(
            "corregido_desde_id",
            sa.BigInteger(),
            sa.ForeignKey("pedidos_compra.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "Si no-NULL, este pedido es un clon corrección del "
                "referenciado. Feature D."
            ),
        ),
    )
    op.add_column(
        "pedidos_compra",
        sa.Column(
            "corregido_a_id",
            sa.BigInteger(),
            sa.ForeignKey("pedidos_compra.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "Si no-NULL, este pedido fue reemplazado por el clon "
                "referenciado (original cancelado). Feature D."
            ),
        ),
    )
    op.create_index(
        "ix_pedidos_compra_corregido_desde_id",
        "pedidos_compra",
        ["corregido_desde_id"],
        postgresql_where=sa.text("corregido_desde_id IS NOT NULL"),
    )
    op.create_index(
        "ix_pedidos_compra_corregido_a_id",
        "pedidos_compra",
        ["corregido_a_id"],
        postgresql_where=sa.text("corregido_a_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pedidos_compra_corregido_a_id", table_name="pedidos_compra")
    op.drop_index(
        "ix_pedidos_compra_corregido_desde_id",
        table_name="pedidos_compra",
    )
    op.drop_column("pedidos_compra", "corregido_a_id")
    op.drop_column("pedidos_compra", "corregido_desde_id")
