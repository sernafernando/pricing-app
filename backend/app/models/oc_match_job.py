"""
OC-match jobs and renglones — persist extract/match results for Compras.

Pricing DB is the source of truth. The upload hook (Phase 2) enqueues a
row; the worker (Phase 3) fills renglones, acta, and excel_rel_path.

Tables:
  - compras_oc_match_jobs: one row per (pedido_id, attachment_id)
  - compras_oc_match_renglones: extract + match fields per line
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class OcMatchJob(Base):
    """Background OC-match job for one pedido adjunto."""

    __tablename__ = "compras_oc_match_jobs"

    STATUS_QUEUED: str = "queued"
    STATUS_RUNNING: str = "running"
    STATUS_DONE: str = "done"
    STATUS_ERROR: str = "error"
    STATUS_SKIPPED: str = "skipped"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attachment_id = Column(
        BigInteger,
        ForeignKey("compras_adjuntos.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(String(20), nullable=False, server_default="queued")
    error_message = Column(Text, nullable=True)
    acta = Column(Text, nullable=True)
    excel_rel_path = Column(String(500), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    pedido = relationship("PedidoCompra")
    adjunto = relationship("CompraAdjunto")
    renglones = relationship(
        "OcMatchRenglon",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','error','skipped')",
            name="ck_oc_match_jobs_status",
        ),
        UniqueConstraint(
            "pedido_id",
            "attachment_id",
            name="uq_oc_match_jobs_pedido_attachment",
        ),
        Index("ix_oc_match_jobs_status", "status"),
        Index("ix_oc_match_jobs_pedido_id", "pedido_id"),
        Index("ix_oc_match_jobs_started_at", "started_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<OcMatchJob(id={self.id}, pedido_id={self.pedido_id}, "
            f"attachment_id={self.attachment_id}, status={self.status!r})>"
        )


class OcMatchRenglon(Base):
    """One extracted/matched line belonging to an OC-match job."""

    __tablename__ = "compras_oc_match_renglones"

    MATCH_OK: str = "ok"
    MATCH_NO_HALLADO: str = "no_hallado"
    MATCH_OMITIDO: str = "omitido"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(
        BigInteger,
        ForeignKey("compras_oc_match_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    indice = Column(Integer, nullable=False)

    descripcion = Column(Text, nullable=True)
    cantidad = Column(Numeric(18, 4), nullable=True)
    precio_unitario = Column(Numeric(18, 4), nullable=True)
    moneda = Column(String(3), nullable=True)
    codigo_proveedor = Column(String(100), nullable=True)
    codigo_fabricante = Column(String(100), nullable=True)
    ean_extract = Column(String(32), nullable=True)
    ean_ultimos4 = Column(String(4), nullable=True)
    omitir = Column(Boolean, nullable=False, server_default="false")
    motivo_omitir = Column(Text, nullable=True)

    match_estado = Column(String(20), nullable=True)
    item_id = Column(String(64), nullable=True)
    ean = Column(String(32), nullable=True)
    confianza = Column(String(16), nullable=True)
    motivo = Column(Text, nullable=True)

    job = relationship("OcMatchJob", back_populates="renglones")

    __table_args__ = (
        CheckConstraint(
            "match_estado IS NULL OR match_estado IN ('ok','no_hallado','omitido')",
            name="ck_oc_match_renglones_match_estado",
        ),
        UniqueConstraint("job_id", "indice", name="uq_oc_match_renglones_job_indice"),
        Index("ix_oc_match_renglones_job_id", "job_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<OcMatchRenglon(id={self.id}, job_id={self.job_id}, "
            f"indice={self.indice}, match_estado={self.match_estado!r})>"
        )
