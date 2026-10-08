"""ml-billing-balance PR 2b: billing documents + document/legal columns on charges

Revision ID: 20261011_ml_billing_documents
Revises: 20261010_ml_user_product_stock_locations
Create Date: 2026-10-11

- `ml_billing_documents`: one row per ML document (invoice or credit note) with
  ML's own values only. No cached aggregates: completeness is a query.
- `ml_billing_charges` gains `document_type` (existing rows are all general BILL
  rows, backfilled 'BILL'), `billing_source` (server default 'general'),
  `legal_document_number`, `legal_document_status` and two lookup indexes.

Downgrade drops the table and the added columns/indexes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261011_ml_billing_documents"
down_revision: Union[str, None] = "20261010_ml_user_product_stock_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHARGES = "ml_billing_charges"


def upgrade() -> None:
    op.create_table(
        "ml_billing_documents",
        sa.Column("document_id", sa.String(60), primary_key=True),
        sa.Column("group", sa.String(5), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("period_key", sa.String(10), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("unpaid_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("document_status", sa.String(30), nullable=True),
        sa.Column("associated_document_id", sa.String(60), nullable=True),
        sa.Column("count_details", sa.Integer(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("currency_id", sa.String(5), nullable=True),
        sa.Column("site_id", sa.String(5), nullable=True),
        sa.Column("reference_number", sa.String(20), nullable=True),
        sa.Column("legal_point_of_sale", sa.Integer(), nullable=True),
        sa.Column("legal_letter", sa.String(1), nullable=True),
        sa.Column("legal_number", sa.Integer(), nullable=True),
        sa.Column("files", postgresql.JSONB(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ml_billing_documents_period_key", "ml_billing_documents", ["period_key"])

    op.add_column(_CHARGES, sa.Column("document_type", sa.String(20), nullable=True))
    op.add_column(
        _CHARGES,
        sa.Column("billing_source", sa.String(10), nullable=False, server_default=sa.text("'general'")),
    )
    op.add_column(_CHARGES, sa.Column("legal_document_number", sa.String(30), nullable=True))
    op.add_column(_CHARGES, sa.Column("legal_document_status", sa.String(30), nullable=True))
    # Everything swept before this migration came from the general BILL fetch.
    op.execute(f"UPDATE {_CHARGES} SET document_type = 'BILL' WHERE document_type IS NULL")
    op.create_index("ix_ml_billing_charges_period_document_type", _CHARGES, ["period_key", "document_type"])
    op.create_index("ix_ml_billing_charges_document_id", _CHARGES, ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_billing_charges_document_id", table_name=_CHARGES)
    op.drop_index("ix_ml_billing_charges_period_document_type", table_name=_CHARGES)
    op.drop_column(_CHARGES, "legal_document_status")
    op.drop_column(_CHARGES, "legal_document_number")
    op.drop_column(_CHARGES, "billing_source")
    op.drop_column(_CHARGES, "document_type")
    op.drop_index("ix_ml_billing_documents_period_key", table_name="ml_billing_documents")
    op.drop_table("ml_billing_documents")
