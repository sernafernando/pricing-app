"""ML publications store: item state, variations, change log, events and the
operational tables of the refresh pipeline.

Mirrors `alembic/versions/20261006_ml_publications_core.py`. Data comes only
from MercadoLibre: no column or foreign key points at a GBP/ERP table.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
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

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job = Column(Text, nullable=False)
    scope = Column(Text)
    started_at = Column(_TS, nullable=False)
    finished_at = Column(_TS)
    outcome = Column(Text)
    counts = Column(JSONB, nullable=False, server_default=text("'{}'"))
    last_error = Column(Text)
