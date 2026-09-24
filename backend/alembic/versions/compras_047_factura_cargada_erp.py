"""compras 047 — per-factura ERP cargada check + pending-alert clock

Revision ID: compras_047_factura_cargada_erp
Revises: compras_045_pedido_compra_ocs
Create Date: 2026-09-23

Adds check columns on `pedido_factura_documentos`. Existing rows stay
`cargada=false` (server default). No backfill of cargada=true.

Partial index covers the sweep of still-checked rows whose pending
alert window has been reached.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_047_factura_cargada_erp"
down_revision: Union[str, None] = "compras_045_pedido_compra_ocs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("cargada", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("cargada_marked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("cargada_marked_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("alerta_pendiente_hasta", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("alerta_disparada_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_pedido_factura_documentos_cargada_marked_by_id",
        "pedido_factura_documentos",
        "usuarios",
        ["cargada_marked_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_pedido_factura_documentos_alerta_pendiente",
        "pedido_factura_documentos",
        ["alerta_pendiente_hasta"],
        postgresql_where=sa.text(
            "cargada = true AND alerta_disparada_at IS NULL AND alerta_pendiente_hasta IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pedido_factura_documentos_alerta_pendiente",
        table_name="pedido_factura_documentos",
    )
    op.drop_constraint(
        "fk_pedido_factura_documentos_cargada_marked_by_id",
        "pedido_factura_documentos",
        type_="foreignkey",
    )
    op.drop_column("pedido_factura_documentos", "alerta_disparada_at")
    op.drop_column("pedido_factura_documentos", "alerta_pendiente_hasta")
    op.drop_column("pedido_factura_documentos", "cargada_marked_by_id")
    op.drop_column("pedido_factura_documentos", "cargada_marked_at")
    op.drop_column("pedido_factura_documentos", "cargada")
