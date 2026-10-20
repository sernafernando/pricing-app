"""pedidos_compra.fecha_factura: app-side copy of the linked invoice date

Revision ID: 20261103_pedidos_fecha_factura
Revises: 20261102_sell_in_compra_pedidos
Create Date: 2026-10-19

sell-in-sell-out T3c-1. The brand sell in must read only app tables, so each
Compras operation keeps the date of its linked supplier invoice. From now on
`erp_matching_service.asignar_factura_erp` writes it together with
`ct_transaction_id`; this upgrade fills it for the operations already linked.

- `fecha_factura` = date part of `v_facturas_compra_vigentes.ct_date` (the ERP
  naive wall-clock document date, no zone shift).
- A link whose ct is not in the view (annulled since, or never a valid
  purchase invoice) stays NULL, as the service does.
- `date(...)` and the correlated subquery run unchanged on Postgres and on the
  SQLite test schema (tests/unit/test_migration_pedidos_compra_fecha_factura.py).

The downgrade drops the column; `ct_transaction_id` still holds every link.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_pedidos_fecha_factura"
down_revision: Union[str, None] = "20261102_sell_in_compra_pedidos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKFILL = """
UPDATE pedidos_compra
SET fecha_factura = (
    SELECT date(v.ct_date)
    FROM v_facturas_compra_vigentes v
    WHERE v.ct_transaction = pedidos_compra.ct_transaction_id
)
WHERE ct_transaction_id IS NOT NULL
"""


def upgrade() -> None:
    op.add_column("pedidos_compra", sa.Column("fecha_factura", sa.Date(), nullable=True))
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_column("pedidos_compra", "fecha_factura")
