"""compras_042: nullable documentary Factura/s and Pedido/s on pedidos_compra

Revision ID: compras_042_pedido_doc_refs
Revises: compras_041_oc_match_progress_phase
Create Date: 2026-09-22

Supplier invoice/PO tokens extracted by OC-match. Text NULL, no index.
Never touches numero_factura (ERP-only). Existing rows stay NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "compras_042_pedido_doc_refs"
down_revision: Union[str, None] = "compras_041_oc_match_progress_phase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column("facturas_documento", sa.Text(), nullable=True),
    )
    op.add_column(
        "pedidos_compra",
        sa.Column("pedidos_documento", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pedidos_compra", "pedidos_documento")
    op.drop_column("pedidos_compra", "facturas_documento")
