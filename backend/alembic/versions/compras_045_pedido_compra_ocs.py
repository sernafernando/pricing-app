"""compras_045: pedido_compra_ocs multi-OC relation (D-MULTI)

Revision ID: compras_045_pedido_compra_ocs
Revises: compras_046_seed_ver_alertas_factura
Create Date: 2026-09-23

PR4 of compras-ops-pipeline-ux. Relation table is SoT for N OC triples.
Existing header oc_* is first-link cache — copy into the first row.
Unique (pedido_id, oc_comp_id, oc_bra_id, oc_poh_id); index on oc_poh_id.

Design.md previously listed this as compras_043; main/PR1 already consumed
compras_042 / compras_043 / compras_044.

Rehang (D-046): 046 landed on PR2 parenting 044. Single-head chain is
044 → 046 → 045.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "compras_045_pedido_compra_ocs"
down_revision: Union[str, None] = "compras_046_seed_ver_alertas_factura"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pedido_compra_ocs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("pedido_id", sa.BigInteger(), nullable=False),
        sa.Column("oc_comp_id", sa.Integer(), nullable=False),
        sa.Column("oc_bra_id", sa.Integer(), nullable=False),
        sa.Column("oc_poh_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pedido_id"],
            ["pedidos_compra.id"],
            name="fk_pedido_compra_ocs_pedido_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pedido_id",
            "oc_comp_id",
            "oc_bra_id",
            "oc_poh_id",
            name="uq_pedido_compra_ocs_triple",
        ),
    )
    op.create_index("ix_pedido_compra_ocs_pedido_id", "pedido_compra_ocs", ["pedido_id"])
    op.create_index("ix_pedido_compra_ocs_oc_poh_id", "pedido_compra_ocs", ["oc_poh_id"])

    op.execute(
        """
        INSERT INTO pedido_compra_ocs (pedido_id, oc_comp_id, oc_bra_id, oc_poh_id, created_at)
        SELECT id, oc_comp_id, oc_bra_id, oc_poh_id, CURRENT_TIMESTAMP
        FROM pedidos_compra
        WHERE oc_poh_id IS NOT NULL
          AND oc_comp_id IS NOT NULL
          AND oc_bra_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_pedido_compra_ocs_oc_poh_id", table_name="pedido_compra_ocs")
    op.drop_index("ix_pedido_compra_ocs_pedido_id", table_name="pedido_compra_ocs")
    op.drop_table("pedido_compra_ocs")
