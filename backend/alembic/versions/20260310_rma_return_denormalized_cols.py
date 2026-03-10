"""Desnormalizar campos de devolución en rma_claims_ml

Extrae los campos clave de return_data (JSONB) a columnas dedicadas
para poder filtrar eficientemente las devoluciones que vuelven al local
sin tener que parsear el JSONB en cada query.

Columnas:
- return_status: estado general de la devolución (pending, shipped, delivered...)
- return_shipment_status: estado del envío físico (pending, ready_to_ship, shipped...)
- return_destination: destino del paquete (seller_address = local, warehouse = fulfillment)
- return_tracking: número de seguimiento del correo
- return_shipment_type: tipo de envío (return, return_from_triage)

Backfill: extrae datos de return_data JSONB existente para poblar las nuevas columnas.

Revision ID: 20260310_return_denorm
Revises: 20260309_permiso_seg_envios
Create Date: 2026-03-10

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260310_return_denorm"
down_revision = "20260309_permiso_seg_envios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add denormalized columns
    op.add_column(
        "rma_claims_ml",
        sa.Column("return_status", sa.String(50), nullable=True),
    )
    op.add_column(
        "rma_claims_ml",
        sa.Column("return_shipment_status", sa.String(50), nullable=True),
    )
    op.add_column(
        "rma_claims_ml",
        sa.Column("return_destination", sa.String(50), nullable=True),
    )
    op.add_column(
        "rma_claims_ml",
        sa.Column("return_tracking", sa.String(100), nullable=True),
    )
    op.add_column(
        "rma_claims_ml",
        sa.Column("return_shipment_type", sa.String(50), nullable=True),
    )

    # Indexes for efficient filtering
    op.create_index(
        "idx_rma_claims_ml_return_destination",
        "rma_claims_ml",
        ["return_destination"],
    )
    op.create_index(
        "idx_rma_claims_ml_return_status",
        "rma_claims_ml",
        ["return_status"],
    )

    # Backfill from existing return_data JSONB
    # Uses PostgreSQL JSONB operators to extract nested data
    op.execute(
        """
        UPDATE rma_claims_ml
        SET
            return_status = return_data ->> 'status',
            return_shipment_status = return_data -> 'shipments' -> 0 ->> 'status',
            return_destination = return_data -> 'shipments' -> 0 ->> 'destination_name',
            return_tracking = return_data -> 'shipments' -> 0 ->> 'tracking_number',
            return_shipment_type = return_data -> 'shipments' -> 0 ->> 'shipment_type'
        WHERE return_data IS NOT NULL
          AND return_data ->> 'status' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_rma_claims_ml_return_status", table_name="rma_claims_ml")
    op.drop_index("idx_rma_claims_ml_return_destination", table_name="rma_claims_ml")
    op.drop_column("rma_claims_ml", "return_shipment_type")
    op.drop_column("rma_claims_ml", "return_tracking")
    op.drop_column("rma_claims_ml", "return_destination")
    op.drop_column("rma_claims_ml", "return_shipment_status")
    op.drop_column("rma_claims_ml", "return_status")
