"""Add client shipping columns to rma_caso_items

New columns for tracking shipments back to the customer:
- listo_envio_cliente: marked as ready to ship to client
- enviado_cliente: already shipped to client
- shipping_cliente_id: FK to etiquetas_envio.shipping_id
- fecha_envio_cliente: datetime of shipment to client

Revision ID: 20260305_rma_envio_cli
Revises: 20260305_rma_fill_ean
Create Date: 2026-03-05

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_rma_envio_cli"
down_revision = "20260305_rma_fill_ean"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rma_caso_items",
        sa.Column("listo_envio_cliente", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "rma_caso_items",
        sa.Column("enviado_cliente", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "rma_caso_items",
        sa.Column(
            "shipping_cliente_id",
            sa.String(50),
            sa.ForeignKey("etiquetas_envio.shipping_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "rma_caso_items",
        sa.Column("fecha_envio_cliente", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_rma_caso_items_shipping_cliente_id",
        "rma_caso_items",
        ["shipping_cliente_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rma_caso_items_shipping_cliente_id", table_name="rma_caso_items")
    op.drop_column("rma_caso_items", "fecha_envio_cliente")
    op.drop_column("rma_caso_items", "shipping_cliente_id")
    op.drop_column("rma_caso_items", "enviado_cliente")
    op.drop_column("rma_caso_items", "listo_envio_cliente")
