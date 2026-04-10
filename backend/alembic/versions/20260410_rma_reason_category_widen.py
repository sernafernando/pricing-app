"""Widen rma_claims_ml.reason_category from varchar(10) to varchar(100).

ML returns full category names like 'Producto Diferente o Defectuoso'
instead of short codes. The previous limit caused StringDataRightTruncation.

Revision ID: 20260410_rma_reason
Revises: 20260408_caja_tags
Create Date: 2026-04-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20260410_rma_reason"
down_revision = "20260408_caja_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "rma_claims_ml",
        "reason_category",
        existing_type=sa.String(10),
        type_=sa.String(100),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "rma_claims_ml",
        "reason_category",
        existing_type=sa.String(100),
        type_=sa.String(10),
        existing_nullable=True,
    )
