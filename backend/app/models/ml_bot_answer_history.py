"""
ORM model for `ml_bot_answer_history` — the growing corpus of published bot
answers, embedded for similarity-based few-shot retrieval
(sdd/ml-bot-dynamic-fewshot, design "ml_bot_answer_history model + migration").

Separate trust class from `ml_bot_answer_examples` (the static, curated
tone-grounding seed): rows here are captured automatically at publish success
(PR2) and retrieved by cosine similarity (PR3). `embedding` is a 384-dim
`pgvector` vector of the "passage: "-prefixed `answer_text`
(`intfloat/multilingual-e5-small`), always populated (NOT NULL) — a failed
embed simply skips capture rather than inserting a dead row (design "Decision:
Capture side-effect placement").
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.core.database import Base

# Embedding dimensionality of `intfloat/multilingual-e5-small` (design ADR-2 /
# "Interfaces / Contracts"). Any change to the embedding model requires a new
# migration + backfill; this constant and the migration's column width must
# always match.
EMBEDDING_DIM = 384


class MlBotAnswerHistory(Base):
    """A single captured published answer with its similarity embedding."""

    __tablename__ = "ml_bot_answer_history"

    id = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    item_id = Column(String(32), nullable=False, index=True)
    edited_flag = Column(Boolean, nullable=False, default=False, server_default="false")
    category = Column(String(40), nullable=True)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<MlBotAnswerHistory(id={self.id}, item_id={self.item_id}, active={self.active})>"
