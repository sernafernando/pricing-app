"""ml_publications_product_links: link table between ML publications and our products

Revision ID: 20261006_ml_publications_product_links
Revises: 20261006_ml_publications_subresources
Create Date: 2026-10-06

New table only (design D20). One current link per link unit `(item_id, variation_id)`;
`variation_id = 0` is the item-level unit. `producto_item_id` holds `productos_erp.item_id`
WITHOUT a foreign key: the ERP sync rewrites that table and a link whose product vanished is
reported as dangling instead. Publication state tables get no product column. New objects need
no `lock_timeout`.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261006_ml_publications_product_links"
down_revision: Union[str, None] = "20261006_ml_publications_subresources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_item_product_links"

STATEMENTS = [
    f"""
    CREATE TABLE {TABLE} (
        item_id text NOT NULL,
        variation_id bigint NOT NULL DEFAULT 0 CHECK (variation_id >= 0),
        source text NOT NULL CHECK (source IN ('sku_auto', 'manual', 'manual_none')),
        match_status text NOT NULL CHECK (match_status IN ('linked', 'unmatched', 'conflict', 'no_product')),
        producto_item_id integer,
        matched_sku text,
        sku_field text,
        candidate_ids integer[],
        suggested_producto_item_id integer,
        suggestion_status text,
        suggestion_candidates smallint,
        evaluated_sku_key text,
        evaluated_at timestamptz,
        linked_by integer,
        linked_at timestamptz NOT NULL,
        note text,
        first_seen_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (item_id, variation_id),
        CHECK ((match_status = 'linked') = (producto_item_id IS NOT NULL)),
        CHECK (source <> 'manual_none' OR match_status = 'no_product')
    ) WITH (fillfactor = 85)
    """,
    f"CREATE INDEX ix_{TABLE}_status_source ON {TABLE} (match_status, source)",
    f"CREATE INDEX ix_{TABLE}_producto ON {TABLE} (producto_item_id)",
    f"""
    CREATE INDEX ix_{TABLE}_manual_differs ON {TABLE} (item_id, variation_id)
    WHERE source <> 'sku_auto' AND suggestion_status = 'linked'
      AND suggested_producto_item_id IS DISTINCT FROM producto_item_id
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
