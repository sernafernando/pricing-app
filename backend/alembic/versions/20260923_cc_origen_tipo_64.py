"""origen_tipo: 32 -> 64 en cc_proveedor_movimientos e imputaciones

Revision ID: 20260923_cc_origen_tipo_64
Revises: 20260922_ix_producto_item_id
Create Date: 2026-09-23

`cancelacion_pedido_por_correccion` is 33 characters and the column was
`VARCHAR(32)`, so Postgres rejected the insert and "corregir pedido"
answered 500 for any pedido that already had CC movements. The value has
been in the code since April 2026; the suite runs on SQLite, which
ignores VARCHAR lengths, so nothing caught it until production did.

Widening is preferred over shortening the literal: the value is written
in the service, read back in the router and documented, and existing
rows are not touched. Growing a VARCHAR in Postgres is a catalog-only
change -- no table rewrite, no long lock.

`imputaciones.origen_tipo` holds the same vocabulary and had the same
32-character ceiling, so it is widened together: leaving it behind would
just move the trap one table over.

Downgrade narrows back to 32 and would fail if a longer value is already
stored, which is correct: it refuses rather than truncating money audit
rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_cc_origen_tipo_64"
down_revision: Union[str, None] = "20260922_ix_producto_item_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLAS = ("cc_proveedor_movimientos", "imputaciones")


def upgrade() -> None:
    for tabla in _TABLAS:
        op.alter_column(
            tabla,
            "origen_tipo",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    for tabla in _TABLAS:
        op.alter_column(
            tabla,
            "origen_tipo",
            existing_type=sa.String(length=64),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
