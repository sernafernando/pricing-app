from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.core.database import Base


class PropuestaIA(Base):
    """
    AI-generated proposal for a single ticket field (severidad, urgencia,
    titulo, resumen, ...). A proposal never writes to `tickets` — a human
    (or, later, an auto-apply flag) confirms it via a dedicated
    confirmation service (tickets-ai-triage PR 4b), which is the only code
    path allowed to write `tickets.<campo>`.

    `estado` is a 4-state lifecycle, not a boolean, because "human
    rejected" (`descartada`) must never re-surface as `pendiente` again —
    see the partial unique index below and the confirmation service's
    invariant (enforced in PR 4b, not here).

    VARCHAR + CHECK for `estado` (not a PG ENUM): you cannot drop a value
    from a Postgres enum type, so a migration `downgrade()` would be a
    lie. Same rationale as `Ticket.severidad`/`Ticket.urgencia` (PR 2a).
    """

    __tablename__ = "tickets_propuestas_ia"

    # No index=True here: the primary key already gets a unique index from
    # Postgres for free. Adding index=True would make the model expect an
    # extra `ix_tickets_propuestas_ia_id` that the migration never creates,
    # which is exactly the kind of model/migration drift `alembic revision
    # --autogenerate` would flag later.
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)

    campo = Column(String(50), nullable=False)
    valor_propuesto = Column(JSONB, nullable=False)
    confianza = Column(Numeric(3, 2), nullable=True)
    modelo = Column(String(60), nullable=True)
    run_id = Column(UUID(as_uuid=True), nullable=True)

    estado = Column(String(20), nullable=False, default="pendiente", server_default="pendiente")

    confirmado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    confirmado_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente','confirmada','descartada','reemplazada')",
            name="ck_tickets_propuestas_ia_estado",
        ),
        # Partial unique index: only one PENDING proposal per (ticket_id,
        # campo) at a time. Once a proposal is confirmada/descartada/
        # reemplazada, a fresh triage run may write a new pendiente row for
        # the same pair without violating uniqueness — a plain unique
        # constraint would wrongly block that. Postgres-only (`WHERE`
        # clause on a unique index); see @pytest.mark.postgres tests.
        # SQLite silently ignores `postgresql_where` and creates a FULL
        # unique index on (ticket_id, campo) instead — a test using the
        # SQLite-backed `db` fixture to write a second, non-pending
        # proposal for the same pair would fail for a reason that does not
        # exist in production. Exercise that scenario only via the
        # Postgres-backed `pg_tickets_db` fixture.
        Index(
            "uq_tickets_propuestas_ia_ticket_campo_pendiente",
            "ticket_id",
            "campo",
            unique=True,
            postgresql_where=text("estado = 'pendiente'"),
        ),
    )

    def __repr__(self):
        return f"<PropuestaIA Ticket#{self.ticket_id} {self.campo}={self.estado}>"
