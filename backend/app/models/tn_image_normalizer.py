"""Tienda Nube image normalizer — schema (slice 3).

Three tables:

- `tn_image_normalization_run`: one row per normalization run (batch).
- `tn_image_artifact`: one row per DISTINCT normalized output. Deliberately
  a separate table, not a column on the item row — the dedup key
  `(source_hash, normalization_params)` is a property of the artifact
  itself, and one artifact legitimately serves many EANs and many runs.
  Hanging the constraint on the item row would either forbid that reuse or
  force a nullable partial index.
- `tn_image_normalization_item`: one row per (run, EAN, slot) attempt.
  `inconclusive_reason` is its own column, not an error string folded into
  a generic detail blob: in the push stage `inconclusive` is a first-class
  state distinct from `failed`, and only that separation keeps a timed-out
  verification from ever authorizing a delete.

No readers or writers exist yet — that is intentional for this slice.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TnImageNormalizationRun(Base):
    """One normalization run (batch of EAN/slot items processed together)."""

    __tablename__ = "tn_image_normalization_run"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)

    preset = Column(SmallInteger, nullable=False)
    fill_color = Column(String(7), nullable=False, default="#ffffff")
    output_format = Column(String(8), nullable=False)
    quality = Column(SmallInteger, nullable=False)
    max_output_bytes = Column(Integer, nullable=False)
    params_fingerprint = Column(String(32), nullable=False)

    # Safe default is not optional: no stage may write to Tienda Nube
    # without a human having seen a dry-run first.
    dry_run = Column(Boolean, nullable=False, default=True)

    state = Column(String(24), nullable=False)
    totals = Column(JSONB, nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    created_by = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<TnImageNormalizationRun(id={self.id}, state='{self.state}', dry_run={self.dry_run})>"


class TnImageArtifact(Base):
    """A distinct normalized output, deduplicated by (source_hash, params).

    Separate table on purpose: this dedup key is a property of the
    artifact, not of an item row — one artifact legitimately serves many
    EANs and many runs.
    """

    __tablename__ = "tn_image_artifact"

    id = Column(Integer, primary_key=True, index=True)
    source_hash = Column(String(64), nullable=False)
    normalization_params = Column(String(32), nullable=False)
    output_path = Column(Text, nullable=True)
    output_hash = Column(String(64), nullable=True)
    output_bytes = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("source_hash", "normalization_params", name="uq_tn_img_artifact_dedup"),)

    def __repr__(self) -> str:
        return f"<TnImageArtifact(id={self.id}, source_hash='{self.source_hash[:8]}...')>"


class TnImageNormalizationItem(Base):
    """One (run, EAN, source slot) attempt.

    `inconclusive_reason` is deliberately its own column, not an error
    string stuffed into a detail blob: `inconclusive` is a first-class
    state distinct from `failed`, and only that separation keeps a
    timed-out verification from ever authorizing a delete.
    """

    __tablename__ = "tn_image_normalization_item"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("tn_image_normalization_run.id"), nullable=False)
    ean = Column(String(20), nullable=False)
    tn_product_id = Column(Integer, nullable=True)
    source_slot = Column(SmallInteger, nullable=False)
    source_url = Column(Text, nullable=False)
    source_hash = Column(String(64), nullable=True)
    artifact_id = Column(Integer, ForeignKey("tn_image_artifact.id"), nullable=True)
    state = Column(String(32), nullable=False)
    inconclusive_reason = Column(Text, nullable=True)
    tn_image_id = Column(Integer, nullable=True)
    claim_definitive = Column(Boolean, nullable=True)
    attempts = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    run = relationship("TnImageNormalizationRun")
    artifact = relationship("TnImageArtifact")

    __table_args__ = (
        # The review grid's main filter: items by run, grouped by state.
        Index("ix_tn_image_normalization_item_run_id_state", "run_id", "state"),
        Index("ix_tn_image_normalization_item_ean", "ean"),
        Index("ix_tn_image_normalization_item_tn_product_id", "tn_product_id"),
    )

    def __repr__(self) -> str:
        return f"<TnImageNormalizationItem(id={self.id}, ean='{self.ean}', state='{self.state}')>"
