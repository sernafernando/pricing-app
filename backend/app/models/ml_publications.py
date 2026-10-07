"""ML publications store: item state, variations, change log, events and the
operational tables of the refresh pipeline.

Mirrors `alembic/versions/20261006_ml_publications_core.py` and, for the sub-resource
state tables at the end of the module, `20261006_ml_publications_subresources.py` and
`20261007_ml_publications_quality.py`. Data comes only from MercadoLibre: no column or foreign key
points at a GBP/ERP table.

`fillfactor = 85` on the state tables is set by the migration only
(SQLAlchemy has no table-level `postgresql_with`); Alembic autogenerate does not compare it.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base

_TS = DateTime(timezone=True)


class MlItem(Base):
    __tablename__ = "ml_items"
    __table_args__ = (
        Index("ix_ml_items_status", "status"),
        Index("ix_ml_items_official_store_id", "official_store_id"),
        Index("ix_ml_items_brand", "brand"),
        Index("ix_ml_items_user_product_id", "user_product_id"),
        Index("ix_ml_items_family_id", "family_id"),
        Index("ix_ml_items_catalog_product_id", "catalog_product_id"),
        Index("ix_ml_items_seller_custom_field", "seller_custom_field"),
        Index("ix_ml_items_seller_sku", "seller_sku"),
        Index("ix_ml_items_gone_at", "gone_at", postgresql_where=text("gone_at IS NOT NULL")),
    )

    item_id = Column(Text, primary_key=True)
    site_id = Column(Text)
    seller_id = Column(BigInteger)
    title = Column(Text)
    brand = Column(Text)
    family_name = Column(Text)
    family_id = Column(BigInteger)
    category_id = Column(Text)
    domain_id = Column(Text)
    user_product_id = Column(Text)
    catalog_product_id = Column(Text)
    catalog_listing = Column(Boolean)
    official_store_id = Column(BigInteger)
    status = Column(Text)
    sub_status = Column(ARRAY(Text))
    tags = Column(ARRAY(Text))
    listing_type_id = Column(Text)
    buying_mode = Column(Text)
    condition = Column(Text)
    currency_id = Column(Text)
    seller_custom_field = Column(Text)
    seller_sku = Column(Text)
    price = Column(Numeric(16, 2))
    base_price = Column(Numeric(16, 2))
    original_price = Column(Numeric(16, 2))
    available_quantity = Column(Integer)
    sold_quantity = Column(Integer)
    initial_quantity = Column(Integer)
    permalink = Column(Text)
    thumbnail = Column(Text)
    health = Column(Numeric(5, 4))
    inventory_id = Column(Text)
    parent_item_id = Column(Text)
    shipping_mode = Column(Text)
    logistic_type = Column(Text)
    free_shipping = Column(Boolean)
    start_time = Column(_TS)
    stop_time = Column(_TS)
    end_time = Column(_TS)
    expiration_time = Column(_TS)
    date_created = Column(_TS)
    ml_last_updated = Column(_TS)
    raw = Column(JSONB)
    raw_hash = Column(LargeBinary)
    http_status = Column(SmallInteger)
    error_body = Column(JSONB)
    last_error = Column(Text)
    first_seen_at = Column(_TS, nullable=False, server_default=func.now())
    fetched_at = Column(_TS)
    fetched_request_started_at = Column(_TS)
    never_existed = Column(Boolean, nullable=False, server_default=text("false"))
    last_checked_at = Column(_TS)
    gone_at = Column(_TS)
    first_active_at = Column(_TS)
    last_scan_seen_at = Column(_TS)
    last_trigger_received_at = Column(_TS)


class MlItemVariation(Base):
    __tablename__ = "ml_item_variations"

    item_id = Column(Text, primary_key=True)
    variation_id = Column(BigInteger, primary_key=True, autoincrement=False)
    seller_custom_field = Column(Text)
    seller_sku = Column(Text)
    user_product_id = Column(Text)
    available_quantity = Column(Integer)
    sold_quantity = Column(Integer)
    raw = Column(JSONB, nullable=False)
    raw_hash = Column(LargeBinary, nullable=False)
    first_seen_at = Column(_TS, nullable=False, server_default=func.now())
    fetched_at = Column(_TS, nullable=False)
    gone_at = Column(_TS)


class MlChangeLog(Base):
    __tablename__ = "ml_change_log"
    __table_args__ = (
        Index("ix_ml_change_log_item", "item_id", text("observed_at DESC"), text("id DESC")),
        Index("ix_ml_change_log_entity", "resource_type", "entity_id", text("observed_at DESC")),
        Index("ix_ml_change_log_paths", "changed_paths", postgresql_using="gin"),
        Index("ix_ml_change_log_observed_brin", "observed_at", postgresql_using="brin"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    resource_type = Column(Text, nullable=False)
    entity_id = Column(Text, nullable=False)
    item_id = Column(Text)
    kind = Column(Text, nullable=False, server_default="change")
    observed_at = Column(_TS, nullable=False)
    source_last_updated = Column(_TS)
    prev_hash = Column(LargeBinary)
    new_hash = Column(LargeBinary)
    changed_paths = Column(ARRAY(Text), nullable=False)
    changes = Column(JSONB, nullable=False)
    context = Column(JSONB, nullable=False, server_default=text("'{}'"))


class MlItemEvent(Base):
    __tablename__ = "ml_item_events"
    __table_args__ = (
        Index("ix_ml_item_events_item", "item_id", text("observed_at DESC"), text("id DESC")),
        Index("ix_ml_item_events_type", "event_type", text("observed_at DESC"), text("id DESC")),
        Index("ix_ml_item_events_store", "official_store_id", "event_type", text("observed_at DESC")),
        Index("ix_ml_item_events_change_log", "change_log_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(Text, nullable=False)
    item_id = Column(Text, nullable=False)
    promotion_id = Column(Text)
    promotion_type = Column(Text)
    price_kind = Column(Text)
    old_value = Column(JSONB)
    new_value = Column(JSONB)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'"))
    observed_at = Column(_TS, nullable=False)
    source_last_updated = Column(_TS)
    official_store_id = Column(BigInteger)
    brand = Column(Text)
    change_log_id = Column(BigInteger, ForeignKey("ml_change_log.id"), nullable=False)
    dedupe_key = Column(LargeBinary, nullable=False, unique=True)


class MlPubSetting(Base):
    __tablename__ = "ml_pub_settings"

    key = Column(Text, primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(_TS, nullable=False, server_default=func.now())
    updated_by = Column(Text)


class MlPubRefreshQueue(Base):
    __tablename__ = "ml_pub_refresh_queue"
    __table_args__ = (
        Index(
            "ix_ml_pub_refresh_queue_ready",
            "lane",
            "not_before",
            "first_enqueued_at",
            postgresql_where=text("claimed_at IS NULL AND parked_at IS NULL"),
        ),
        Index("ix_ml_pub_refresh_queue_claimed", "claimed_at", postgresql_where=text("claimed_at IS NOT NULL")),
        Index("ix_ml_pub_refresh_queue_parked", "parked_at", postgresql_where=text("parked_at IS NOT NULL")),
    )

    kind = Column(Text, primary_key=True)
    entity_id = Column(Text, primary_key=True)
    resources = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    lane = Column(SmallInteger, nullable=False)
    first_enqueued_at = Column(_TS, nullable=False, server_default=func.now())
    last_enqueued_at = Column(_TS, nullable=False, server_default=func.now())
    source_received_at = Column(_TS)
    not_before = Column(_TS, nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default="0")
    last_error = Column(Text)
    parked_at = Column(_TS)
    claimed_at = Column(_TS)
    claimed_by = Column(Text)
    claim_token = Column(UUID(as_uuid=False))
    version = Column(Integer, nullable=False, server_default="1")


class MlPubIntakeCursor(Base):
    __tablename__ = "ml_pub_intake_cursors"

    topic = Column(Text, primary_key=True)
    cursor_received_at = Column(_TS)
    cursor_resource = Column(Text)
    updated_at = Column(_TS)
    rows_read = Column(BigInteger)
    enqueued = Column(BigInteger)
    skipped_satisfied = Column(BigInteger)
    skipped_foreign_seller = Column(BigInteger)
    unparsed = Column(BigInteger)


class MlPubScanState(Base):
    __tablename__ = "ml_pub_scan_state"

    status = Column(Text, primary_key=True)
    mode = Column(Text)
    scroll_id = Column(Text)
    scroll_started_at = Column(_TS)
    pages = Column(Integer)
    enumerated = Column(Integer)
    enqueued = Column(Integer)
    restarts = Column(Integer)
    unsupported = Column(Boolean, nullable=False, server_default=text("false"))
    lap_started_at = Column(_TS)
    started_at = Column(_TS)
    completed_at = Column(_TS)
    last_error = Column(Text)


class MlPubJobRun(Base):
    __tablename__ = "ml_pub_job_runs"
    __table_args__ = (Index("ix_ml_pub_job_runs_job", "job", text("started_at DESC")),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job = Column(Text, nullable=False)
    scope = Column(Text)
    started_at = Column(_TS, nullable=False)
    finished_at = Column(_TS)
    outcome = Column(Text)
    counts = Column(JSONB, nullable=False, server_default=text("'{}'"))
    last_error = Column(Text)


# --- Sub-resource state tables (migration 20261006_ml_publications_subresources) -----------------
# Same metadata columns as `ml_items`; typed columns fixed from the 2026-10-06 captures.


class _SubResourceState:
    """Shared metadata columns of a sub-resource state row (a mixin: it has no table)."""

    raw = Column(JSONB)
    raw_hash = Column(LargeBinary)
    http_status = Column(SmallInteger)
    error_body = Column(JSONB)
    last_error = Column(Text)
    first_seen_at = Column(_TS, nullable=False, server_default=func.now())
    fetched_at = Column(_TS)
    fetched_request_started_at = Column(_TS)
    never_existed = Column(Boolean, nullable=False, server_default=text("false"))
    last_checked_at = Column(_TS)
    gone_at = Column(_TS)


class MlItemDescription(_SubResourceState, Base):
    __tablename__ = "ml_item_descriptions"

    item_id = Column(Text, primary_key=True)
    plain_text_length = Column(Integer)
    ml_last_updated = Column(_TS)


class MlItemPrices(_SubResourceState, Base):
    __tablename__ = "ml_item_prices"

    item_id = Column(Text, primary_key=True)
    standard_amount = Column(Numeric(16, 2))
    currency_id = Column(Text)
    active_promotion_amount = Column(Numeric(16, 2))


class MlItemSalePrice(_SubResourceState, Base):
    __tablename__ = "ml_item_sale_prices"

    item_id = Column(Text, primary_key=True)
    price_id = Column(Text)
    amount = Column(Numeric(16, 2))
    regular_amount = Column(Numeric(16, 2))
    currency_id = Column(Text)
    campaign_id = Column(Text)
    promotion_id = Column(Text)
    promotion_type = Column(Text)


class MlItemSellerPromotions(_SubResourceState, Base):
    __tablename__ = "ml_item_seller_promotions"

    item_id = Column(Text, primary_key=True)
    candidate_count = Column(Integer)
    started_count = Column(Integer)
    started_promotion_keys = Column(ARRAY(Text))


class MlUserProduct(_SubResourceState, Base):
    __tablename__ = "ml_user_products"

    user_product_id = Column(Text, primary_key=True)
    family_id = Column(BigInteger)
    name = Column(Text)
    domain_id = Column(Text)
    catalog_product_id = Column(Text)
    ml_last_updated = Column(_TS)


class MlUserProductStock(_SubResourceState, Base):
    __tablename__ = "ml_user_product_stock"

    user_product_id = Column(Text, primary_key=True)
    total_quantity = Column(Integer)
    ml_last_updated = Column(_TS)


class MlUserProductFamily(_SubResourceState, Base):
    __tablename__ = "ml_user_product_families"

    family_id = Column(BigInteger, primary_key=True, autoincrement=False)
    user_products_ids = Column(ARRAY(Text))


# --- Quality sub-resources (migration 20261007_ml_publications_quality) --------------------------------


class MlItemCompetition(_SubResourceState, Base):
    __tablename__ = "ml_item_competition"

    item_id = Column(Text, primary_key=True)
    status = Column(Text)
    price_to_win = Column(Numeric(16, 2))
    current_price = Column(Numeric(16, 2))
    currency_id = Column(Text)
    consistent = Column(Boolean)


class MlItemPerformance(_SubResourceState, Base):
    __tablename__ = "ml_item_performance"

    item_id = Column(Text, primary_key=True)
    applicable = Column(Boolean)
    entity_type = Column(Text)
    entity_id = Column(Text)
    score = Column(Numeric(5, 2))
    level = Column(Text)
    calculated_at = Column(_TS)


class MlItemModeration(_SubResourceState, Base):
    __tablename__ = "ml_item_moderations"

    item_id = Column(Text, primary_key=True)
    has_moderation = Column(Boolean)


class MlItemVisits(_SubResourceState, Base):
    __tablename__ = "ml_item_visits"

    item_id = Column(Text, primary_key=True)
    window_days = Column(Integer)
    total_visits = Column(Integer)
    date_from = Column(_TS)
    date_to = Column(_TS)


# --- Product links (migration 20261006_ml_publications_product_links, design D20) -------------------


class MlItemProductLink(Base):
    """Current link of a publication unit `(item_id, variation_id)` to one of our products.

    `variation_id = 0` is the item-level unit. `producto_item_id` is `productos_erp.item_id` with NO
    foreign key (the ERP sync rewrites that table); a vanished product is reported as dangling.
    """

    __tablename__ = "ml_item_product_links"
    __table_args__ = (
        Index("ix_ml_item_product_links_status_source", "match_status", "source"),
        Index("ix_ml_item_product_links_producto", "producto_item_id"),
        Index(
            "ix_ml_item_product_links_manual_differs",
            "item_id",
            "variation_id",
            postgresql_where=text(
                "source <> 'sku_auto' AND suggestion_status = 'linked' "
                "AND suggested_producto_item_id IS DISTINCT FROM producto_item_id"
            ),
        ),
    )

    item_id = Column(Text, primary_key=True)
    variation_id = Column(BigInteger, primary_key=True, autoincrement=False, server_default=text("0"))
    source = Column(Text, nullable=False)
    match_status = Column(Text, nullable=False)
    producto_item_id = Column(Integer)
    matched_sku = Column(Text)
    sku_field = Column(Text)
    candidate_ids = Column(ARRAY(Integer))
    suggested_producto_item_id = Column(Integer)
    suggestion_status = Column(Text)
    suggestion_candidates = Column(SmallInteger)
    evaluated_sku_key = Column(Text)
    evaluated_at = Column(_TS)
    linked_by = Column(Integer)
    linked_at = Column(_TS, nullable=False)
    note = Column(Text)
    first_seen_at = Column(_TS, nullable=False, server_default=func.now())
    updated_at = Column(_TS, nullable=False, server_default=func.now())
