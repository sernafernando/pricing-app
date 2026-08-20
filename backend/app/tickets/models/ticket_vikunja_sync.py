from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class TicketVikunjaSync(Base):
    """Ledger row tracking the sync state of one ticket towards Vikunja
    (sdd/tickets-sync-vikunja, PR 1: client + ledger table only — nothing
    writes to this table yet, that's PR 2/3).

    One row per ticket (`ticket_id` is UNIQUE, enforced at the DB level so a
    duplicate claim/create can never silently double-post the same ticket as
    two separate Vikunja tasks). `estado` tracks the sync lifecycle:
    pendiente -> enviando -> sincronizado | ambiguo | error.
    """

    __tablename__ = "tickets_vikunja_sync"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vikunja_task_id = Column(Integer, nullable=True)
    estado = Column(String(20), nullable=False, default="pendiente", index=True)
    intentos = Column(SmallInteger, nullable=False, default=0)
    ultimo_error = Column(String(500), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    notificado_at = Column(DateTime(timezone=True), nullable=True)
    adjuntos_pendientes = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_tickets_vikunja_sync_ticket_id"),
        Index("ix_tickets_vikunja_sync_estado_updated_at", "estado", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<TicketVikunjaSync ticket_id={self.ticket_id} estado={self.estado}>"
