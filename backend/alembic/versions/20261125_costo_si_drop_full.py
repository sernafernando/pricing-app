"""costo SI: drop the Full operations tables

Revision ID: 20261125_costo_si_drop_full
Revises: 20261125_costo_si
Create Date: 2026-11-20

`costo_si_full_operaciones` and `costo_si_full_cobertura` kept Mercado Libre's Full stock operations, fetched from the
ML operations API. Costo SI now rebuilds past Full stock from the ML stock and sales the app already stores
(`services/costo_si/full_ml.py`, owner L11), so nothing writes or reads them. Never filled in prod: the fetch never
completed a coverage window there. The downgrade recreates them empty, exactly as `20261125_costo_si` did.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261125_costo_si_drop_full"
down_revision: Union[str, None] = "20261125_costo_si"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("costo_si_full_cobertura")
    op.drop_index("ix_costo_si_full_operaciones_inv_fecha", table_name="costo_si_full_operaciones")
    op.drop_table("costo_si_full_operaciones")


def downgrade() -> None:
    op.create_table(
        "costo_si_full_operaciones",
        sa.Column("operation_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("inventory_id", sa.Text(), nullable=False),
        sa.Column("date_created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("disponible", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_costo_si_full_operaciones_inv_fecha", "costo_si_full_operaciones", ["inventory_id", "date_created"]
    )
    op.create_table(
        "costo_si_full_cobertura",
        sa.Column("inventory_id", sa.Text(), primary_key=True),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
