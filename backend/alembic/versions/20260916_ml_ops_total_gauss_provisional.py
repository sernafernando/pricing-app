"""total_gauss_provisional column on ml_orders_ops (total-gauss-provisorio)

Revision ID: 20260916_total_gauss_provisorio
Revises: 20260916_ml_ops_varios_editar
Create Date: 2026-09-16

A `self_service` (Flex) sale has no freight cost until the shipping label
is loaded at the warehouse -- which happens AFTER the sale is ingested.
Until then, `deducciones.calcular_total_gauss` used to resolve
`total_gauss` to `None` for the whole order, even though every other link
of the chain (cost of goods, "% de varios") is already known.

Product owner's decision (verbatim): "al principio mostrarlo sin envío,
quizás con un badge o algo que marque que falta el envío y después se
actualiza cuando está el envío". This column persists that flag alongside
`total_gauss` (written by `persistir_total_gauss`, same place/transaction
as the amount itself) so the sort/filter key row can carry the same badge
the live, always-recomputed value does -- never a second source of truth
for the number, only for whether it is provisional.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260916_total_gauss_provisorio"
down_revision: Union[str, None] = "20260916_ml_ops_varios_editar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_orders_ops",
        sa.Column(
            "total_gauss_provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("ml_orders_ops", "total_gauss_provisional")
