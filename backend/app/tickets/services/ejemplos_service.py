"""Best-effort correction capture (tickets-triage-feedback PR3, design
"Best-effort correction capture behind a flag"). This PR ships only the
CAPTURE half — `capturar_correccion` — dark-launched behind
`TICKETS_TRIAGE_EJEMPLOS_CAPTURE` (default False). A future PR adds
retrieval against `tickets_triage_ejemplos`.

Scheduled from `confirmar_propuesta` (`propuestas.py`) via
`BackgroundTasks.add_task`, gated on `confirmacion_service.confirmar()`'s
return having `estado == 'corregida'` — the single site that is the whole
"genuine corrections only" gate: a plain ratification or a discard never
reaches this function at all.

Mirrors `publisher_service._capture_answer_history`'s shape exactly
(sdd/ml-bot-dynamic-fewshot, PR2): short-lived session A loads plain scalars
and closes (pool-exhaustion lesson, PR #811's `get_background_db` short-lived
blocks pattern), `embed_passage` runs OUTSIDE any session, then a short-lived
session B inserts. The whole function is wrapped in a bare `except Exception`
— capture must NEVER fail a confirm that has already committed."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.core.database import get_background_db
from app.services.ml_questions.embedding_client import embed_passage
from app.tickets.models.ejemplo_correccion import EjemploCorreccion
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.ticket import Ticket

logger = logging.getLogger(__name__)


async def capturar_correccion(propuesta_id: int) -> None:
    """Best-effort: loads the confirmed correction, embeds its ticket's
    original text, and inserts one `tickets_triage_ejemplos` row. Never
    raises — flag off returns before any DB work, and any failure (missing
    row, embed failure, DB error) is swallowed here, logged, and skips the
    capture entirely (design: never insert a dead row with a
    null/placeholder embedding)."""
    if not settings.TICKETS_TRIAGE_EJEMPLOS_CAPTURE:
        # Checked BEFORE any session work: a flag-off capture must be a true
        # no-op, never a pool checkout (PR #811 pool-exhaustion lesson).
        return

    try:
        with get_background_db() as db:
            propuesta = db.query(PropuestaIA).filter(PropuestaIA.id == propuesta_id).first()
            if propuesta is None:
                return
            ticket = db.query(Ticket).filter(Ticket.id == propuesta.ticket_id).first()
            if ticket is None:
                return

            texto = ticket.texto_original
            ticket_id = ticket.id
            campo = propuesta.campo
            valor_ia = propuesta.valor_propuesto.get("valor") if propuesta.valor_propuesto else None
            valor_corregido = propuesta.valor_corregido

        if not texto or valor_ia is None or valor_corregido is None:
            # Nothing meaningful to embed/capture — skip rather than insert
            # a row with a null AI value or corrected value.
            return

        embedding = await embed_passage(texto)
        if embedding is None:
            # No session while calling embed_passage; a None result means
            # capture is skipped entirely — never a dead row with a
            # null/placeholder embedding.
            return

        with get_background_db() as db:
            db.add(
                EjemploCorreccion(
                    ticket_id=ticket_id,
                    propuesta_id=propuesta_id,
                    campo=campo,
                    texto=texto,
                    valor_ia=valor_ia,
                    valor_corregido=valor_corregido,
                    embedding=embedding,
                    active=True,
                )
            )
    except Exception:  # noqa: BLE001 — capture must never fail a real confirm.
        logger.warning(
            "tickets triage: correction capture failed for propuesta %s (best-effort, confirm unaffected)",
            propuesta_id,
            exc_info=True,
        )
