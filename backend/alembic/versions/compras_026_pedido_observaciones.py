"""compras 026 — agregar pedidos_compra.observaciones

Revision ID: compras_026_pedido_observaciones
Revises: compras_025_ajuste_cc_manual
Create Date: 2026-04-24

Campo libre de texto editable en cualquier estado (borrador) y también
en aprobado/pagado_parcial/pagado (feature B — campos metadata editables
post-aprobación). No tiene impacto contable: vive en pedidos_compra (tabla
mutable) y no dispara escrituras en cc_proveedor_movimientos ni imputaciones.

Anchura: TEXT para no limitar el uso (notas auditoría, aclaraciones largas).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_026_pedido_observaciones"
down_revision: Union[str, None] = "compras_025_ajuste_cc_manual"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column(
            "observaciones",
            sa.Text(),
            nullable=True,
            comment=(
                "Notas libres del pedido. Editable en borrador y en "
                "aprobado/pagado_parcial/pagado como metadata (no afecta CC)."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("pedidos_compra", "observaciones")
