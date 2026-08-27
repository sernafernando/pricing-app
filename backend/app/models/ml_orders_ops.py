"""ML operations source-of-truth schema (slice 1 of ml-ventas-fuente-de-verdad).

Additive tables sourced directly from the ML API (via the ml-webhook proxy),
independent of GBP. Nothing writes to these tables yet — no ingestion
service, no sweep, no reader — that is intentional for this slice, exactly
like the tn_image_normalizer precedent.

Design decisions (see design doc, obs #1823):
- Natural key is the ML `order_id`, never the ERP `mlo_id`.
- `ml_order_items_ops` carries ZERO cost columns; a later change joins ERP
  cost onto `(seller_sku, item_id)` from a separate table/view.
- `ml_ops_divergence` is reused by slice 3/6 for the out-of-window update
  counter via `kind='out_of_window_update'` — no dedicated counter table
  (cross-slice contract, obs #1828).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class MlOrdersOps(Base):
    """One row per ML order. Writer of record: ML ingestion service."""

    __tablename__ = "ml_orders_ops"
    __table_args__ = (
        Index("ix_ml_orders_ops_seller_id_ml_last_updated", "seller_id", "ml_last_updated"),
        Index("ix_ml_orders_ops_status_date_created", "status", "date_created"),
    )

    order_id = Column(BigInteger, primary_key=True)

    pack_id = Column(BigInteger, nullable=True, index=True)
    status = Column(String(30), nullable=True, index=True)
    status_detail = Column(String(60), nullable=True)

    date_created = Column(DateTime(timezone=True), nullable=True)
    date_closed = Column(DateTime(timezone=True), nullable=True)
    ml_last_updated = Column(DateTime(timezone=True), nullable=False, index=True)

    buyer_id = Column(BigInteger, nullable=True, index=True)
    buyer_nickname = Column(String(120), nullable=True)

    seller_id = Column(BigInteger, nullable=False, index=True)

    total_amount = Column(Numeric(14, 2), nullable=True)
    paid_amount = Column(Numeric(14, 2), nullable=True)
    currency_id = Column(String(5), nullable=True)

    shipping_id = Column(BigInteger, nullable=True, index=True)

    tags = Column(JSONB, nullable=True)
    raw_order = Column(JSONB, nullable=True)

    ingest_error = Column(Text, nullable=True)

    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MlOrderItemOps(Base):
    """One row per (order, item, variation). Writer of record: ML ingestion service.

    ZERO cost columns — this is the cost seam. A later change joins ERP cost
    onto `(seller_sku, item_id)` from a separate table/view; ingestion never
    reads ERP.
    """

    __tablename__ = "ml_order_items_ops"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "item_id",
            "variation_id",
            name="uq_ml_order_item_ops_order_item_variation",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    item_id = Column(String(20), nullable=False, index=True)
    variation_id = Column(BigInteger, nullable=True)

    seller_sku = Column(String(60), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=True)
    unit_price = Column(Numeric(14, 2), nullable=True)
    full_unit_price = Column(Numeric(14, 2), nullable=True)
    sale_fee = Column(Numeric(14, 2), nullable=True)
    listing_type_id = Column(String(30), nullable=True)

    raw_item = Column(JSONB, nullable=True)


class MlShipmentOps(Base):
    """One row per ML shipment. Writer of record: ML ingestion service."""

    __tablename__ = "ml_shipments_ops"

    shipment_id = Column(BigInteger, primary_key=True)

    order_id = Column(BigInteger, nullable=True, index=True)
    status = Column(String(30), nullable=True, index=True)
    substatus = Column(String(40), nullable=True)
    logistic_type = Column(String(30), nullable=True)
    tracking_number = Column(String(60), nullable=True, index=True)
    tracking_method = Column(String(40), nullable=True)

    date_created = Column(DateTime(timezone=True), nullable=True)
    last_updated = Column(DateTime(timezone=True), nullable=True)

    receiver_address = Column(JSONB, nullable=True)
    raw_shipment = Column(JSONB, nullable=True)

    last_synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MlOperationLink(Base):
    """Link from a claim/question/message to its ML order.

    Writer of record: link resolver service. Existing ingestion tables
    (rma_claims_ml, ml_bot_question, ml_bot_message) are read-only inputs —
    never written by this resolver.
    """

    __tablename__ = "ml_operation_links"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "order_id", name="uq_ml_operation_links_entity_order"),
        Index("ix_ml_operation_links_order_id_entity_type", "order_id", "entity_type"),
    )

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    entity_type = Column(String(20), nullable=False)  # claim | question | message
    entity_id = Column(BigInteger, nullable=False)

    link_source = Column(String(20), nullable=False)  # claim_resource_id | pack_id | item_id | manual
    link_confidence = Column(String(10), nullable=False)  # exact | inferred

    resolved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MlOpsSyncCursor(Base):
    """Checkpoint for the ingestion sweep and backfill jobs.

    Writer of record: ingestion sweep + backfill. Backfill checkpoints here
    under `name='backfill'` so a killed run resumes at the last fully
    completed window.
    """

    __tablename__ = "ml_ops_sync_cursor"

    name = Column(String(50), primary_key=True)  # 'sweep' | 'backfill'

    window_from = Column(DateTime(timezone=True), nullable=True)
    window_to = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)

    state = Column(String(20), nullable=False, server_default="idle")  # idle | running | error
    detail = Column(Text, nullable=True)


class MlOpsDivergence(Base):
    """One row per open divergence between ML-sourced and GBP-sourced data.

    Writer of record: divergence job (detection) + dashboard endpoint
    (state/note/assignee only — never the ML data itself).

    Also reused (cross-slice contract, obs #1828) by the sweep's
    out-of-window update counter via `kind='out_of_window_update'` — no
    dedicated counter table.
    """

    __tablename__ = "ml_ops_divergence"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "kind",
            "field",
            name="uq_ml_ops_divergence_order_kind_field",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    kind = Column(String(30), nullable=False)  # missing_in_gbp | missing_in_ml | field_mismatch | out_of_window_update
    field = Column(String(40), nullable=True)
    ml_value = Column(Text, nullable=True)
    gbp_value = Column(Text, nullable=True)

    state = Column(String(20), nullable=False, server_default="open")  # open | acknowledged | resolved | ignored
    assigned_to_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    note = Column(Text, nullable=True)

    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
