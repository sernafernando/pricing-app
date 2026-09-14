"""ml-ventas-modo-logistico PR5: total_gauss columns + deduction chain tables

Revision ID: 20260914_total_gauss
Revises: 20260914_cuarentena
Create Date: 2026-09-14

Nullable adds on `ml_orders_ops` (design D2 -- a materialised SORT/FILTER
key only, never the displayed value) plus two new tables: one for the
persisted per-order deduction amounts (design D1/D2), one for the "% de
varios" versioned rate (obs #2064 decision, reuses the `pricing_constants`
date-range PATTERN, not the row).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_total_gauss"
# Re-parented onto the quarantine migration rather than adding a merge
# revision: both were written off `20260911_costo_congelado` in parallel,
# and this one had not shipped yet. Two heads in `main` is an incident this
# project has already lived through once.
down_revision: Union[str, None] = "20260914_cuarentena"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_orders_ops", sa.Column("total_gauss", sa.Numeric(14, 2), nullable=True))
    op.add_column("ml_orders_ops", sa.Column("total_gauss_at", sa.DateTime(timezone=True), nullable=True))
    # INDEXED, because sorting is the column's ONLY purpose. `ml_orders_ops`
    # grows without bound and the listing's `ORDER BY max(total_gauss) DESC
    # NULLS LAST` would be a full sort on every page. Same reasoning, and
    # the same fix, as `ix_ml_ops_divergence_kind_state_detected_at` in this
    # very model file.
    op.create_index("ix_ml_orders_ops_total_gauss", "ml_orders_ops", ["total_gauss"])
    op.add_column(
        "ml_orders_ops",
        sa.Column("total_gauss_stale", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "ml_venta_deducciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("monto", sa.Numeric(14, 2), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", "code", name="uq_ml_venta_deducciones_order_code"),
    )
    op.create_index("ix_ml_venta_deducciones_order_id", "ml_venta_deducciones", ["order_id"])

    op.create_table(
        "ml_venta_varios_pct",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("porcentaje", sa.Numeric(5, 2), nullable=False),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=True),
        sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde",
            name="ck_ml_venta_varios_pct_fecha_rango",
        ),
    )
    op.create_index("ix_ml_venta_varios_pct_fecha_desde", "ml_venta_varios_pct", ["fecha_desde"])


def downgrade() -> None:
    op.drop_index("ix_ml_venta_varios_pct_fecha_desde", table_name="ml_venta_varios_pct")
    op.drop_table("ml_venta_varios_pct")
    op.drop_index("ix_ml_venta_deducciones_order_id", table_name="ml_venta_deducciones")
    op.drop_table("ml_venta_deducciones")
    op.drop_column("ml_orders_ops", "total_gauss_stale")
    op.drop_index("ix_ml_orders_ops_total_gauss", table_name="ml_orders_ops")
    op.drop_column("ml_orders_ops", "total_gauss_at")
    op.drop_column("ml_orders_ops", "total_gauss")
