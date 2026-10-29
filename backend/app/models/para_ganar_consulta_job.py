"""PARA GANAR consultation jobs (A1 / P6): PM- or cron-owned MLA batches.

Each job owns many items (one row per MLA). The ML worker drains items with
fairness across jobs; revision outcomes still land in `para_ganar_revision_mla`.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base

SOURCE_MANUAL = "manual"
SOURCE_PERIODIC = "periodic"
SOURCES = (SOURCE_MANUAL, SOURCE_PERIODIC)

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
JOB_STATUSES = (JOB_PENDING, JOB_RUNNING, JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED)

ITEM_PENDING = "pending"
ITEM_PROCESSING = "processing"
ITEM_DONE = "done"
ITEM_SKIPPED = "skipped"
ITEM_FAILED = "failed"
ITEM_STATUSES = (ITEM_PENDING, ITEM_PROCESSING, ITEM_DONE, ITEM_SKIPPED, ITEM_FAILED)


class ParaGanarConsultaJob(Base):
    """One consultation batch (manual Advisor scope or periodic Periodicidad)."""

    __tablename__ = "para_ganar_consulta_job"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default=JOB_PENDING, index=True)
    total_count = Column(Integer, nullable=False, default=0)
    done_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    pendiente_count = Column(Integer, nullable=False, default=0)
    sin_novedades_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    # Fairness: claim prefers jobs with oldest (or null) last_progress_at.
    last_progress_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    created_by = relationship("Usuario", foreign_keys=[created_by_id])
    items = relationship(
        "ParaGanarConsultaJobItem",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class ParaGanarConsultaJobItem(Base):
    """One MLA inside a consultation job."""

    __tablename__ = "para_ganar_consulta_job_item"
    __table_args__ = (
        UniqueConstraint("job_id", "mla", name="uq_para_ganar_consulta_job_item_job_mla"),
        Index("ix_para_ganar_consulta_job_item_claim", "status", "job_id", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(
        Integer,
        ForeignKey("para_ganar_consulta_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mla = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default=ITEM_PENDING)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    revision_estado = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("ParaGanarConsultaJob", back_populates="items")
