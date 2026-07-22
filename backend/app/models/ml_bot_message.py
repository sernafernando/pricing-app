"""
ORM model for `ml_bot_messages` — MercadoLibre postventa messages MVP
(read-only ingestion, sdd/ml-bot-postventa-messages-mvp).

Sibling of `ml_bot_questions` (see app/models/ml_bot_question.py): a single
persisted row per unique `ml_message_id`, populated by
`app/services/ml_messages/ingestion_service.py`. This MVP is read-only — no
lifecycle/state machine on this table yet, only `created`/`read` webhook
actions apply.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class MlBotMessage(Base):
    """A single MercadoLibre postventa (post-sale) message ingested from the
    `messages` webhook topic.

    Phase A (sdd/ml-bot-messages-reply, migration
    `20260722_ml_bot_messages_bot_columns`) adds the draft/classify state
    machine on top of the read-only MVP row shape below. `bot_status` is a
    NEW column, deliberately isolated from ML's own `status` (never collide
    the two) and non-NULL ONLY on the "anchor" row — the latest unanswered
    buyer message per `pack_id` (design "Draft unit = anchor"). Earlier
    messages in the same burst stay `bot_status IS NULL` forever; the
    aggregated conversation is reconstructed live from the pack thread, not
    by mutating every row in the burst.

    `bot_status` state machine:
        (NULL|pending) -> drafting -> {awaiting_human|blocked_claim|failed}
        drafting -> pending                      (bounded retry / stale reclaim)
        awaiting_human -> superseded              (a newer buyer message re-opens
                                                     aggregation for the pack)
        {awaiting_human|blocked_claim} -> taken_over -> {sent|failed}
        failed -> pending                         (manual retry)

    Phase A NEVER auto-sends: `sent` is reachable ONLY via a human take-over
    + explicit send action (itself gated off by default, `messages_send_enabled`).
    """

    __tablename__ = "ml_bot_messages"

    id = Column(BigInteger, primary_key=True)

    # Idempotency key from ML (UUIDv7 hex string). Uniqueness enforced by the
    # named constraint in __table_args__ (matches the migration).
    ml_message_id = Column(String(64), nullable=False)

    pack_id = Column(String(32), nullable=True)
    buyer_id = Column(BigInteger, nullable=True)
    buyer_nickname = Column(String(255), nullable=True)
    seller_id = Column(BigInteger, nullable=False)

    subject = Column(String(255), nullable=True)
    text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)

    # NULL = unknown/pass (design decision #3) — a moderated message always
    # has a non-NULL, non-'clean' status; absence of moderation data must
    # never be treated as "hide this row".
    moderation_status = Column(String(50), nullable=True)

    is_first_message = Column(Boolean, nullable=False, default=False, server_default="false")
    attachments = Column(JSON, nullable=True)

    received_at = Column(DateTime(timezone=True), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    kind = Column(String(16), nullable=False, default="postventa", server_default="postventa")

    # Forward-compat columns (design decision #4) — nullable, unused by this
    # read-only MVP slice.
    taken_over_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notes = Column(Text, nullable=True)

    ingested_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Phase A draft/classify columns (migration 20260722) ---
    bot_status = Column(String(24), nullable=True)
    drafted_answer = Column(Text, nullable=True)
    intent_category = Column(String(40), nullable=True)
    confidence = Column(Numeric(4, 3), nullable=True)
    answer_source = Column(String(10), nullable=True)
    llm_provider = Column(String(100), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    drafted_at = Column(DateTime(timezone=True), nullable=True)
    bot_updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("ml_message_id", name="uq_ml_bot_messages_ml_message_id"),
        Index("idx_ml_bot_messages_pack_id", "pack_id"),
        Index("idx_ml_bot_messages_buyer_id", "buyer_id"),
        Index("idx_ml_bot_messages_received_at", "received_at"),
        Index(
            "idx_ml_bot_messages_moderation_status",
            "moderation_status",
            postgresql_where="moderation_status IS NOT NULL AND moderation_status != 'clean'",
        ),
        Index(
            "idx_ml_bot_messages_bot_status",
            "bot_status",
            postgresql_where="bot_status IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<MlBotMessage(ml_message_id={self.ml_message_id!r}, status={self.status})>"
