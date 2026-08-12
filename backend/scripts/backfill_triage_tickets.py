"""Backfill AI triage for tickets that predate the triage agent, and for
tickets missing only SOME proposable fields.

Slice 3 (single-box intake) merged BEFORE slice 4a (the triage agent), and
33/35 production tickets predate single-box intake entirely (they carry a
human-written `titulo` + `descripcion` from the OLD two-field form instead
of `texto_original`). Nothing else in the system ever reprocesses either
group: obs #1400 (a truncated auto-title with no AI structuring at all) and
obs #1409 (ticket #34 already had `titulo`/`resumen` but could never get
`sector`/`tipo_ticket` because the old candidate query picked tickets with
ZERO proposals, all-or-nothing per ticket instead of per field).

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

from sqlalchemy import and_, or_
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


class _TriageOutcomeDetector(logging.Handler):
    """Attached around ONE `run_triage` call at a time so its outcome is
    attributed to the right ticket. `run_triage` never re-raises a
    failure (spec: "Degradation When Groq Is Unavailable") — it always
    logs a WARNING and returns, so this is the only signal available from
    outside without changing that contract:

    - `did_fail` + `hit_429`: the provider call itself failed with a 429
      (rate limited — Groq never even returned a response to classify).
    - `did_fail` + not `hit_429`: the call failed for another reason
      (timeout, non-429 HTTP error, malformed/unparseable JSON, a schema
      mismatch, or a write-phase failure such as the partial unique index
      backstop) — a REAL problem worth investigating, distinct from a
      rate limit that clears on its own.
    - not `did_fail`: the call succeeded and parsed. Combined with "zero
      NEW proposal rows written" (checked by the caller), this means every
      applicable field was null or below the confidence threshold — a
      LEGITIMATE, expected outcome (obs #1371's gate doing its job), not a
      bug to chase. Previously lumped together with the line above under
      one "sin propuestas por otra causa" bucket, which sent the
      maintainer chasing the wrong cause.

    Substring match, not a parsed status code: a ticket whose own error
    text happened to contain '429' would false-positive here, but this
    only feeds a report bucket, never a retry/skip decision.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.did_fail = False
        self.hit_429 = False

    def emit(self, record: logging.LogRecord) -> None:
        # Common prefix, not the full "...failed for ticket" phrase: that
        # only matched ONE of `run_triage`'s two failure warnings — a
        # write-phase failure ("failed to write proposals for ticket #%s",
        # the partial unique index backstop) slipped through and was
        # miscounted as a legitimate confidence gate. Same review finding
        # this bucket split was written to prevent, entering through the
        # other message.
        if "tickets triage: failed" not in record.getMessage():
            return
        self.did_fail = True
        if record.exc_info and record.exc_info[1] is not None and "429" in str(record.exc_info[1]):
            self.hit_429 = True


# Fields `run_triage` always attempts for any ticket with text to classify
# (obs #1409's gap). `titulo` is NOT here — it only applies when
# `texto_original` is set (see below) — and `metadata_ia` is deliberately
# excluded: it is optional BY DESIGN (`run_triage` only writes it when the
# response actually carries something useful), so treating it as
# "missing" would flag every ticket forever, not just genuine gaps. Kept
# in sync with `run_triage`'s own write loop in `triage_service.py`.
CAMPOS_PROPUESTA_BASE = ("sector", "tipo_ticket", "severidad", "urgencia", "resumen")

# Same (ticket, campo) → "already has an active proposal" predicate as
# `triage_service._ya_tiene_propuesta_activa` — kept consistent on
# purpose: if the two drift apart, this script could pick up a ticket
# `run_triage` will immediately skip for every field, wasting a Groq call.
_ESTADOS_PROPUESTA_ACTIVA = ("pendiente", "confirmada")


def find_candidate_tickets(db: Session, limit: Optional[int] = None) -> list:
    """Tickets with SOME text to classify (`texto_original` OR, falling
    back, `descripcion` — same fallback `run_triage` itself applies) that
    are missing an active proposal for AT LEAST ONE applicable field —
    reasoned PER FIELD, not per ticket. `titulo` only counts as
    "applicable" when `texto_original` is set: a ticket predating
    single-box intake never gets an AI titulo proposed at all (its titulo
    is a person's own words), so a missing titulo there is not a gap.

    Idempotent in the sense that matters: `_ya_tiene_propuesta_activa`
    inside `run_triage` still refuses to duplicate a field that already
    has an active proposal, so re-running this script never writes twice.
    A ticket whose remaining gap is a genuinely confidence-gated judgement
    field CAN be re-selected on a later run (there is no DB row to
    distinguish "never attempted" from "attempted and gated") — a
    conscious tradeoff for a manually-run maintenance script, not a
    correctness bug.
    """

    def _sin_propuesta_activa(campo: str):
        activa = db.query(PropuestaIA.id).filter(
            PropuestaIA.ticket_id == Ticket.id,
            PropuestaIA.campo == campo,
            PropuestaIA.estado.in_(_ESTADOS_PROPUESTA_ACTIVA),
        )
        return ~activa.exists()

    falta_campo_base = or_(*(_sin_propuesta_activa(campo) for campo in CAMPOS_PROPUESTA_BASE))
    falta_titulo = and_(Ticket.texto_original.isnot(None), _sin_propuesta_activa("titulo"))

    query = (
        db.query(Ticket)
        .filter(or_(Ticket.texto_original.isnot(None), Ticket.descripcion.isnot(None)))
        .filter(or_(falta_campo_base, falta_titulo))
        .order_by(Ticket.id)
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def _preview(ticket) -> str:
    texto = (ticket.texto_original or ticket.descripcion or "").replace("\n", " ").strip()
    return texto[:60]


def _print_candidatos(tickets: list) -> None:
    print(f"Tickets candidatos para backfill de triage IA: {len(tickets)}")
    for t in tickets:
        print(f"  #{t.id} | creado {t.created_at} | {_preview(t)}")


def _contar_propuestas(db: Session, ticket_id: int) -> int:
    return db.query(PropuestaIA.id).filter(PropuestaIA.ticket_id == ticket_id).count()


async def _procesar(tickets: list, provider: LlmProvider) -> dict:
    resumen = {
        "procesados": 0,
        "con_propuestas": 0,
        "rate_limit": 0,
        "fallo_llm_o_parseo": 0,
        "sin_propuestas_por_confianza": 0,
        "fallidos": 0,
    }
    triage_logger = logging.getLogger(_TRIAGE_LOGGER_NAME)
    # ONE session reused for the (read-only) before/after COUNT check
    # across the whole batch — real pre-push review finding: opening a
    # throwaway SessionLocal() twice per ticket (up to 70 connections for
    # 35 tickets) is exactly the disposable-session-in-a-loop pattern
    # behind this project's 2026-06-24 pool exhaustion incident (PR #811).
    # Never holds a transaction open across `run_triage`'s own network
    # call — it is only ever touched here, between calls.
    conteo_db = SessionLocal()
    try:
        for i, ticket in enumerate(tickets):
            detector = _TriageOutcomeDetector()
            triage_logger.addHandler(detector)
            try:
                antes = _contar_propuestas(conteo_db, ticket.id)
                await run_triage(ticket.id, provider)
                resumen["procesados"] += 1
                if _contar_propuestas(conteo_db, ticket.id) > antes:
                    resumen["con_propuestas"] += 1
                elif detector.hit_429:
                    resumen["rate_limit"] += 1
                elif detector.did_fail:
                    resumen["fallo_llm_o_parseo"] += 1
                else:
                    resumen["sin_propuestas_por_confianza"] += 1
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
    finally:
        conteo_db.close()

    return resumen


def _print_resumen(resumen: dict) -> None:
    print("Resumen del backfill de triage IA:")
    print(f"  Procesados: {resumen['procesados']}")
    print(f"  Con propuestas nuevas escritas: {resumen['con_propuestas']}")
    print(f"  Sin clasificar por rate limit de Groq (429, sin reintento): {resumen['rate_limit']}")
    print(f"  Fallo del proveedor o respuesta no parseable (no es rate limit): {resumen['fallo_llm_o_parseo']}")
    print(
        "  Sin propuestas nuevas por confianza baja (gateado, comportamiento esperado): "
        f"{resumen['sin_propuestas_por_confianza']}"
    )
    print(f"  Fallidos (error inesperado del script): {resumen['fallidos']}")


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
