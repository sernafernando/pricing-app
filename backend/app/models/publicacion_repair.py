"""Tracker tables for publication repair jobs (envio / sku).

Separate from user-price `auditoria` and from `free_shipping_fix_log`.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

JOB_ENVIO = "envio"
JOB_SKU = "sku"

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_PARTIAL = "partial"

TRIGGER_PUBLICATIONS_FULL = "publications_full"
TRIGGER_MANUAL = "manual"

ACTION_CHANGED = "changed"
ACTION_SKIPPED = "skipped"
ACTION_ERROR = "error"


class PublicacionRepairRun(Base):
    __tablename__ = "publicacion_repair_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    scanned = Column(Integer, nullable=False, server_default="0")
    changed = Column(Integer, nullable=False, server_default="0")
    skipped = Column(Integer, nullable=False, server_default="0")
    errors = Column(Integer, nullable=False, server_default="0")
    error_message = Column(Text, nullable=True)
    trigger = Column(String(40), nullable=False)

    __table_args__ = (Index("ix_publicacion_repair_run_started", "started_at"),)


class PublicacionRepairEvent(Base):
    __tablename__ = "publicacion_repair_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("publicacion_repair_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mla_id = Column(String(50), nullable=False, index=True)
    item_id = Column(BigInteger, nullable=True)
    action = Column(String(20), nullable=False)
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_publicacion_repair_event_run_mla", "run_id", "mla_id"),)
