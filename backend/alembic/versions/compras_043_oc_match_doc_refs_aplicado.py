"""compras_043: nullable TZ stamp for OC-match doc-ref write-once

Revision ID: compras_043_oc_match_doc_refs_aplicado
Revises: compras_042_pedido_doc_refs
Create Date: 2026-09-22

Write-once guard for Factura/s and Pedido/s write-back. DateTime TZ NULL,
no index. Existing jobs stay NULL so the next persist can still write.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "compras_043_oc_match_doc_refs_aplicado"
down_revision: Union[str, None] = "compras_042_pedido_doc_refs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "compras_oc_match_jobs",
        sa.Column("doc_refs_aplicado_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("compras_oc_match_jobs", "doc_refs_aplicado_at")
