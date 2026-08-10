"""Backfill AI triage for tickets that predate the triage agent.

Slice 3 (single-box intake) merged BEFORE slice 4a (the triage agent).
Tickets created in that window have `texto_original` but ZERO `PropuestaIA`
rows, and nothing else in the system ever reprocesses them (obs #1400: the
board shows a truncated auto-title and nothing else for these — the worst
case of unstructured free-text input with no AI structuring at all).

Standalone script — same mapper-registry trap as
`scripts/audit_transiciones_tickets.py` (obs #1323/#1350):
`relationship("Usuario")` and friends are declared by STRING and only
resolve once every model has been imported somewhere in the running
process. Inside FastAPI, `app/main.py` does that; run standalone, nothing
does, unless we import them ourselves here — same fix as `alembic/env.py:6`.

Runs triage IN-PROCESS via `run_triage`, not through the HTTP endpoint:
this is a maintenance script an operator runs on the server, so minting a
token to go through `POST /tickets/{id}/triage` would add a step for no
benefit. Opens its own `SessionLocal()`/`get_triage_provider()`, the same
way the ml-questions bot's own background cycles open their own
`get_background_db()` session rather than reusing a request-scoped one.

`--dry-run` is the DEFAULT (lists candidates, makes ZERO Groq calls).
`--apply` is required to do real work. Groq's free tier for
`llama-3.3-70b-versatile` is 30 RPM / 1K RPD (obs #1299) — a fixed sleep
between calls keeps a backlog from tripping a 429, which
`OpenAICompatProvider` treats as PERMANENT (no retry): the ticket is simply
left unclassified. `run_triage` never re-raises that failure (spec:
"Degradation When Groq Is Unavailable" — it logs a warning and returns), so
this script cannot distinguish "rate limited" from other silent
degradation without changing that contract, EXCEPT for the 429 case
specifically: `OpenAICompatProvider` formats a 4xx as
`"{name} client error: {status_code}"`, and a small logging handler
attached around each call inspects that text.

Usage (GROQ_TICKETS_KEY only required for --apply; every other setting is
normally already in `.env` on the server — see `config.py`'s
`SettingsConfigDict(env_file=".env")`):

    cd backend && source venv/bin/activate
    python -m scripts.backfill_triage_tickets --dry-run
    python -m scripts.backfill_triage_tickets --apply
    python -m scripts.backfill_triage_tickets --apply --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.tickets.api.deps import get_triage_provider
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.ticket import Ticket
from app.tickets.services.triage_service import LlmProvider, run_triage

# Same mapper-registry trap as scripts/audit_transiciones_tickets.py — see
# that script's docstring and alembic/env.py:6 for the precedent. Do NOT
# remove these as "unused": they populate SQLAlchemy's global mapper
# registry so string-declared relationships (`relationship("Usuario")`,
# etc.) resolve outside of FastAPI's own import graph.
from app.models import *  # noqa: F401,F403
from app.tickets.models import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

_TRIAGE_LOGGER_NAME = "app.tickets.services.triage_service"
_SLEEP_BETWEEN_CALLS_SECONDS = 3.0  # ~20 RPM, under Groq's 30 RPM cap (obs #1299)


class _RateLimitDetector(logging.Handler):
    """Attached around ONE `run_triage` call at a time so a 429 is
    attributed to the right ticket. `run_triage` never re-raises the
    provider's `LlmProviderError` — it logs it via
    `logger.warning(..., exc_info=True)` and degrades to "unclassified".
    Grepping that captured exception text for '429' is the only signal
    available from outside `run_triage` without changing its contract.
    Substring match, not a parsed status code: a ticket whose own error
    text happened to contain '429' would false-positive here, but this
    only feeds a report bucket, never a retry/skip decision."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.hit_429 = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None and "429" in str(record.exc_info[1]):
            self.hit_429 = True


