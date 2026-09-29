"""ml_group_metrics (ventas-ml-rediseno PR20)

Revision ID: 20260929_ml_group_metrics
Revises: compras_047_factura_cargada_erp
Create Date: 2026-09-29

Per-GROUP stored Gauss metrics table (spec `ml-order-stored-metrics`
R9-R14). New table only -- this migration never edits the PR1/PR4/PR5
frozen migrations (`triggers.py:22-33` immutability contract).

down_revision must be the unique alembic head at merge time (branch tip
`compras_047_factura_cargada_erp`; rehang if main advanced).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260929_ml_group_metrics"
down_revision: Union[str, None] = "compras_047_factura_cargada_erp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_group_metrics",
        sa.Column("group_key", sa.String(32), nullable=False),
        sa.Column("neto", sa.Numeric(14, 2), nullable=True),
        sa.Column("neto_sin_iva", sa.Numeric(14, 2), nullable=True),
        sa.Column("costo_mercaderia", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_gauss", sa.Numeric(14, 2), nullable=True),
        sa.Column("markup_pct", sa.Numeric(9, 2), nullable=True),
        sa.Column("gauss_status", sa.String(16), nullable=False),
        sa.Column("member_order_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("group_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("formula_version", sa.SmallInteger(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("group_key"),
        sa.CheckConstraint("gauss_status IN ('ok', 'provisional', 'unresolved')", name="ck_ml_group_metrics_status"),
    )
    op.create_index("ix_ml_group_metrics_status", "ml_group_metrics", ["gauss_status"])
    op.create_index(
        "ix_ml_group_metrics_member_order_ids",
        "ml_group_metrics",
        ["member_order_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_ml_group_metrics_member_order_ids", table_name="ml_group_metrics")
    op.drop_index("ix_ml_group_metrics_status", table_name="ml_group_metrics")
    op.drop_table("ml_group_metrics")
