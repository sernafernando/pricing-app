"""
ORM model for `ml_bot_questions` — the MercadoLibre pre-sale question bot.

Lifecycle (design §2):
    received -> drafting -> {waiting | pending_morning | failed}
    waiting -> {published | taken_over | failed}
    taken_over -> {published | pending_morning}
    pending_morning -> {published | taken_over}
    failed -> {waiting | published}  (manual retry)

Every transition is a single short `get_background_db()` UPDATE with an
explicit WHERE on the current state (CAS-safe, idempotent).
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.sql import func

from app.core.database import Base


class MlBotQuestion(Base):
    """A single MercadoLibre buyer question tracked through the bot's lifecycle."""

    __tablename__ = "ml_bot_questions"

    id = Column(BigInteger, primary_key=True)

    # Idempotency key from ML (design §3/§4, R-101). Uniqueness enforced by
    # the named constraint in __table_args__ (matches the migration).
    ml_question_id = Column(BigInteger, nullable=False)

    item_id = Column(String(32), nullable=False)
    buyer_id = Column(BigInteger, nullable=True)
    buyer_nickname = Column(String(255), nullable=True)

    # Item enrichment (panel-v2 requirement #2) — populated best-effort by
    # ingestion via `ml_client.get_item()`; NULL when enrichment failed or
    # for rows ingested before this column existed. Never blocks ingestion.
    item_title = Column(String(200), nullable=True)
    item_permalink = Column(String(500), nullable=True)

    question_text = Column(Text, nullable=False)
    question_date = Column(DateTime(timezone=True), nullable=False)

    status = Column(String(20), nullable=False, default="received", server_default="received")

    drafted_answer = Column(Text, nullable=True)
    answer_source = Column(String(10), nullable=True)  # bot | human | fallback
    confidence = Column(Numeric(4, 3), nullable=True)
    category = Column(String(40), nullable=True)

    # PR de pulido item #2: "provider/model" that produced this draft (e.g.
    # "groq/llama-3.3-70b-versatile"). Nullable — NULL for rows drafted
    # before this column existed, human-authored answers, or fallback-only
    # rows that never called an LLM.
    llm_provider = Column(String(100), nullable=True)

    injection_flag = Column(Boolean, nullable=False, default=False, server_default="false")
    fallback_used = Column(Boolean, nullable=False, default=False, server_default="false")

    wait_until = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)

    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)

    taken_over_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("ml_question_id", name="uq_ml_bot_questions_ml_question_id"),
        Index("idx_ml_bot_questions_status", "status"),
        Index("idx_ml_bot_questions_item_id", "item_id"),
        Index("idx_ml_bot_questions_question_date", "question_date"),
        # Backs GET /questions/{id}/buyer-history (panel-v2 requirement #3),
        # which filters by buyer_id.
        Index("idx_ml_bot_questions_buyer_id", "buyer_id"),
        Index(
            "idx_ml_bot_questions_wait_until_waiting",
            "wait_until",
            postgresql_where="status = 'waiting'",
        ),
        Index("idx_ml_bot_questions_taken_over_by", "taken_over_by"),
    )

    def __repr__(self) -> str:
        return f"<MlBotQuestion(ml_question_id={self.ml_question_id}, status={self.status})>"