def find_candidate_tickets(db: Session, limit: Optional[int] = None) -> list:
    """Tickets with `texto_original` set and ZERO `PropuestaIA` rows of any
    `estado` — a discarded/replaced proposal still means triage RAN for
    that ticket. Idempotent by construction: once a ticket has at least one
    proposal, a re-run of this script never selects it again."""
    tiene_propuesta = db.query(PropuestaIA.id).filter(PropuestaIA.ticket_id == Ticket.id)
    query = (
        db.query(Ticket).filter(Ticket.texto_original.isnot(None)).filter(~tiene_propuesta.exists()).order_by(Ticket.id)
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def _preview(ticket) -> str:
    texto = (ticket.texto_original or "").replace("\n", " ").strip()
    return texto[:60]


def _print_candidatos(tickets: list) -> None:
    print(f"Tickets candidatos para backfill de triage IA: {len(tickets)}")
    for t in tickets:
        print(f"  #{t.id} | creado {t.created_at} | {_preview(t)}")


def _tiene_propuestas(ticket_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.query(PropuestaIA.id).filter(PropuestaIA.ticket_id == ticket_id).first() is not None
    finally:
        db.close()


async def _procesar(tickets: list, provider: LlmProvider) -> dict:
    resumen = {"procesados": 0, "con_propuestas": 0, "sin_clasificar_rate_limit": 0, "fallidos": 0}
    triage_logger = logging.getLogger(_TRIAGE_LOGGER_NAME)

    for i, ticket in enumerate(tickets):
        detector = _RateLimitDetector()
        triage_logger.addHandler(detector)
        try:
            await run_triage(ticket.id, provider)
            resumen["procesados"] += 1
            if _tiene_propuestas(ticket.id):
                resumen["con_propuestas"] += 1
            elif detector.hit_429:
                resumen["sin_clasificar_rate_limit"] += 1
        except Exception:
            # A per-ticket failure (including anything unexpected NOT
            # already swallowed by run_triage's own contract) must not
            # abort the whole batch — report it and move on.
            logger.exception("backfill triage: fallo inesperado en ticket #%s", ticket.id)
            resumen["fallidos"] += 1
        finally:
            triage_logger.removeHandler(detector)

        if i < len(tickets) - 1:
            await asyncio.sleep(_SLEEP_BETWEEN_CALLS_SECONDS)

    return resumen


def _print_resumen(resumen: dict) -> None:
    print("Resumen del backfill de triage IA:")
    print(f"  Procesados: {resumen['procesados']}")
    print(f"  Con propuestas escritas: {resumen['con_propuestas']}")
    print(f"  Sin clasificar por rate limit de Groq (429, sin reintento): {resumen['sin_clasificar_rate_limit']}")
    print(f"  Fallidos (error inesperado del script): {resumen['fallidos']}")
    sin_causa_identificada = resumen["procesados"] - resumen["con_propuestas"] - resumen["sin_clasificar_rate_limit"]
    if sin_causa_identificada > 0:
        print(
            f"  Sin propuestas por otra causa (respuesta no parseable, confianza baja, etc.): {sin_causa_identificada}"
        )


def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill de triage IA para tickets sin PropuestaIA.")
    # Mutually exclusive on purpose: `--dry-run --apply` together must be a
    # loud argparse error, never a silent "the last one wins" — this script
    # burns API quota and writes to the DB, so a real pre-push review
    # finding was that treating --dry-run as a no-op when --apply is also
    # present would let it run for real while the operator believes they
    # are still in dry-run mode.
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--apply",
        action="store_true",
        help="Ejecuta la triage real (llama a Groq). Sin esta bandera corre en dry-run.",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista los candidatos sin llamar a Groq (comportamiento por defecto, no requiere GROQ_TICKETS_KEY).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limita la cantidad de tickets a listar/procesar.")
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.apply

    provider: Optional[LlmProvider] = None
    if not dry_run:
        provider = get_triage_provider()
        if not provider.is_configured():
            print(
                "ERROR: GROQ_TICKETS_KEY no está configurada. No se puede ejecutar el backfill real "
                "(falta la clave para llamar a Groq). Configurala y volvé a correr con --apply.",
                file=sys.stderr,
            )
            return 1

    db = SessionLocal()
    try:
        tickets = find_candidate_tickets(db, limit=args.limit)
    finally:
        db.close()

    if dry_run:
        _print_candidatos(tickets)
        print("Dry-run: no se hizo ninguna llamada a Groq. Use --apply para ejecutar de verdad.")
        return 0

    print(f"Procesando {len(tickets)} ticket(s) con triage IA (esto puede tardar varios minutos)...")
    assert provider is not None  # the --apply path above always builds it
    resumen = asyncio.run(_procesar(tickets, provider))
    _print_resumen(resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
