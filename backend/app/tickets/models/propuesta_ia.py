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

    # NULL for every outcome except a correction (tickets-triage-feedback
    # PR1): the human-picked value on a `corregida` row. Together with
    # `estado`, the four proposal outcomes (ratified/corrected/discarded/
    # from scratch) become structurally distinguishable with no timestamp
    # or value-inequality inference — see the table in
    # `confirmacion_service.confirmar()`'s docstring.
    valor_corregido = Column(String(20), nullable=True)

    confirmado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    confirmado_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # 'corregida' added by tickets-triage-feedback PR1
        # (alembic/versions/20260813_propuesta_corregida.py): a confirm
        # carrying a corrected value for severidad/urgencia. Still
        # VARCHAR + CHECK, not a PG ENUM — an enum value can never be
        # dropped, so that migration's `downgrade()` would be a lie.
        CheckConstraint(
            "estado IN ('pendiente','confirmada','descartada','reemplazada','corregida')",
            name="ck_tickets_propuestas_ia_estado",
        ),
        # Campo-agnostic union of both correctable vocabularies
        # (severidad ∪ urgencia, see `vocabularios.VOCABULARIOS`) — mirrors
        # the two-layer shape `campo`'s own CHECK below already uses: the
        # per-campo correlation (severidad values only make sense on a
        # severidad proposal) stays in the app
        # (`vocabularios.CAMPOS_CORREGIBLES` + `_resolver_correccion`), the
        # DB only blocks a value outside EITHER vocabulary entirely.
        CheckConstraint(
            "valor_corregido IS NULL OR valor_corregido IN "
            "('trivial','menor','mayor','critica','baja','normal','alta','inmediata')",
            name="ck_tickets_propuestas_ia_valor_corregido",
        ),
        # DB-level mirror of `confirmacion_service.CAMPOS_CONFIRMABLES` — a
        # second, independent enforcement layer on top of the app-level
        # allowlist enforced in `_aplicar_confirmacion()`: even a raw INSERT
        # or a future app bug can never smuggle in a value like 'estado_id'
        # that would let confirmation write straight through the
        # workflow-transition engine (PR 1). If a future slice adds another
        # confirmable field, THIS constraint AND
        # `confirmacion_service.CAMPOS_CONFIRMABLES` must both be updated,
        # plus a new migration (see
        # alembic/versions/20260806_campo_check_ia.py,
        # 20260810_sector_tipo_metadata_check_ia.py).
        # VARCHAR + CHECK, not a PG ENUM — same rationale as `estado` above.
        CheckConstraint(
            "campo IN ('severidad','urgencia','titulo','resumen','sector','tipo_ticket','metadata_ia')",
            name="ck_tickets_propuestas_ia_campo",
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
