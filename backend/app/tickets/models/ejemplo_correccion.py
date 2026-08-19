"""ORM model for `tickets_triage_ejemplos` — best-effort corpus of genuine
human corrections to AI triage proposals (tickets-triage-feedback PR3,
design "Best-effort correction capture behind a flag"), embedded for future
similarity-based few-shot retrieval. Mirrors `MlBotAnswerHistory`'s own
shape (`sdd/ml-bot-dynamic-fewshot`): rows are captured automatically at
confirm time when `TICKETS_TRIAGE_EJEMPLOS_CAPTURE` is on AND the confirm
resolved to a genuine correction (`PropuestaIA.estado == 'corregida'` — see
`confirmacion_service.confirmar()`), never for a plain ratification or
discard.

`propuesta_id` is UNIQUE: at most one captured example per proposal — a
proposal can only ever resolve to `corregida` once (`confirmar()` rejects a
non-`pendiente`/unreviewed-`ia_auto` proposal), so a second row for the same
`propuesta_id` would only ever come from a bug, not a legitimate re-correction.

`embedding` is nullable-free in the SAME sense as `MlBotAnswerHistory`: a
failed/skipped embed simply skips the insert entirely (see
`ejemplos_service.capturar_correccion`), never a dead row with a placeholder
vector.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.core.database import Base

# Embedding dimensionality of `intfloat/multilingual-e5-small` (matches
# `MlBotAnswerHistory.EMBEDDING_DIM` / `embedding_client._EMBEDDING_DIM`). Any
# change to the embedding model requires a new migration + backfill; this
# constant and the migration's column width must always match.
EMBEDDING_DIM = 384


class EjemploCorreccion(Base):
    """A single captured human correction of an AI triage proposal."""

    __tablename__ = "tickets_triage_ejemplos"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    propuesta_id = Column(Integer, ForeignKey("tickets_propuestas_ia.id"), nullable=False, unique=True)

    # VARCHAR + CHECK, not a PG ENUM — same rationale as `PropuestaIA.estado`/
    # `campo` (you cannot drop an enum value, so a migration downgrade()
    # would be a lie). Scoped to `vocabularios.CAMPOS_CORREGIBLES`
    # (severidad/urgencia only — the only campos a correction can target).
    campo = Column(String(20), nullable=False)

    texto = Column(Text, nullable=False)
    valor_ia = Column(String(20), nullable=False)
    valor_corregido = Column(String(20), nullable=False)

    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("campo IN ('severidad','urgencia')", name="ck_tickets_triage_ejemplos_campo"),)

    def __repr__(self) -> str:
        return f"<EjemploCorreccion propuesta_id={self.propuesta_id} campo={self.campo}>"
