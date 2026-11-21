"""costo SI: every step stores the currency it is in

Revision ID: 20261126_costo_si_moneda
Revises: 20261125_costo_si_bono_unidad
Create Date: 2026-11-20

Owner L18: costo SI lives in the product's cost currency; an ARS-cost product averages in pesos (its USD invoices at
each invoice's own rate). `costo_si_pasos.moneda` says which currency a step's amounts are in; the `*_usd` columns keep
their names. Every row stored so far was computed in USD, so the column starts as 'USD'; the next recompute of an
ARS-cost product rewrites its history in pesos, with a backup (S8). The downgrade drops the column.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261126_costo_si_moneda"
down_revision: Union[str, None] = "20261125_costo_si_bono_unidad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("costo_si_pasos", sa.Column("moneda", sa.String(3), nullable=False, server_default=sa.text("'USD'")))


def downgrade() -> None:
    op.drop_column("costo_si_pasos", "moneda")
