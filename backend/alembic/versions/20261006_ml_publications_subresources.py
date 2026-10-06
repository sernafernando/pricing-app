"""ml_publications_subresources: per-item and per-user-product sub-resource state tables

Revision ID: 20261006_ml_publications_subresources
Revises: 20261006_ml_publications_core
Create Date: 2026-10-06

New tables only: item description, prices, sale price and seller promotions, plus user
product, user product stock and user product family. Each table has the metadata columns
of `ml_items` (raw, raw_hash, http_status, error_body, last_error, first_seen_at,
fetched_at, fetched_request_started_at, never_existed, last_checked_at, gone_at) and the
few typed columns fixed from the 2026-10-06 captures. Data comes only from MercadoLibre:
no column or foreign key points at any GBP/ERP table. New objects need no `lock_timeout`.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261006_ml_publications_subresources"
down_revision: Union[str, None] = "20261006_ml_publications_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "ml_item_descriptions",
    "ml_item_prices",
    "ml_item_sale_prices",
    "ml_item_seller_promotions",
    "ml_user_products",
    "ml_user_product_stock",
    "ml_user_product_families",
]

STATEMENTS = [
    """
    CREATE TABLE ml_item_descriptions (
        item_id text PRIMARY KEY,
        plain_text_length integer, ml_last_updated timestamptz,
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_item_prices (
        item_id text PRIMARY KEY,
        standard_amount numeric(16,2), currency_id text,
        active_promotion_amount numeric(16,2),
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_item_sale_prices (
        item_id text PRIMARY KEY,
        price_id text, amount numeric(16,2), regular_amount numeric(16,2), currency_id text,
        campaign_id text, promotion_id text, promotion_type text,
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_item_seller_promotions (
        item_id text PRIMARY KEY,
        candidate_count integer, started_count integer, started_promotion_keys text[],
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_user_products (
        user_product_id text PRIMARY KEY,
        family_id bigint, name text, domain_id text, catalog_product_id text,
        ml_last_updated timestamptz,
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_user_product_stock (
        user_product_id text PRIMARY KEY,
        total_quantity integer, ml_last_updated timestamptz,
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_user_product_families (
        family_id bigint PRIMARY KEY,
        user_products_ids text[],
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
    ) WITH (fillfactor = 85)
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
