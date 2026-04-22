"""compras 023 — extender CHECK constraint de compras_adjuntos para NCs locales

Revision ID: compras_023_extend_adjuntos_nc
Revises: compras_022_aprobar_nc
Create Date: 2026-04-22

Modifica el CHECK constraint `ck_compras_adjuntos_entidad_tipo` para
agregar `'nota_credito_local'` como entidad válida. Permite que las NCs
locales tengan adjuntos (PDF de la NC del proveedor, comprobantes de
respaldo, etc.) reusando la misma tabla `compras_adjuntos` y el mismo
servicio.

Patrón consistente con pedidos_compra y orden_pago:
  POST /administracion/compras/ncs-locales/{id}/adjuntos
  GET  /administracion/compras/ncs-locales/{id}/adjuntos

Postgres permite drop + add en una sola transacción si nombramos el
constraint igual; lo más limpio es drop + add para evitar ambigüedad.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_023_extend_adjuntos_nc"
down_revision: Union[str, None] = "compras_022_aprobar_nc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop el CHECK viejo y crear uno nuevo con NC local incluida.
    # batch_alter_table funciona tanto en Postgres como en SQLite (tests).
    with op.batch_alter_table("compras_adjuntos") as batch_op:
        batch_op.drop_constraint("ck_compras_adjuntos_entidad_tipo", type_="check")
        batch_op.create_check_constraint(
            "ck_compras_adjuntos_entidad_tipo",
            "entidad_tipo IN ('pedido_compra','orden_pago','nota_credito_local')",
        )

    # También extendemos el CHECK de compras_eventos.entidad_tipo: el log
    # polimórfico hoy solo permite ('pedido_compra','orden_pago'). Las NCs
    # locales registran sus eventos en la misma tabla con entidad_tipo
    # = 'nota_credito_local'.
    with op.batch_alter_table("compras_eventos") as batch_op:
        batch_op.drop_constraint("ck_compras_eventos_entidad_tipo", type_="check")
        batch_op.create_check_constraint(
            "ck_compras_eventos_entidad_tipo",
            "entidad_tipo IN ('pedido_compra','orden_pago','nota_credito_local')",
        )


def downgrade() -> None:
    with op.batch_alter_table("compras_eventos") as batch_op:
        batch_op.drop_constraint("ck_compras_eventos_entidad_tipo", type_="check")
        batch_op.create_check_constraint(
            "ck_compras_eventos_entidad_tipo",
            "entidad_tipo IN ('pedido_compra','orden_pago')",
        )

    with op.batch_alter_table("compras_adjuntos") as batch_op:
        batch_op.drop_constraint("ck_compras_adjuntos_entidad_tipo", type_="check")
        batch_op.create_check_constraint(
            "ck_compras_adjuntos_entidad_tipo",
            "entidad_tipo IN ('pedido_compra','orden_pago')",
        )
