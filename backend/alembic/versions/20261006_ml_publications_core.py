"""ml_publications_core: core tables of the ML publications store

Revision ID: 20261006_ml_publications_core
Revises: 20261006_ml_tiendas_oficiales
Create Date: 2026-10-06

New tables only (item state, variations, change log, business events, runtime
settings, refresh queue, intake cursors, scan state, job runs). Data comes only
from MercadoLibre: no column or foreign key points at any GBP/ERP table. New
objects need no `lock_timeout`: nothing else references them yet.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261006_ml_publications_core"
down_revision: Union[str, None] = "20261006_ml_tiendas_oficiales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Drop order: children first (events reference the change log).
TABLES = [
    "ml_pub_job_runs",
    "ml_pub_scan_state",
    "ml_pub_intake_cursors",
    "ml_pub_refresh_queue",
    "ml_pub_settings",
    "ml_item_events",
    "ml_change_log",
    "ml_item_variations",
    "ml_items",
]

STATEMENTS = [
    """
    CREATE TABLE ml_items (
        item_id text PRIMARY KEY,
        site_id text, seller_id bigint, title text, brand text, family_name text,
        family_id bigint, category_id text, domain_id text, user_product_id text,
        catalog_product_id text, catalog_listing boolean, official_store_id bigint,
        status text, sub_status text[], tags text[], listing_type_id text, buying_mode text,
        condition text, currency_id text, seller_custom_field text, seller_sku text,
        price numeric(16,2), base_price numeric(16,2), original_price numeric(16,2),
        available_quantity integer, sold_quantity integer, initial_quantity integer,
        permalink text, thumbnail text, health numeric(5,4), inventory_id text, parent_item_id text,
        shipping_mode text, logistic_type text, free_shipping boolean,
        start_time timestamptz, stop_time timestamptz, end_time timestamptz, expiration_time timestamptz,
        date_created timestamptz, ml_last_updated timestamptz,
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz,
        first_active_at timestamptz, last_scan_seen_at timestamptz, last_trigger_received_at timestamptz
    ) WITH (fillfactor = 85)
    """,
    "CREATE INDEX ix_ml_items_status ON ml_items (status)",
    "CREATE INDEX ix_ml_items_official_store_id ON ml_items (official_store_id)",
    "CREATE INDEX ix_ml_items_brand ON ml_items (brand)",
    "CREATE INDEX ix_ml_items_user_product_id ON ml_items (user_product_id)",
    "CREATE INDEX ix_ml_items_family_id ON ml_items (family_id)",
    "CREATE INDEX ix_ml_items_catalog_product_id ON ml_items (catalog_product_id)",
    "CREATE INDEX ix_ml_items_seller_custom_field ON ml_items (seller_custom_field)",
    "CREATE INDEX ix_ml_items_seller_sku ON ml_items (seller_sku)",
    "CREATE INDEX ix_ml_items_gone_at ON ml_items (gone_at) WHERE gone_at IS NOT NULL",
    """
    CREATE TABLE ml_item_variations (
        item_id text NOT NULL, variation_id bigint NOT NULL,
        seller_custom_field text, seller_sku text, user_product_id text,
        available_quantity integer, sold_quantity integer,
        raw jsonb NOT NULL, raw_hash bytea NOT NULL,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz NOT NULL, gone_at timestamptz,
        PRIMARY KEY (item_id, variation_id)
    ) WITH (fillfactor = 85)
    """,
    """
    CREATE TABLE ml_change_log (
        id bigserial PRIMARY KEY,
        resource_type text NOT NULL,
        entity_id text NOT NULL,
        item_id text,
        kind text NOT NULL DEFAULT 'change',
        observed_at timestamptz NOT NULL,
        source_last_updated timestamptz,
        prev_hash bytea, new_hash bytea,
        changed_paths text[] NOT NULL,
        changes jsonb NOT NULL,
        context jsonb NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX ix_ml_change_log_item ON ml_change_log (item_id, observed_at DESC, id DESC)",
    "CREATE INDEX ix_ml_change_log_entity ON ml_change_log (resource_type, entity_id, observed_at DESC)",
    "CREATE INDEX ix_ml_change_log_paths ON ml_change_log USING gin (changed_paths)",
    "CREATE INDEX ix_ml_change_log_observed_brin ON ml_change_log USING brin (observed_at)",
    """
    CREATE TABLE ml_item_events (
        id bigserial PRIMARY KEY,
        event_type text NOT NULL,
        item_id text NOT NULL,
        promotion_id text, promotion_type text, price_kind text,
        old_value jsonb, new_value jsonb, payload jsonb NOT NULL DEFAULT '{}',
        observed_at timestamptz NOT NULL, source_last_updated timestamptz,
        official_store_id bigint, brand text,
        change_log_id bigint NOT NULL REFERENCES ml_change_log(id),
        dedupe_key bytea NOT NULL,
        CONSTRAINT uq_ml_item_events_dedupe_key UNIQUE (dedupe_key)
    )
    """,
    "CREATE INDEX ix_ml_item_events_item ON ml_item_events (item_id, observed_at DESC, id DESC)",
    "CREATE INDEX ix_ml_item_events_type ON ml_item_events (event_type, observed_at DESC, id DESC)",
    "CREATE INDEX ix_ml_item_events_store ON ml_item_events (official_store_id, event_type, observed_at DESC)",
    "CREATE INDEX ix_ml_item_events_change_log ON ml_item_events (change_log_id)",
    """
    CREATE TABLE ml_pub_settings (
        key text PRIMARY KEY,
        value jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by text
    )
    """,
    """
    CREATE TABLE ml_pub_refresh_queue (
        kind text NOT NULL,
        entity_id text NOT NULL,
        resources text[] NOT NULL DEFAULT '{}',
        lane smallint NOT NULL,
        first_enqueued_at timestamptz NOT NULL DEFAULT now(),
        last_enqueued_at timestamptz NOT NULL DEFAULT now(),
        source_received_at timestamptz,
        not_before timestamptz NOT NULL DEFAULT now(),
        attempts integer NOT NULL DEFAULT 0,
        last_error text,
        parked_at timestamptz,
        claimed_at timestamptz,
        claimed_by text,
        claim_token uuid,
        version integer NOT NULL DEFAULT 1,
        PRIMARY KEY (kind, entity_id)
    )
    """,
    """
    CREATE INDEX ix_ml_pub_refresh_queue_ready ON ml_pub_refresh_queue (lane, not_before, first_enqueued_at)
    WHERE claimed_at IS NULL AND parked_at IS NULL
    """,
    "CREATE INDEX ix_ml_pub_refresh_queue_claimed ON ml_pub_refresh_queue (claimed_at) WHERE claimed_at IS NOT NULL",
    "CREATE INDEX ix_ml_pub_refresh_queue_parked ON ml_pub_refresh_queue (parked_at) WHERE parked_at IS NOT NULL",
    """
    CREATE TABLE ml_pub_intake_cursors (
        topic text PRIMARY KEY, cursor_received_at timestamptz, cursor_resource text,
        updated_at timestamptz, rows_read bigint, enqueued bigint,
        skipped_satisfied bigint, skipped_foreign_seller bigint, unparsed bigint
    )
    """,
    """
    CREATE TABLE ml_pub_scan_state (
        status text PRIMARY KEY, mode text, scroll_id text, scroll_started_at timestamptz,
        pages integer, enumerated integer, enqueued integer, restarts integer,
        unsupported boolean NOT NULL DEFAULT false,
        lap_started_at timestamptz, started_at timestamptz, completed_at timestamptz, last_error text
    )
    """,
    """
    CREATE TABLE ml_pub_job_runs (
        id bigserial PRIMARY KEY, job text NOT NULL, scope text,
        started_at timestamptz NOT NULL, finished_at timestamptz, outcome text,
        counts jsonb NOT NULL DEFAULT '{}', last_error text
    )
    """,
    "CREATE INDEX ix_ml_pub_job_runs_job ON ml_pub_job_runs (job, started_at DESC)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
