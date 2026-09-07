"""drop ml_iibb_aliquots

The table was created by cut 1 of ml-ventas-desglose-costos to hold IIBB
aliquots for a `tax_service` that would compute each sale's withholdings.
That service was never built and never will be: Mercado Pago reports every
withholding already resolved, with its amount and its jurisdiction in the
charge name (`tax_withholding_sirtac-catamarca`). Nothing is calculated,
so there is no aliquot to store.

It never had a writer, a reader, or a single row. Left in place it is
worse than absent -- a table named for where the aliquots live is a trap
for whoever reads the schema next and assumes something fills it.

Revision ID: 20260907_drop_ml_iibb_aliquots
Revises: 20260907_ml_orders_ops_payments_synced_at
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_drop_ml_iibb_aliquots"
down_revision: Union[str, None] = "20260907_ml_orders_ops_payments_synced_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("ml_iibb_aliquots")


def downgrade() -> None:
    # Recreated exactly as 20260904_ml_billing_schema declared it, so the
    # chain stays reversible. The rows are not coming back, but there were
    # never any to lose.
    op.create_table(
        "ml_iibb_aliquots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("porcentaje", sa.Numeric(6, 4), nullable=False),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["creado_por"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="chk_ml_iibb_aliquots_fecha_hasta"
        ),
    )
