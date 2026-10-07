"""ml_publications_quality: competition, performance, moderation and visits state tables

Revision ID: 20261007_ml_publications_quality
Revises: 20261007_ml_publicaciones_vincular_perm
Create Date: 2026-10-07

New tables only: the catalog competition (`price_to_win`), item performance, last moderation and
visits time-window state of an item. Each table has the metadata columns of `ml_items` (raw,
raw_hash, http_status, error_body, last_error, first_seen_at, fetched_at, fetched_request_started_at,
never_existed, last_checked_at, gone_at) and the few typed columns fixed from the 2026-10-06
captures. Data comes only from MercadoLibre: no column or foreign key points at any GBP/ERP table.
New objects need no `lock_timeout`.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261007_ml_publications_quality"
down_revision: Union[str, None] = "20261007_ml_publicaciones_vincular_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "ml_item_competition",
    "ml_item_performance",
    "ml_item_moderations",
    "ml_item_visits",
]

_METADATA = """
        raw jsonb, raw_hash bytea, http_status smallint, error_body jsonb, last_error text,
        first_seen_at timestamptz NOT NULL DEFAULT now(), fetched_at timestamptz,
        fetched_request_started_at timestamptz, never_existed boolean NOT NULL DEFAULT false,
        last_checked_at timestamptz, gone_at timestamptz
"""

STATEMENTS = [
    f"""
    CREATE TABLE ml_item_competition (
        item_id text PRIMARY KEY,
        status text, price_to_win numeric(16,2), current_price numeric(16,2), currency_id text,
        consistent boolean,
        {_METADATA}
    ) WITH (fillfactor = 85)
    """,
    f"""
    CREATE TABLE ml_item_performance (
        item_id text PRIMARY KEY,
        applicable boolean, entity_type text, entity_id text, score numeric(5,2), level text,
        calculated_at timestamptz,
        {_METADATA}
    ) WITH (fillfactor = 85)
    """,
    f"""
    CREATE TABLE ml_item_moderations (
        item_id text PRIMARY KEY,
        has_moderation boolean,
        {_METADATA}
    ) WITH (fillfactor = 85)
    """,
    f"""
    CREATE TABLE ml_item_visits (
        item_id text PRIMARY KEY,
        window_days integer, total_visits integer, date_from timestamptz, date_to timestamptz,
        {_METADATA}
    ) WITH (fillfactor = 85)
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
