"""ml_user_product_replenishment: Full replenishment state per user product

Revision ID: 20261011_ml_user_product_replenishment
Revises: 20261010_ml_user_product_stock_locations
Create Date: 2026-10-11

New table only (no existing object is altered, so no `lock_timeout`): the state of
`GET /marketplace/fbm/user-products/{MLAU}/replenishment?country=AR`, keyed by user product id.
It has the metadata columns of the other sub-resource state tables (raw, raw_hash, http_status,
error_body, last_error, first_seen_at, fetched_at, fetched_request_started_at, never_existed,
last_checked_at, gone_at) and the typed columns fixed from the 2026-10-08 capture: sales windows
(7/14/21/30 days), GMV, days out of stock, and the Full stock / shipping urgency block.

The refresh handler writes it (fetcher, sweep and registration: `replenishment` in `bundle_resources`, off by default).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261011_ml_user_product_replenishment"
down_revision: Union[str, None] = "20261010_ml_user_product_stock_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ml_user_product_replenishment"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_TABLE} (
            user_product_id text PRIMARY KEY,
            partial boolean, content_missing text,
            period text, units_30d integer, gmv_30d numeric(16,2), currency_id text,
            units_7d integer, units_14d integer, units_21d integer,
            days_out_of_stock_21d integer, history_through date,
            total_stock integer, shipping_urgency text, minimum_distributable_stock integer,
            raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
            first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
            fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
            last_checked_at timestamptz, gone_at timestamptz
        ) WITH (fillfactor = 85)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
