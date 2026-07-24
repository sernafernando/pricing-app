"""
ORM model for `tn_category_embedding` — a build-once, re-runnable mirror of
the TN category tree with a per-category embedding, used to preselect a
likely TN category for a product being published (sdd/tn-reconcile-publish,
sub-slice 3b, design "Category" decision + Data Flow's "category_service").

Trust class mirrors `MlBotAnswerHistory`: `embedding` is a 384-dim `pgvector`
vector of the `category_path_text` ("Parent > Child" readable path), embedded
with the "passage: " e5 prefix via `embed_passages`
(`intfloat/multilingual-e5-small`). Rows are refreshed by
`tn_category_embedding_service.sync_category_embeddings` — a re-runnable
full upsert, not an append-only log — so `tn_category_id` is unique.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.core.database import Base

# Embedding dimensionality of `intfloat/multilingual-e5-small` (matches
# `ml_bot_answer_history.EMBEDDING_DIM`). Any change to the embedding model
# requires a new migration + a full re-sync of this table.
EMBEDDING_DIM = 384


class TnCategoryEmbedding(Base):
    """A single TN category with its readable path text and similarity embedding."""

    __tablename__ = "tn_category_embedding"

    id = Column(Integer, primary_key=True, index=True)
    tn_category_id = Column(Integer, unique=True, index=True, nullable=False)
    category_path_text = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<TnCategoryEmbedding(tn_category_id={self.tn_category_id})>"
